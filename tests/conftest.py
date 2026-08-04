from __future__ import annotations

from pathlib import Path

import pytest

from config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data_root = tmp_path / "data"
    value = Settings(
        model_root=tmp_path / "model",
        api_base="http://127.0.0.1:30011",
        web_host="127.0.0.1",
        web_port=7860,
        data_root=data_root,
        poll_seconds=0.01,
        task_timeout_seconds=30,
        physical_gpu_ids=(4, 5, 6, 7),
        request_connect_timeout=0.1,
        request_read_timeout=0.1,
        session_days=30,
        secure_cookie=False,
    )
    value.ensure_directories()
    return value
