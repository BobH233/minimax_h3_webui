from __future__ import annotations

import json
import time

from config import Settings
from database import Database
from scheduler import QueueWorker


class Client:
    pass


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
