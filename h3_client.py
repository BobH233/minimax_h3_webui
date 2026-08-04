from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from config import ASPECT_RATIOS, Settings, validate_generation_parameters
from media import MediaAsset, ensure_within, file_uri, probe_media, validate_assets


class H3APIError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        category: str,
        retryable: bool = False,
        status_code: int | None = None,
    ):
        super().__init__(message)
        self.category = category
        self.retryable = retryable
        self.status_code = status_code


@dataclass(frozen=True)
class HealthResult:
    online: bool
    detail: str
    endpoint: str | None = None


@dataclass(frozen=True)
class TaskStatus:
    status: str
    stage: str
    error: str | None
    raw: dict[str, Any]


STATUS_MAP = {
    "pending": "queued",
    "queued": "queued",
    "waiting": "queued",
    "processing": "generating",
    "running": "generating",
    "in_progress": "generating",
    "generating": "generating",
    "completed": "succeeded",
    "complete": "succeeded",
    "succeeded": "succeeded",
    "success": "succeeded",
    "failed": "failed",
    "error": "failed",
    "cancelled": "cancelled",
    "canceled": "cancelled",
}
TASK_ID_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,128}")
MENTION_RE = re.compile(r"@(?P<kind>图|视频|音频)(?P<index>[1-9]\d*)(?!\d)")
CANONICAL_RE = re.compile(
    r"<(?P<kind>Picture|Video|Audio) (?P<index>[1-9]\d*)>"
)
MENTION_KIND = {"图": "image", "视频": "video", "音频": "audio"}
CANONICAL_KIND = {"Picture": "image", "Video": "video", "Audio": "audio"}
CANONICAL_LABEL = {"image": "Picture", "video": "Video", "audio": "Audio"}


def _object(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise H3APIError("推理服务返回的数据格式无效", category="invalid_json")
    nested = data.get("data")
    return nested if isinstance(nested, dict) else data


def _first(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return None


def validate_task_id(task_id: str, *, category: str = "request") -> str:
    if not TASK_ID_PATTERN.fullmatch(task_id):
        raise H3APIError("任务 ID 格式无效", category=category)
    return task_id


def prompt_reference_errors(prompt: str, assets: list[MediaAsset]) -> list[str]:
    counts = {
        kind: sum(asset.kind == kind for asset in assets)
        for kind in ("image", "video", "audio")
    }
    errors: list[str] = []
    if "@已删除" in prompt:
        errors.append("提示词包含已删除的素材引用")
    for pattern, kind_map in (
        (MENTION_RE, MENTION_KIND),
        (CANONICAL_RE, CANONICAL_KIND),
    ):
        for match in pattern.finditer(prompt):
            kind = kind_map[match.group("kind")]
            index = int(match.group("index"))
            if index > counts[kind]:
                errors.append(f"素材引用不存在：{match.group(0)}")
    return list(dict.fromkeys(errors))


def compile_prompt_mentions(prompt: str, assets: list[MediaAsset]) -> str:
    errors = prompt_reference_errors(prompt, assets)
    if errors:
        raise ValueError("\n".join(errors))

    def replace(match: re.Match[str]) -> str:
        kind = MENTION_KIND[match.group("kind")]
        return f'<{CANONICAL_LABEL[kind]} {match.group("index")}>'

    return MENTION_RE.sub(replace, prompt).strip()


def build_payload(
    settings: Settings,
    assets: list[MediaAsset],
    *,
    prompt: str,
    seconds: int,
    aspect_ratio: str,
    seed: int,
    num_inference_steps: int,
    flow_shift: float,
    audio_flow_shift: float,
) -> dict[str, Any]:
    errors = validate_assets(assets)
    errors.extend(
        validate_generation_parameters(
            prompt,
            seconds,
            aspect_ratio,
            seed,
            num_inference_steps,
            flow_shift,
            audio_flow_shift,
        )
    )
    errors.extend(prompt_reference_errors(prompt, assets))
    if errors:
        raise ValueError("\n".join(errors))
    ordered_assets = [
        asset
        for kind in ("image", "video", "audio")
        for asset in assets
        if asset.kind == kind
    ]
    return {
        "model": "MiniMaxAI/MiniMax-H3",
        "prompt": compile_prompt_mentions(prompt, assets),
        "seconds": int(seconds),
        "task": "ref2va",
        "conditions": [
            {"type": asset.kind, "uri": file_uri(asset, settings), "role": "reference"}
            for asset in ordered_assets
        ],
        "target": {
            "short_edge": 768,
            "aspect_ratio": ASPECT_RATIOS[aspect_ratio],
            "duration_seconds": int(seconds),
        },
        "num_outputs_per_prompt": 1,
        "num_inference_steps": int(num_inference_steps),
        "flow_shift": float(flow_shift),
        "audio_flow_shift": float(audio_flow_shift),
        "seed": int(seed),
    }


class H3Client:
    def __init__(self, settings: Settings, session: requests.Session | None = None):
        self.settings = settings
        self.session = session or requests.Session()
        self.timeout = (settings.request_connect_timeout, settings.request_read_timeout)
        self._cancel_route: tuple[str, str] | None | bool = False

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        try:
            response = self.session.request(
                method,
                f"{self.settings.api_base}{path}",
                timeout=self.timeout,
                **kwargs,
            )
        except requests.ConnectTimeout as exc:
            raise H3APIError(
                "连接推理服务超时", category="timeout", retryable=True
            ) from exc
        except requests.ReadTimeout as exc:
            raise H3APIError(
                "等待推理服务响应超时", category="timeout", retryable=True
            ) from exc
        except requests.ConnectionError as exc:
            raise H3APIError(
                "无法连接推理服务", category="connection", retryable=True
            ) from exc
        except requests.RequestException as exc:
            raise H3APIError(
                "推理服务请求失败", category="request", retryable=True
            ) from exc

        if response.status_code >= 400:
            retryable = response.status_code == 429 or response.status_code >= 500
            category = (
                "server"
                if response.status_code >= 500
                else "rate_limit"
                if response.status_code == 429
                else "request"
            )
            detail = ""
            try:
                body = _object(response.json())
                detail = str(_first(body, "message", "detail", "error") or "")
            except (ValueError, H3APIError):
                pass
            message = f"推理服务返回 HTTP {response.status_code}"
            if detail:
                message += f"：{detail[:240]}"
            raise H3APIError(
                message,
                category=category,
                retryable=retryable,
                status_code=response.status_code,
            )
        return response

    @staticmethod
    def _json(response: requests.Response) -> dict[str, Any]:
        try:
            return _object(response.json())
        except (requests.JSONDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise H3APIError(
                "推理服务返回了无效 JSON", category="invalid_json"
            ) from exc

    def health(self) -> HealthResult:
        failures: list[str] = []
        for endpoint in ("/health", "/healthz", "/v1/models"):
            try:
                self._request("GET", endpoint)
                return HealthResult(True, "推理服务已连接", endpoint)
            except H3APIError as exc:
                failures.append(str(exc))
                if exc.status_code not in {404, 405, None}:
                    break
        return HealthResult(False, failures[-1] if failures else "推理服务未连接")

    def create_video(self, payload: dict[str, Any]) -> str:
        data = self._json(self._request("POST", "/v1/videos", json=payload))
        task_id = _first(data, "id", "task_id", "request_id")
        if not isinstance(task_id, (str, int)) or not str(task_id).strip():
            raise H3APIError("创建任务响应中缺少任务 ID", category="schema")
        return validate_task_id(str(task_id), category="schema")

    def get_task(self, task_id: str) -> TaskStatus:
        task_id = validate_task_id(task_id)
        data = self._json(self._request("GET", f"/v1/videos/{task_id}"))
        raw_status = str(_first(data, "status", "state", "task_status") or "").lower()
        if not raw_status:
            raise H3APIError("任务响应中缺少状态字段", category="schema")
        status = STATUS_MAP.get(raw_status, "generating")
        stage = str(_first(data, "stage", "phase", "message") or raw_status)
        error_value = _first(data, "error", "error_message", "detail")
        return TaskStatus(
            status, stage, str(error_value)[:500] if error_value else None, data
        )

    def _discover_cancel_route(self) -> tuple[str, str] | None:
        if self._cancel_route is not False:
            return self._cancel_route
        self._cancel_route = None
        try:
            data = self._json(self._request("GET", "/openapi.json"))
        except H3APIError:
            return None
        for path, methods in data.get("paths", {}).items():
            if "{id}" not in path and "{task_id}" not in path:
                continue
            lower_path = path.lower()
            if "video" not in lower_path:
                continue
            for method in ("post", "delete"):
                is_cancel_route = "cancel" in lower_path or (
                    method == "delete"
                    and lower_path.rstrip("/").endswith(("{id}", "{task_id}"))
                )
                if method in methods and is_cancel_route:
                    self._cancel_route = (method.upper(), path)
                    return self._cancel_route
        return None

    def cancel_task(self, task_id: str) -> bool:
        task_id = validate_task_id(task_id)
        route = self._discover_cancel_route()
        if not route:
            return False
        method, path = route
        path = path.replace("{id}", task_id).replace("{task_id}", task_id)
        self._request(method, path)
        return True

    def download_content(self, task_id: str, destination: Path) -> Path:
        task_id = validate_task_id(task_id)
        destination = ensure_within(destination, self.settings.outputs_root)
        response = self._request("GET", f"/v1/videos/{task_id}/content", stream=True)
        content_type = (
            response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        )
        if content_type and not (
            content_type.startswith("video/")
            or content_type == "application/octet-stream"
        ):
            raise H3APIError(f"生成内容类型无效：{content_type}", category="content")
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".part")
        written = 0
        try:
            with temporary.open("wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        output.write(chunk)
                        written += len(chunk)
            if written == 0:
                raise H3APIError("生成内容为空", category="content")
            temporary.chmod(0o600)
            probe_media(temporary, "video")
            os.replace(temporary, destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return destination
