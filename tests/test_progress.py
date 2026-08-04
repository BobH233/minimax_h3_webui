import sqlite3

import pytest


def test_estimated_progress_uses_recent_same_duration_jobs(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("H3_DATA_ROOT", str(tmp_path / "data"))
    import app

    connection = sqlite3.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE jobs (
            status TEXT, seconds INTEGER, generation_seconds REAL,
            deleted_at REAL, completed_at REAL
        )
        """
    )
    connection.execute(
        "INSERT INTO jobs VALUES ('succeeded', 5, 1000, NULL, 1)"
    )
    connection.executemany(
        "INSERT INTO jobs VALUES ('succeeded', 5, 100, NULL, ?)",
        [(value,) for value in range(2, 12)],
    )
    monkeypatch.setattr(app.time, "time", lambda: 1000)

    progress, estimated = app._estimated_progress(
        connection,
        {"progress": None, "status": "generating", "started_at": 950, "seconds": 5},
    )

    assert progress == pytest.approx(50)
    assert estimated is True
