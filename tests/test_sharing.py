from __future__ import annotations

import time

import pytest
from fastapi import HTTPException

from config import Settings
from database import Database


def test_admin_can_manage_another_users_share(
    settings: Settings, monkeypatch
) -> None:
    monkeypatch.setenv("H3_DATA_ROOT", str(settings.data_root))
    import app

    database = Database(settings.database_path)
    database.initialize()
    now = time.time()
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO users(
                id, username, password_hash, password_salt, weight,
                is_admin, is_active, created_at, updated_at
            ) VALUES ('owner', 'owner', 'hash', 'salt', 0, 0, 1, ?, ?)
            """,
            (now, now),
        )
        connection.execute(
            """
            INSERT INTO jobs(
                id, user_id, prompt, compiled_prompt, payload_json, status,
                stage, output_path, seconds, aspect_ratio, seed,
                num_inference_steps, flow_shift, audio_flow_shift,
                created_at, updated_at
            ) VALUES (
                'job', 'owner', 'p', 'p', '{}', 'succeeded', '完成',
                '/tmp/video.mp4', 5, '16:9', 0, 50, 12, 3, ?, ?
            )
            """,
            (now, now),
        )
    monkeypatch.setattr(app, "database", database)

    regular = {"id": "other", "is_admin": False}
    with pytest.raises(HTTPException) as denied:
        app.share_job("job", regular)
    assert denied.value.status_code == 404

    admin = {"id": "admin", "is_admin": True}
    result = app.share_job("job", admin)
    assert result["share_url"].startswith("/share/")
    assert app.unshare_job("job", admin) == {"ok": True}
