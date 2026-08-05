from __future__ import annotations

import time

from config import Settings
from database import Database


def test_existing_assets_table_gets_compression_columns(settings: Settings) -> None:
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    with Database(settings.database_path).connect() as connection:
        connection.execute(
            """
            CREATE TABLE assets (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                path TEXT NOT NULL UNIQUE,
                original_name TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                duration_seconds REAL,
                created_at REAL NOT NULL,
                deleted_at REAL
            )
            """
        )

    database = Database(settings.database_path)
    database.initialize()

    with database.connect() as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(assets)")}
    assert {"original_path", "original_size_bytes"} <= columns


def test_share_tokens_are_unique_per_job(settings: Settings) -> None:
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
            ) VALUES ('job', 'user', 'p', 'p', '{}', 'succeeded', '完成',
                      5, '16:9', 0, 50, 12, 3, ?, ?)
            """,
            (now, now),
        )
        connection.execute(
            "INSERT INTO job_shares(job_id, token, created_at) VALUES ('job', 'token', ?)",
            (now,),
        )
        row = connection.execute(
            "SELECT token FROM job_shares WHERE job_id = 'job'"
        ).fetchone()
    assert row and row["token"] == "token"
