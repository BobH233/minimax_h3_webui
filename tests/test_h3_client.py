from __future__ import annotations

import json

import pytest
import requests

from config import Settings
from h3_client import H3APIError, H3Client


def response(
    status: int, data: object | None = None, body: bytes | None = None
) -> requests.Response:
    value = requests.Response()
    value.status_code = status
    value._content = body if body is not None else json.dumps(data).encode()
    value.headers["Content-Type"] = "application/json"
    return value


class Session:
    def __init__(self, result: requests.Response | Exception):
        self.result = result

    def request(self, *args, **kwargs):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class SequenceSession:
    def __init__(self, results):
        self.results = iter(results)
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append((method, url))
        return next(self.results)


def test_create_task_accepts_common_id_field(settings: Settings) -> None:
    client = H3Client(settings, Session(response(200, {"data": {"task_id": "task-1"}})))  # type: ignore[arg-type]
    assert client.create_video({}) == "task-1"


def test_create_task_rejects_unsafe_id(settings: Settings) -> None:
    client = H3Client(settings, Session(response(200, {"id": "../../etc"})))  # type: ignore[arg-type]
    with pytest.raises(H3APIError, match="任务 ID 格式无效"):
        client.create_video({})


@pytest.mark.parametrize(
    ("status", "retryable"),
    [(400, False), (429, True), (503, True)],
)
def test_http_error_classification(
    settings: Settings, status: int, retryable: bool
) -> None:
    client = H3Client(settings, Session(response(status, {"detail": "bad"})))  # type: ignore[arg-type]
    with pytest.raises(H3APIError) as caught:
        client.create_video({})
    assert caught.value.retryable is retryable
    assert caught.value.status_code == status


def test_timeout_is_retryable(settings: Settings) -> None:
    client = H3Client(settings, Session(requests.ReadTimeout()))  # type: ignore[arg-type]
    with pytest.raises(H3APIError) as caught:
        client.get_task("task")
    assert caught.value.category == "timeout"
    assert caught.value.retryable


def test_invalid_json_is_reported(settings: Settings) -> None:
    client = H3Client(settings, Session(response(200, body=b"not json")))  # type: ignore[arg-type]
    with pytest.raises(H3APIError, match="无效 JSON"):
        client.get_task("task")


def test_status_normalization(settings: Settings) -> None:
    client = H3Client(
        settings, Session(response(200, {"state": "processing", "phase": "diffusion"}))
    )  # type: ignore[arg-type]
    result = client.get_task("task")
    assert result.status == "generating"
    assert result.stage == "diffusion"


def test_discovers_delete_cancel_endpoint(settings: Settings) -> None:
    session = SequenceSession(
        [
            response(200, {"paths": {"/v1/videos/{id}": {"get": {}, "delete": {}}}}),
            response(204, {}),
        ]
    )
    client = H3Client(settings, session)  # type: ignore[arg-type]
    assert client.cancel_task("task-1")
    assert session.requests[-1] == ("DELETE", "http://127.0.0.1:30011/v1/videos/task-1")
