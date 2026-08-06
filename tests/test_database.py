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
        connection.execute(
            """
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                prompt TEXT NOT NULL,
                compiled_prompt TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL,
                stage TEXT NOT NULL,
                remote_id TEXT,
                output_path TEXT,
                error TEXT,
                progress REAL,
                seconds INTEGER NOT NULL,
                aspect_ratio TEXT NOT NULL,
                seed INTEGER NOT NULL,
                num_inference_steps INTEGER NOT NULL,
                flow_shift REAL NOT NULL,
                audio_flow_shift REAL NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                started_at REAL,
                completed_at REAL,
                generation_seconds REAL,
                deleted_at REAL
            )
            """
        )

    database = Database(settings.database_path)
    database.initialize()

    with database.connect() as connection:
        asset_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(assets)")
        }
        job_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(jobs)")
        }
    assert {"original_path", "original_size_bytes"} <= asset_columns
    assert {"original_prompt", "backend_id"} <= job_columns
    with database.connect() as connection:
        controls = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'backend_controls'"
        ).fetchone()
    assert controls is not None


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
