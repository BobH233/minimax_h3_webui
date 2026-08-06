from __future__ import annotations

import json
import time

from config import Settings
from database import Database
from scheduler import QueueWorker, generation_progress


class Client:
    pass


def test_patched_sglang_progress_uses_real_steps() -> None:
    progress, stage = generation_progress(
        {
            "progress": 51,
            "current_step": 25,
            "total_steps": 49,
            "generation_stage": "denoising",
        }
    )
    assert progress == 51
    assert stage == "正在去噪 · 25/49 步"


def test_unpatched_sglang_progress_falls_back_cleanly() -> None:
    progress, stage = generation_progress({"progress": 0})
    assert progress == 0
    assert stage == "正在生成"


def test_patched_sglang_reports_postprocessing() -> None:
    progress, stage = generation_progress(
        {
            "progress": 95,
            "current_step": 49,
            "total_steps": 49,
            "generation_stage": "postprocessing",
        }
    )
    assert progress == 95
    assert stage == "正在解码与保存"


def test_worker_claims_current_highest_weight(settings: Settings) -> None:
    database = Database(settings.database_path)
    database.initialize()
    now = time.time()
    with database.connect() as connection:
        for user_id, weight in (("low", 2), ("high", 10)):
            connection.execute(
                """
                INSERT INTO users(
                    id, username, password_hash, password_salt, weight,
                    is_admin, is_active, created_at, updated_at
                ) VALUES (?, ?, 'hash', 'salt', ?, 0, 1, ?, ?)
                """,
                (user_id, user_id, weight, now, now),
            )
        for index, user_id in enumerate(("low", "low", "high")):
            connection.execute(
                """
                INSERT INTO jobs(
                    id, user_id, prompt, compiled_prompt, payload_json, status,
                    stage, seconds, aspect_ratio, seed, num_inference_steps,
                    flow_shift, audio_flow_shift, created_at, updated_at
                ) VALUES (?, ?, 'p', 'p', ?, 'queued', '等待生成',
                          5, '16:9', 0, 50, 12, 3, ?, ?)
                """,
                (f"job-{index}", user_id, json.dumps({}), now + index, now + index),
            )

    worker = QueueWorker(settings, database, Client())  # type: ignore[arg-type]
    claimed = worker._claim_next()
    assert claimed and claimed["id"] == "job-2"


def test_weight_change_reorders_unstarted_jobs(settings: Settings) -> None:
    database = Database(settings.database_path)
    database.initialize()
    now = time.time()
    with database.connect() as connection:
        for user_id, weight in (("first", 5), ("second", 1)):
            connection.execute(
                """
                INSERT INTO users(
                    id, username, password_hash, password_salt, weight,
                    is_admin, is_active, created_at, updated_at
                ) VALUES (?, ?, 'hash', 'salt', ?, 0, 1, ?, ?)
                """,
                (user_id, user_id, weight, now, now),
            )
            connection.execute(
                """
                INSERT INTO jobs(
                    id, user_id, prompt, compiled_prompt, payload_json, status,
                    stage, seconds, aspect_ratio, seed, num_inference_steps,
                    flow_shift, audio_flow_shift, created_at, updated_at
                ) VALUES (?, ?, 'p', 'p', '{}', 'queued', '等待生成',
                          5, '16:9', 0, 50, 12, 3, ?, ?)
                """,
                (f"job-{user_id}", user_id, now, now),
            )
        connection.execute("UPDATE users SET weight = 9 WHERE id = 'second'")

    worker = QueueWorker(settings, database, Client())  # type: ignore[arg-type]
    claimed = worker._claim_next()
    assert claimed and claimed["id"] == "job-second"


def test_two_backends_claim_different_jobs(settings: Settings) -> None:
    database = Database(settings.database_path)
    database.initialize()
    now = time.time()
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO users(
                id, username, password_hash, password_salt, weight,
                is_admin, is_active, created_at, updated_at
            ) VALUES ('user', 'user', 'hash', 'salt', 0, 0, 1, ?, ?)
            """,
            (now, now),
        )
        for index in range(2):
            connection.execute(
                """
                INSERT INTO jobs(
                    id, user_id, prompt, compiled_prompt, payload_json, status,
                    stage, seconds, aspect_ratio, seed, num_inference_steps,
                    flow_shift, audio_flow_shift, created_at, updated_at
                ) VALUES (?, 'user', 'p', 'p', '{}', 'queued', '等待生成',
                          5, '16:9', 0, 50, 12, 3, ?, ?)
                """,
                (f"job-{index}", now + index, now + index),
            )

    primary = QueueWorker(
        settings, database, Client(), "primary"  # type: ignore[arg-type]
    )
    secondary = QueueWorker(
        settings, database, Client(), "secondary"  # type: ignore[arg-type]
    )
    first = primary._claim_next()
    second = secondary._claim_next()

    assert first and second and first["id"] != second["id"]
    assert first["backend_id"] == "primary"
    assert second["backend_id"] == "secondary"


def test_disabled_backend_does_not_claim_new_job(settings: Settings) -> None:
    database = Database(settings.database_path)
    database.initialize()
    now = time.time()
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO users(
                id, username, password_hash, password_salt, weight,
                is_admin, is_active, created_at, updated_at
            ) VALUES ('user', 'user', 'hash', 'salt', 0, 0, 1, ?, ?)
            """,
            (now, now),
        )
        connection.execute(
            """
            INSERT INTO jobs(
                id, user_id, prompt, compiled_prompt, payload_json, status,
                stage, seconds, aspect_ratio, seed, num_inference_steps,
                flow_shift, audio_flow_shift, created_at, updated_at
            ) VALUES ('job', 'user', 'p', 'p', '{}', 'queued', '等待生成',
                      5, '16:9', 0, 50, 12, 3, ?, ?)
            """,
            (now, now),
        )
        connection.execute(
            """
            INSERT INTO backend_controls(id, dispatch_enabled, updated_at)
            VALUES ('secondary', 0, ?)
            """,
            (now,),
        )

    worker = QueueWorker(
        settings, database, Client(), "secondary"  # type: ignore[arg-type]
    )
    assert worker._claim_next() is None
