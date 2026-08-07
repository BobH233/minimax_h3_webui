from __future__ import annotations

import time

from config import Settings
from database import Database


def _insert_job(database: Database, job_id: str, user_id: str, status: str) -> None:
    now = time.time()
    with database.connect() as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO users(
                id, username, password_hash, password_salt, weight,
                is_admin, is_active, created_at, updated_at
            ) VALUES (?, ?, 'hash', 'salt', 0, 0, 1, ?, ?)
            """,
            (user_id, user_id, now, now),
        )
        connection.execute(
            """
            INSERT INTO jobs(
                id, user_id, prompt, compiled_prompt, payload_json, status,
                stage, seconds, aspect_ratio, seed, num_inference_steps,
                flow_shift, audio_flow_shift, created_at, updated_at,
                completed_at, generation_seconds
            ) VALUES (?, ?, 'p', 'p', '{}', ?, '完成',
                      5, '16:9', 0, 50, 12, 3, ?, ?, ?, 10)
            """,
            (job_id, user_id, status, now, now, now if status == "succeeded" else None),
        )


def test_completed_job_becomes_read_only_when_owner_opens_it(
    settings: Settings, monkeypatch
) -> None:
    monkeypatch.setenv("H3_DATA_ROOT", str(settings.data_root))
    import app

    database = Database(settings.database_path)
    database.initialize()
    _insert_job(database, "owner-job", "owner", "succeeded")
    _insert_job(database, "admin-job", "other", "succeeded")
    monkeypatch.setattr(app, "database", database)

    with database.connect() as connection:
        row = connection.execute(
            "SELECT * FROM jobs WHERE id = 'owner-job'"
        ).fetchone()
        assert app._job_payload(connection, row)["unread"] is True

    owner_result = app.get_job("owner-job", {"id": "owner", "is_admin": False})
    assert owner_result["unread"] is False

    admin_result = app.get_job("admin-job", {"id": "admin", "is_admin": True})
    assert admin_result["unread"] is False
    with database.connect() as connection:
        assert connection.execute(
            "SELECT viewed_at FROM jobs WHERE id = 'owner-job'"
        ).fetchone()[0] is not None
        assert connection.execute(
            "SELECT viewed_at FROM jobs WHERE id = 'admin-job'"
        ).fetchone()[0] is None
