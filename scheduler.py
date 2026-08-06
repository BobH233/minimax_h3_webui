from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import Settings
from database import Database
from h3_client import H3APIError, H3Client

LOGGER = logging.getLogger(__name__)


def generation_progress(raw: dict[str, Any]) -> tuple[float | None, str]:
    try:
        progress = max(0.0, min(100.0, float(raw.get("progress"))))
    except (TypeError, ValueError):
        progress = None

    stage = "正在生成"
    try:
        current_step = int(raw.get("current_step"))
        total_steps = int(raw.get("total_steps"))
    except (TypeError, ValueError):
        current_step = total_steps = None
    if current_step is not None and total_steps and 0 <= current_step <= total_steps:
        stage = f"正在去噪 · {current_step}/{total_steps} 步"
    if raw.get("generation_stage") == "postprocessing":
        stage = "正在解码与保存"
    return progress, stage


class QueueWorker:
    def __init__(
        self,
        settings: Settings,
        database: Database,
        client: H3Client,
        backend_id: str = "primary",
    ):
        self.settings = settings
        self.database = database
        self.client = client
        self.backend_id = backend_id
        self._wake = threading.Event()
        self._closed = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name=f"h3-queue-{backend_id}", daemon=True
        )

    def start(self) -> None:
        self._recover()
        self._thread.start()

    def close(self) -> None:
        self._closed.set()
        self._wake.set()
        self._thread.join(timeout=3)

    def notify(self) -> None:
        self._wake.set()

    def _recover(self) -> None:
        now = time.time()
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET status = 'failed', stage = '提交已中断',
                    error = '服务重启前未取得推理任务 ID', updated_at = ?, completed_at = ?
                WHERE status = 'submitting' AND remote_id IS NULL AND deleted_at IS NULL
                """,
                (now, now),
            )

    def _run(self) -> None:
        while not self._closed.is_set():
            health = self.client.health()
            job = self._claim_next(allow_new=health.online)
            if job is None:
                self._wake.wait(timeout=1)
                self._wake.clear()
                continue
            self._process(job)

    def _claim_next(self, allow_new: bool = True) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            active = connection.execute(
                """
                SELECT * FROM jobs
                WHERE status IN ('submitting', 'generating')
                  AND backend_id = ? AND remote_id IS NOT NULL
                  AND deleted_at IS NULL
                ORDER BY started_at, created_at LIMIT 1
                """,
                (self.backend_id,),
            ).fetchone()
            if active is not None:
                connection.commit()
                return dict(active)

            enabled = connection.execute(
                "SELECT dispatch_enabled FROM backend_controls WHERE id = ?",
                (self.backend_id,),
            ).fetchone()
            if not allow_new or (enabled is not None and not enabled[0]):
                connection.commit()
                return None

            row = connection.execute(
                """
                SELECT jobs.*
                FROM jobs JOIN users ON users.id = jobs.user_id
                WHERE jobs.status = 'queued' AND jobs.deleted_at IS NULL
                ORDER BY users.weight DESC, jobs.created_at ASC, jobs.id ASC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            now = time.time()
            changed = connection.execute(
                """
                UPDATE jobs SET status = 'submitting', stage = '正在提交',
                    backend_id = ?, started_at = COALESCE(started_at, ?), updated_at = ?
                WHERE id = ? AND status = 'queued'
                """,
                (self.backend_id, now, now, row["id"]),
            ).rowcount
            connection.commit()
            if not changed:
                return None
            job = dict(row)
            job.update(
                status="submitting",
                stage="正在提交",
                backend_id=self.backend_id,
                started_at=now,
            )
            return job

    def _process(self, job: dict[str, Any]) -> None:
        try:
            remote_id = job.get("remote_id")
            if not remote_id:
                remote_id = self.client.create_video(json.loads(job["payload_json"]))
                job["remote_id"] = remote_id
                self._update(
                    job["id"],
                    status="generating",
                    stage="正在生成",
                    remote_id=remote_id,
                    progress=0,
                )
            self._poll(job["id"], remote_id, job)
        except H3APIError as exc:
            LOGGER.warning("推理任务失败 job=%s category=%s", job["id"], exc.category)
            if not job.get("remote_id") and exc.retryable:
                self._requeue(job["id"], str(exc))
            else:
                self._finish(job["id"], "failed", "生成失败", str(exc))
        except Exception:
            LOGGER.exception("任务处理异常 job=%s", job["id"])
            self._finish(job["id"], "failed", "生成失败", "任务处理发生错误")

    def _poll(self, job_id: str, remote_id: str, job: dict[str, Any]) -> None:
        started_at = float(job.get("started_at") or time.time())
        failures = 0
        while not self._closed.is_set():
            if time.time() - started_at > self.settings.task_timeout_seconds:
                self._finish(job_id, "failed", "生成超时", "任务超过自动查询时限")
                return
            try:
                status = self.client.get_task(remote_id)
                failures = 0
            except H3APIError as exc:
                if not exc.retryable:
                    raise
                failures += 1
                self._update(job_id, stage="连接中断，正在重试")
                time.sleep(min(self.settings.poll_seconds * 2**min(failures, 4), 15))
                continue

            progress, stage = generation_progress(status.raw)

            if status.status == "succeeded":
                self._download(job_id, remote_id, job)
                return
            if status.status in {"failed", "cancelled"}:
                self._finish(
                    job_id,
                    status.status,
                    "生成失败" if status.status == "failed" else "已取消",
                    status.error,
                )
                return
            self._update(
                job_id,
                status="generating",
                stage=stage,
                error=status.error,
                progress=progress,
            )
            time.sleep(self.settings.poll_seconds)

    def _download(self, job_id: str, remote_id: str, job: dict[str, Any]) -> None:
        user_dir = self.settings.outputs_root / job["user_id"]
        short_id = re.sub(r"[^A-Za-z0-9]", "", remote_id)[:8] or "task"
        filename = (
            f"{datetime.now(timezone.utc):%Y%m%d}-{short_id}-seed{job['seed']}.mp4"
        )
        self._update(job_id, stage="正在保存", progress=99)
        output = self.client.download_content(remote_id, user_dir / filename)
        now = time.time()
        started_at = float(job.get("started_at") or now)
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE jobs SET status = 'succeeded', stage = '生成完成',
                    output_path = ?, error = NULL, progress = 100,
                    completed_at = ?, generation_seconds = ?, updated_at = ?
                WHERE id = ?
                """,
                (str(output), now, max(0, now - started_at), now, job_id),
            )

    def _finish(
        self, job_id: str, status: str, stage: str, error: str | None
    ) -> None:
        now = time.time()
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE jobs SET status = ?, stage = ?, error = ?,
                    completed_at = ?, updated_at = ? WHERE id = ?
                """,
                (status, stage, error, now, now, job_id),
            )

    def _requeue(self, job_id: str, error: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE jobs SET status = 'queued', stage = '等待可用实例',
                    backend_id = NULL, remote_id = NULL, started_at = NULL,
                    progress = NULL, error = ?, updated_at = ? WHERE id = ?
                """,
                (error[:500], time.time(), job_id),
            )

    def _update(self, job_id: str, **changes: Any) -> None:
        changes["updated_at"] = time.time()
        columns = ", ".join(f"{name} = ?" for name in changes)
        values = list(changes.values()) + [job_id]
        with self.database.connect() as connection:
            connection.execute(f"UPDATE jobs SET {columns} WHERE id = ?", values)


class QueueWorkerPool:
    def __init__(
        self, settings: Settings, database: Database, clients: dict[str, H3Client]
    ):
        self.database = database
        self.clients = clients
        self.workers = {
            backend_id: QueueWorker(settings, database, client, backend_id)
            for backend_id, client in clients.items()
        }

    def start(self) -> None:
        now = time.time()
        with self.database.connect() as connection:
            connection.executemany(
                """
                INSERT INTO backend_controls(id, dispatch_enabled, updated_at)
                VALUES (?, 1, ?) ON CONFLICT(id) DO NOTHING
                """,
                [(backend_id, now) for backend_id in self.workers],
            )
        for worker in self.workers.values():
            worker.start()

    def close(self) -> None:
        for worker in self.workers.values():
            worker.close()

    def notify(self) -> None:
        for worker in self.workers.values():
            worker.notify()

    def set_dispatch_enabled(self, backend_id: str, enabled: bool) -> None:
        if backend_id not in self.workers:
            raise KeyError(backend_id)
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO backend_controls(id, dispatch_enabled, updated_at)
                VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET
                    dispatch_enabled = excluded.dispatch_enabled,
                    updated_at = excluded.updated_at
                """,
                (backend_id, int(enabled), time.time()),
            )
        self.notify()
