from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import mimetypes
import secrets
import subprocess
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

import httpx
import uvicorn
from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import LIMITS, OUTPUT_SIZE_CHOICES, Settings
from database import Database
from h3_client import H3Client, build_payload
from media import (
    MAX_BYTES,
    MediaAsset,
    MediaValidationError,
    ensure_thumbnail,
    ensure_within,
    ingest_upload,
    labels_for_assets,
    media_kind_for_path,
    mentions_for_assets,
)
from pagination import PAGE_SIZE, page_window
from prompt_optimizer import (
    LLMConfig,
    render_template,
    stream_completion,
    test_connection,
    validated_config,
)
from scheduler import QueueWorker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
LOGGER = logging.getLogger(__name__)
COOKIE_NAME = "h3_session"
ACTIVE_JOB_STATUSES = {"submitting", "generating"}
PROMPT_TEMPLATE_PATH = Path(__file__).with_name("minimax_gen_prompt.txt")

settings = Settings.from_env()
settings.ensure_directories()
database = Database(settings.database_path)
database.initialize()
client = H3Client(settings)
worker = QueueWorker(settings, database, client)


class Credentials(BaseModel):
    username: str = Field(min_length=2, max_length=32)
    password: str = Field(min_length=8, max_length=256)


class UserCreate(Credentials):
    weight: int = Field(default=0, ge=0, le=100)


class UserUpdate(BaseModel):
    weight: int | None = Field(default=None, ge=0, le=100)
    password: str | None = Field(default=None, min_length=8, max_length=256)
    is_active: bool | None = None


class JobCreate(BaseModel):
    prompt: str
    asset_ids: list[str] = Field(min_length=1, max_length=LIMITS.media_max_count)
    seconds: int = Field(default=5, ge=LIMITS.seconds_min, le=LIMITS.seconds_max)
    aspect_ratio: str = "16:9"
    seed: int = Field(default=0, ge=LIMITS.seed_min, le=LIMITS.seed_max)
    num_inference_steps: int = Field(
        default=50, ge=LIMITS.steps_min, le=LIMITS.steps_max
    )
    flow_shift: float = Field(default=12, ge=0, le=30)
    audio_flow_shift: float = Field(default=3, ge=0, le=30)


class LLMConfigBody(BaseModel):
    base_url: str = Field(max_length=2048)
    model: str = Field(max_length=256)
    api_key: str | None = Field(default=None, max_length=4096)


class PromptOptimizeBody(BaseModel):
    prompt: str = Field(min_length=1, max_length=LIMITS.prompt_max_chars)


def _password_hash(password: str, salt: bytes) -> str:
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32
    )
    return base64.b64encode(digest).decode("ascii")


def _password_fields(password: str) -> tuple[str, str]:
    salt = secrets.token_bytes(16)
    return _password_hash(password, salt), base64.b64encode(salt).decode("ascii")


def _password_matches(password: str, encoded_hash: str, encoded_salt: str) -> bool:
    try:
        salt = base64.b64decode(encoded_salt)
    except (ValueError, binascii.Error):
        return False
    return hmac.compare_digest(_password_hash(password, salt), encoded_hash)


def _clean_username(username: str) -> str:
    value = username.strip()
    if len(value) < 2 or len(value) > 32 or any(
        character.isspace() or ord(character) < 32 for character in value
    ):
        raise HTTPException(status_code=400, detail="用户名格式无效")
    return value


def _session_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _create_session(user_id: str) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    now = time.time()
    with database.connect() as connection:
        connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        connection.execute(
            """
            INSERT INTO sessions(token_hash, user_id, csrf_token, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                _session_hash(token),
                user_id,
                csrf,
                now,
                now + settings.session_days * 86400,
            ),
        )
    return token, csrf


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_days * 86400,
        httponly=True,
        secure=settings.secure_cookie,
        samesite="strict",
        path="/",
    )


def _public_user(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "weight": row["weight"],
        "is_admin": bool(row["is_admin"]),
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
    }


def current_session(request: Request) -> dict[str, Any]:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="请先登录")
    now = time.time()
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT users.*, sessions.csrf_token, sessions.expires_at
            FROM sessions JOIN users ON users.id = sessions.user_id
            WHERE sessions.token_hash = ? AND sessions.expires_at > ?
              AND users.is_active = 1
            """,
            (_session_hash(token), now),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="登录已失效")
    return dict(row)


def csrf_session(
    request: Request, session: dict[str, Any] = Depends(current_session)
) -> dict[str, Any]:
    csrf = request.headers.get("X-CSRF-Token", "")
    if not csrf or not hmac.compare_digest(csrf, session["csrf_token"]):
        raise HTTPException(status_code=403, detail="请求校验失败")
    return session


def admin_session(
    session: dict[str, Any] = Depends(current_session),
) -> dict[str, Any]:
    if not session["is_admin"]:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return session


def admin_csrf_session(
    session: dict[str, Any] = Depends(csrf_session),
) -> dict[str, Any]:
    if not session["is_admin"]:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return session


def _auth_payload(user: Any, csrf: str) -> dict[str, Any]:
    return {"user": _public_user(user), "csrf_token": csrf}


def _saved_llm_config() -> LLMConfig | None:
    with database.connect() as connection:
        row = connection.execute("SELECT * FROM llm_settings WHERE id = 1").fetchone()
    if row is None:
        return None
    return LLMConfig(
        row["base_url"], row["model"], row["api_key"], settings.outbound_proxy
    )


def _effective_llm_config(body: LLMConfigBody) -> LLMConfig:
    saved = _saved_llm_config()
    api_key = body.api_key if body.api_key is not None else saved.api_key if saved else ""
    try:
        return validated_config(
            body.base_url, body.model, api_key, settings.outbound_proxy
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"


def _asset_payload(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "original_name": row["original_name"],
        "size_bytes": row["size_bytes"],
        "duration_seconds": row["duration_seconds"],
        "created_at": row["created_at"],
        "content_url": f"/api/assets/{row['id']}/content",
        "thumbnail_url": (
            f"/api/assets/{row['id']}/thumbnail-v1.jpg"
            if row["kind"] in {"image", "video"}
            else None
        ),
    }


def _row_asset(row: Any) -> MediaAsset:
    return MediaAsset(
        id=row["id"],
        kind=row["kind"],
        path=row["path"],
        original_name=row["original_name"],
        size_bytes=row["size_bytes"],
        duration_seconds=row["duration_seconds"],
    )


def _cached_file(
    request: Request,
    path: Path,
    media_type: str | None,
    cache_key: str,
    *,
    filename: str | None = None,
) -> Response:
    etag = f'"{cache_key}"'
    headers = {
        "Cache-Control": "private, max-age=31536000, immutable",
        "ETag": etag,
        "X-Content-Type-Options": "nosniff",
    }
    if etag in {
        value.strip() for value in request.headers.get("if-none-match", "").split(",")
    }:
        return Response(status_code=304, headers=headers)
    if filename is None:
        headers["Content-Disposition"] = "inline"
    return FileResponse(path, media_type=media_type, headers=headers, filename=filename)


def _job_assets(connection: Any, job_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT assets.*, job_assets.position, job_assets.mention,
               job_assets.canonical_label
        FROM job_assets JOIN assets ON assets.id = job_assets.asset_id
        WHERE job_assets.job_id = ? ORDER BY job_assets.position
        """,
        (job_id,),
    ).fetchall()
    return [
        {
            **_asset_payload(row),
            "position": row["position"],
            "mention": row["mention"],
            "canonical_label": row["canonical_label"],
        }
        for row in rows
    ]


def _estimated_progress(connection: Any, row: Any) -> tuple[float, bool]:
    stored = row["progress"]
    if stored is not None and float(stored) > 0:
        return min(100.0, float(stored)), False
    if row["status"] != "generating" or not row["started_at"]:
        return 0.0, False
    average = connection.execute(
        """
        SELECT AVG(generation_seconds) FROM jobs
        WHERE status = 'succeeded' AND seconds = ?
          AND generation_seconds IS NOT NULL AND deleted_at IS NULL
        """,
        (row["seconds"],),
    ).fetchone()[0]
    expected = float(average or (70 + max(0, row["seconds"] - 5) * 18))
    elapsed = max(0.0, time.time() - float(row["started_at"]))
    return min(95.0, elapsed / max(expected, 1) * 100), True


def _queue_ahead(connection: Any, row: Any) -> int:
    if row["status"] != "queued":
        return 0
    return int(
        connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM jobs active
                 WHERE active.status IN ('submitting', 'generating')
                   AND active.deleted_at IS NULL)
                +
                (SELECT COUNT(*)
                 FROM jobs other
                 JOIN users other_user ON other_user.id = other.user_id
                 JOIN users current_user ON current_user.id = ?
                 WHERE other.status = 'queued' AND other.deleted_at IS NULL
                   AND (
                     other_user.weight > current_user.weight OR
                     (other_user.weight = current_user.weight AND (
                         other.created_at < ? OR
                         (other.created_at = ? AND other.id < ?)
                     ))
                   ))
            """,
            (row["user_id"], row["created_at"], row["created_at"], row["id"]),
        ).fetchone()[0]
    )


def _job_payload(connection: Any, row: Any, include_user: bool = False) -> dict[str, Any]:
    progress, estimated = _estimated_progress(connection, row)
    elapsed = None
    if row["started_at"]:
        elapsed = max(
            0,
            float(row["completed_at"] or time.time()) - float(row["started_at"]),
        )
    value = {
        "id": row["id"],
        "prompt": row["prompt"],
        "status": row["status"],
        "stage": row["stage"],
        "error": row["error"],
        "progress": round(progress, 1),
        "progress_is_estimate": estimated,
        "seconds": row["seconds"],
        "aspect_ratio": row["aspect_ratio"],
        "seed": row["seed"],
        "num_inference_steps": row["num_inference_steps"],
        "flow_shift": row["flow_shift"],
        "audio_flow_shift": row["audio_flow_shift"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "generation_seconds": row["generation_seconds"],
        "elapsed_seconds": round(elapsed, 1) if elapsed is not None else None,
        "queue_ahead": _queue_ahead(connection, row),
        "assets": _job_assets(connection, row["id"]),
        "download_url": (
            f"/api/jobs/{row['id']}/download" if row["status"] == "succeeded" else None
        ),
    }
    if include_user:
        value["user"] = {
            "id": row["user_id"],
            "username": row["username"],
            "weight": row["weight"],
        }
    return value


def _share_url(connection: Any, job_id: str) -> str | None:
    row = connection.execute(
        "SELECT token FROM job_shares WHERE job_id = ?", (job_id,)
    ).fetchone()
    return f"/share/{row['token']}" if row else None


def _shared_job(connection: Any, token: str) -> Any:
    return connection.execute(
        """
        SELECT jobs.* FROM job_shares
        JOIN jobs ON jobs.id = job_shares.job_id
        WHERE job_shares.token = ? AND jobs.status = 'succeeded'
          AND jobs.deleted_at IS NULL
        """,
        (token,),
    ).fetchone()


def _public_share_payload(connection: Any, row: Any, token: str) -> dict[str, Any]:
    assets = _job_assets(connection, row["id"])
    for asset in assets:
        asset["content_url"] = f"/api/public/shares/{token}/assets/{asset['id']}"
        if asset["thumbnail_url"]:
            asset["thumbnail_url"] = (
                f"/api/public/shares/{token}/assets/{asset['id']}/thumbnail-v1.jpg"
            )
    return {
        "id": row["id"],
        "prompt": row["prompt"],
        "seconds": row["seconds"],
        "aspect_ratio": row["aspect_ratio"],
        "seed": row["seed"],
        "num_inference_steps": row["num_inference_steps"],
        "flow_shift": row["flow_shift"],
        "audio_flow_shift": row["audio_flow_shift"],
        "created_at": row["created_at"],
        "generation_seconds": row["generation_seconds"],
        "assets": assets,
        "video_url": f"/api/public/shares/{token}/video",
    }


@asynccontextmanager
async def lifespan(_: FastAPI):
    worker.start()
    yield
    worker.close()


app = FastAPI(title="MiniMax H3 Workspace", lifespan=lifespan)


@app.get("/api/bootstrap/status")
def bootstrap_status() -> dict[str, bool]:
    with database.connect() as connection:
        count = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    return {"needs_setup": count == 0}


@app.post("/api/bootstrap")
def bootstrap(body: Credentials, response: Response) -> dict[str, Any]:
    username = _clean_username(body.username)
    password_hash, salt = _password_fields(body.password)
    now = time.time()
    user_id = uuid.uuid4().hex
    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            connection.rollback()
            raise HTTPException(status_code=409, detail="管理员账号已经创建")
        connection.execute(
            """
            INSERT INTO users(
                id, username, password_hash, password_salt, weight,
                is_admin, is_active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 100, 1, 1, ?, ?)
            """,
            (user_id, username, password_hash, salt, now, now),
        )
        connection.commit()
        user = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    token, csrf = _create_session(user_id)
    _set_session_cookie(response, token)
    return _auth_payload(user, csrf)


@app.post("/api/auth/login")
def login(body: Credentials, response: Response) -> dict[str, Any]:
    username = _clean_username(body.username)
    with database.connect() as connection:
        user = connection.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE AND is_active = 1",
            (username,),
        ).fetchone()
    if user is None or not _password_matches(
        body.password, user["password_hash"], user["password_salt"]
    ):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token, csrf = _create_session(user["id"])
    _set_session_cookie(response, token)
    return _auth_payload(user, csrf)


@app.post("/api/auth/logout")
def logout(
    request: Request,
    response: Response,
    _: dict[str, Any] = Depends(csrf_session),
) -> dict[str, bool]:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        with database.connect() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE token_hash = ?", (_session_hash(token),)
            )
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@app.get("/api/auth/me")
def me(session: dict[str, Any] = Depends(current_session)) -> dict[str, Any]:
    return _auth_payload(session, session["csrf_token"])


@app.get("/api/config")
def generation_config(_: dict[str, Any] = Depends(current_session)) -> dict[str, Any]:
    return {
        "sizes": [{"label": label, "value": value} for label, value in OUTPUT_SIZE_CHOICES],
        "limits": LIMITS.__dict__,
        "defaults": {
            "seconds": 5,
            "aspect_ratio": "16:9",
            "num_inference_steps": 50,
            "flow_shift": 12,
            "audio_flow_shift": 3,
        },
    }


@app.post("/api/prompt/optimize")
async def optimize_prompt(
    body: PromptOptimizeBody, _: dict[str, Any] = Depends(csrf_session)
) -> StreamingResponse:
    config = _saved_llm_config()
    if config is None:
        raise HTTPException(status_code=409, detail="管理员尚未配置提示词优化模型")
    if not body.prompt.strip():
        raise HTTPException(status_code=400, detail="请先输入提示词")
    try:
        content = render_template(PROMPT_TEMPLATE_PATH, body.prompt)
    except (OSError, ValueError) as exc:
        LOGGER.error("无法读取提示词优化模板: %s", exc)
        raise HTTPException(status_code=500, detail="提示词优化模板不可用") from exc

    async def events():
        result: list[str] = []
        total_length = 0
        yield _sse({"type": "start"})
        try:
            async for delta in stream_completion(config, content):
                result.append(delta)
                total_length += len(delta)
                if total_length > LIMITS.prompt_max_chars:
                    raise RuntimeError("优化后的提示词超过 4000 个字符")
                yield _sse({"type": "delta", "text": delta})
            final = "".join(result).strip()
            if not final:
                raise RuntimeError("模型没有返回提示词内容")
            yield _sse({"type": "done", "text": final})
        except (RuntimeError, httpx.HTTPError) as exc:
            LOGGER.warning("提示词优化失败: %s", exc)
            yield _sse({"type": "error", "detail": str(exc)[:500]})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/assets")
def list_assets(session: dict[str, Any] = Depends(current_session)) -> list[dict[str, Any]]:
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT * FROM assets WHERE user_id = ? AND deleted_at IS NULL
            ORDER BY created_at DESC
            """,
            (session["id"],),
        ).fetchall()
    return [_asset_payload(row) for row in rows]


@app.post("/api/assets")
async def upload_assets(
    files: Annotated[list[UploadFile], File()],
    session: dict[str, Any] = Depends(csrf_session),
) -> list[dict[str, Any]]:
    if not files or len(files) > LIMITS.media_max_count:
        raise HTTPException(status_code=400, detail="单次最多上传 12 个素材")
    created: list[dict[str, Any]] = []
    for upload in files:
        safe_name = Path(upload.filename or "upload").name
        try:
            kind = media_kind_for_path(safe_name)
        except MediaValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        suffix = Path(safe_name).suffix.lower()
        temporary = ensure_within(
            settings.temp_root / f"{uuid.uuid4().hex}{suffix}", settings.temp_root
        )
        written = 0
        try:
            with temporary.open("xb") as output:
                while chunk := await upload.read(1024 * 1024):
                    written += len(chunk)
                    if written > MAX_BYTES[kind]:
                        raise MediaValidationError("文件大小超过限制")
                    output.write(chunk)
            temporary.chmod(0o600)
            asset = ingest_upload(temporary, kind, session["id"], settings)
            now = time.time()
            with database.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO assets(
                        id, user_id, kind, path, original_name, size_bytes,
                        duration_seconds, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        asset.id,
                        session["id"],
                        asset.kind,
                        asset.path,
                        safe_name,
                        asset.size_bytes,
                        asset.duration_seconds,
                        now,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM assets WHERE id = ?", (asset.id,)
                ).fetchone()
            created.append(_asset_payload(row))
        except MediaValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            temporary.unlink(missing_ok=True)
            await upload.close()
    return created


@app.get("/api/assets/{asset_id}/content")
def asset_content(
    asset_id: str,
    request: Request,
    session: dict[str, Any] = Depends(current_session),
) -> Response:
    with database.connect() as connection:
        row = connection.execute(
            "SELECT * FROM assets WHERE id = ? AND deleted_at IS NULL", (asset_id,)
        ).fetchone()
    if row is None or (row["user_id"] != session["id"] and not session["is_admin"]):
        raise HTTPException(status_code=404, detail="素材不存在")
    path = ensure_within(Path(row["path"]), settings.uploads_root)
    if path.is_symlink() or not path.is_file():
        raise HTTPException(status_code=404, detail="素材文件不存在")
    return _cached_file(
        request, path, mimetypes.guess_type(path.name)[0], f"asset-{asset_id}"
    )


@app.get("/api/assets/{asset_id}/thumbnail-v1.jpg")
def asset_thumbnail(
    asset_id: str,
    request: Request,
    session: dict[str, Any] = Depends(current_session),
) -> Response:
    with database.connect() as connection:
        row = connection.execute(
            "SELECT * FROM assets WHERE id = ? AND deleted_at IS NULL", (asset_id,)
        ).fetchone()
    if row is None or (row["user_id"] != session["id"] and not session["is_admin"]):
        raise HTTPException(status_code=404, detail="素材不存在")
    try:
        path = ensure_thumbnail(_row_asset(row), settings)
    except MediaValidationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _cached_file(request, path, "image/jpeg", f"thumbnail-v1-{asset_id}")


@app.post("/api/jobs")
def create_job(
    body: JobCreate, session: dict[str, Any] = Depends(csrf_session)
) -> dict[str, Any]:
    if len(set(body.asset_ids)) != len(body.asset_ids):
        raise HTTPException(status_code=400, detail="素材不能重复选择")
    placeholders = ",".join("?" for _ in body.asset_ids)
    with database.connect() as connection:
        rows = connection.execute(
            f"""
            SELECT * FROM assets
            WHERE id IN ({placeholders}) AND user_id = ? AND deleted_at IS NULL
            """,
            (*body.asset_ids, session["id"]),
        ).fetchall()
    by_id = {row["id"]: row for row in rows}
    if len(by_id) != len(body.asset_ids):
        raise HTTPException(status_code=400, detail="存在不可用的素材")
    assets = [
        MediaAsset(
            id=row["id"],
            kind=row["kind"],
            path=row["path"],
            original_name=row["original_name"],
            size_bytes=row["size_bytes"],
            duration_seconds=row["duration_seconds"],
        )
        for row in (by_id[asset_id] for asset_id in body.asset_ids)
    ]
    try:
        payload = build_payload(
            settings,
            assets,
            prompt=body.prompt,
            seconds=body.seconds,
            aspect_ratio=body.aspect_ratio,
            seed=body.seed,
            num_inference_steps=body.num_inference_steps,
            flow_shift=body.flow_shift,
            audio_flow_shift=body.audio_flow_shift,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    now = time.time()
    job_id = uuid.uuid4().hex
    mentions = mentions_for_assets(assets)
    labels = labels_for_assets(assets)
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO jobs(
                id, user_id, prompt, compiled_prompt, payload_json, status, stage,
                seconds, aspect_ratio, seed, num_inference_steps, flow_shift,
                audio_flow_shift, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'queued', '等待生成', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                session["id"],
                body.prompt.strip(),
                payload["prompt"],
                json.dumps(payload, ensure_ascii=False),
                body.seconds,
                body.aspect_ratio,
                body.seed,
                body.num_inference_steps,
                body.flow_shift,
                body.audio_flow_shift,
                now,
                now,
            ),
        )
        connection.executemany(
            """
            INSERT INTO job_assets(job_id, asset_id, position, mention, canonical_label)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (job_id, asset.id, index, mentions[asset.id], labels[asset.id])
                for index, asset in enumerate(assets)
            ],
        )
        row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        result = _job_payload(connection, row)
    worker.notify()
    return result


@app.get("/api/jobs")
def list_jobs(
    session: dict[str, Any] = Depends(current_session),
    page: int = Query(default=1, ge=1),
    status: str = Query(default="all"),
) -> dict[str, Any]:
    status_clauses = {
        "all": "",
        "queued": " AND status = 'queued'",
        "generating": " AND status IN ('submitting', 'generating')",
        "succeeded": " AND status = 'succeeded'",
        "failed": " AND status = 'failed'",
    }
    if status not in status_clauses:
        raise HTTPException(status_code=400, detail="任务状态筛选无效")
    where = "user_id = ? AND deleted_at IS NULL" + status_clauses[status]
    with database.connect() as connection:
        total = int(
            connection.execute(
                f"SELECT COUNT(*) FROM jobs WHERE {where}", (session["id"],)
            ).fetchone()[0]
        )
        current_page, total_pages, offset = page_window(total, page)
        rows = connection.execute(
            f"""
            SELECT * FROM jobs WHERE {where}
            ORDER BY created_at DESC LIMIT ? OFFSET ?
            """,
            (session["id"], PAGE_SIZE, offset),
        ).fetchall()
        return {
            "items": [_job_payload(connection, row) for row in rows],
            "page": current_page,
            "page_size": PAGE_SIZE,
            "total": total,
            "total_pages": total_pages,
        }


@app.get("/api/jobs/{job_id}")
def get_job(
    job_id: str, session: dict[str, Any] = Depends(current_session)
) -> dict[str, Any]:
    with database.connect() as connection:
        row = connection.execute(
            "SELECT * FROM jobs WHERE id = ? AND deleted_at IS NULL", (job_id,)
        ).fetchone()
        if row is None or (row["user_id"] != session["id"] and not session["is_admin"]):
            raise HTTPException(status_code=404, detail="任务不存在")
        if session["is_admin"]:
            row = connection.execute(
                """
                SELECT jobs.*, users.username, users.weight
                FROM jobs JOIN users ON users.id = jobs.user_id WHERE jobs.id = ?
                """,
                (job_id,),
            ).fetchone()
        value = _job_payload(connection, row, bool(session["is_admin"]))
        value["share_url"] = _share_url(connection, job_id)
        return value


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(
    job_id: str, session: dict[str, Any] = Depends(csrf_session)
) -> dict[str, Any]:
    now = time.time()
    with database.connect() as connection:
        changed = connection.execute(
            """
            UPDATE jobs SET status = 'cancelled', stage = '已取消排队',
                completed_at = ?, updated_at = ?
            WHERE id = ? AND user_id = ? AND status = 'queued' AND deleted_at IS NULL
            """,
            (now, now, job_id, session["id"]),
        ).rowcount
        if not changed:
            raise HTTPException(status_code=409, detail="只能取消尚未执行的任务")
        row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _job_payload(connection, row)


@app.get("/api/jobs/{job_id}/download")
def download_job(
    job_id: str,
    request: Request,
    session: dict[str, Any] = Depends(current_session),
) -> Response:
    with database.connect() as connection:
        row = connection.execute(
            "SELECT * FROM jobs WHERE id = ? AND deleted_at IS NULL", (job_id,)
        ).fetchone()
    if row is None or (row["user_id"] != session["id"] and not session["is_admin"]):
        raise HTTPException(status_code=404, detail="任务不存在")
    if row["status"] != "succeeded" or not row["output_path"]:
        raise HTTPException(status_code=409, detail="视频尚未生成完成")
    path = ensure_within(Path(row["output_path"]), settings.outputs_root)
    if path.is_symlink() or not path.is_file():
        raise HTTPException(status_code=404, detail="视频文件不存在")
    return _cached_file(
        request, path, "video/mp4", f"job-output-{job_id}", filename=path.name
    )


@app.post("/api/jobs/{job_id}/share")
def share_job(
    job_id: str, session: dict[str, Any] = Depends(csrf_session)
) -> dict[str, str]:
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT * FROM jobs WHERE id = ? AND user_id = ?
              AND deleted_at IS NULL
            """,
            (job_id, session["id"]),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        if row["status"] != "succeeded" or not row["output_path"]:
            raise HTTPException(status_code=409, detail="只能分享已生成的视频")
        shared = connection.execute(
            "SELECT token FROM job_shares WHERE job_id = ?", (job_id,)
        ).fetchone()
        token = shared["token"] if shared else secrets.token_urlsafe(24)
        if shared is None:
            connection.execute(
                "INSERT INTO job_shares(job_id, token, created_at) VALUES (?, ?, ?)",
                (job_id, token, time.time()),
            )
    return {"share_url": f"/share/{token}"}


@app.delete("/api/jobs/{job_id}/share")
def unshare_job(
    job_id: str, session: dict[str, Any] = Depends(csrf_session)
) -> dict[str, bool]:
    with database.connect() as connection:
        owned = connection.execute(
            "SELECT 1 FROM jobs WHERE id = ? AND user_id = ? AND deleted_at IS NULL",
            (job_id, session["id"]),
        ).fetchone()
        if owned is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        connection.execute("DELETE FROM job_shares WHERE job_id = ?", (job_id,))
    return {"ok": True}


@app.get("/api/public/shares/{token}")
def public_share(token: str) -> dict[str, Any]:
    with database.connect() as connection:
        row = _shared_job(connection, token)
        if row is None:
            raise HTTPException(status_code=404, detail="分享不存在或已取消")
        return _public_share_payload(connection, row, token)


@app.get("/api/public/shares/{token}/video")
def public_share_video(token: str, request: Request) -> Response:
    with database.connect() as connection:
        row = _shared_job(connection, token)
    if row is None or not row["output_path"]:
        raise HTTPException(status_code=404, detail="分享不存在或已取消")
    path = ensure_within(Path(row["output_path"]), settings.outputs_root)
    if path.is_symlink() or not path.is_file():
        raise HTTPException(status_code=404, detail="视频文件不存在")
    return _cached_file(request, path, "video/mp4", f"shared-video-{row['id']}")


@app.get("/api/public/shares/{token}/assets/{asset_id}")
def public_share_asset(token: str, asset_id: str, request: Request) -> Response:
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT assets.* FROM job_shares
            JOIN jobs ON jobs.id = job_shares.job_id
            JOIN job_assets ON job_assets.job_id = jobs.id
            JOIN assets ON assets.id = job_assets.asset_id
            WHERE job_shares.token = ? AND assets.id = ?
              AND jobs.status = 'succeeded' AND jobs.deleted_at IS NULL
              AND assets.deleted_at IS NULL
            """,
            (token, asset_id),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="素材不存在")
    path = ensure_within(Path(row["path"]), settings.uploads_root)
    if path.is_symlink() or not path.is_file():
        raise HTTPException(status_code=404, detail="素材文件不存在")
    return _cached_file(
        request, path, mimetypes.guess_type(path.name)[0], f"shared-asset-{asset_id}"
    )


@app.get("/api/public/shares/{token}/assets/{asset_id}/thumbnail-v1.jpg")
def public_share_thumbnail(token: str, asset_id: str, request: Request) -> Response:
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT assets.* FROM job_shares
            JOIN jobs ON jobs.id = job_shares.job_id
            JOIN job_assets ON job_assets.job_id = jobs.id
            JOIN assets ON assets.id = job_assets.asset_id
            WHERE job_shares.token = ? AND assets.id = ?
              AND jobs.status = 'succeeded' AND jobs.deleted_at IS NULL
              AND assets.deleted_at IS NULL
            """,
            (token, asset_id),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="素材不存在")
    try:
        path = ensure_thumbnail(_row_asset(row), settings)
    except MediaValidationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _cached_file(request, path, "image/jpeg", f"thumbnail-v1-{asset_id}")


@app.get("/api/admin/users")
def admin_users(_: dict[str, Any] = Depends(admin_session)) -> list[dict[str, Any]]:
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT users.*,
                (SELECT COUNT(*) FROM jobs WHERE jobs.user_id = users.id
                 AND jobs.deleted_at IS NULL) AS job_count,
                (SELECT COUNT(*) FROM assets WHERE assets.user_id = users.id
                 AND assets.deleted_at IS NULL) AS asset_count
            FROM users ORDER BY is_admin DESC, is_active DESC, created_at
            """
        ).fetchall()
    return [{**_public_user(row), "job_count": row["job_count"], "asset_count": row["asset_count"]} for row in rows]


@app.post("/api/admin/users")
def admin_create_user(
    body: UserCreate, _: dict[str, Any] = Depends(admin_csrf_session)
) -> dict[str, Any]:
    username = _clean_username(body.username)
    password_hash, salt = _password_fields(body.password)
    now = time.time()
    user_id = uuid.uuid4().hex
    try:
        with database.connect() as connection:
            connection.execute(
                """
                INSERT INTO users(
                    id, username, password_hash, password_salt, weight,
                    is_admin, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 0, 1, ?, ?)
                """,
                (user_id, username, password_hash, salt, body.weight, now, now),
            )
            row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    except Exception as exc:
        if "UNIQUE constraint failed" in str(exc):
            raise HTTPException(status_code=409, detail="用户名已经存在") from exc
        raise
    worker.notify()
    return _public_user(row)


@app.patch("/api/admin/users/{user_id}")
def admin_update_user(
    user_id: str,
    body: UserUpdate,
    admin: dict[str, Any] = Depends(admin_csrf_session),
) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    if body.weight is not None:
        changes["weight"] = body.weight
    if body.password is not None:
        changes["password_hash"], changes["password_salt"] = _password_fields(body.password)
    if body.is_active is not None:
        if user_id == admin["id"] and not body.is_active:
            raise HTTPException(status_code=400, detail="不能停用当前管理员")
        changes["is_active"] = int(body.is_active)
    if not changes:
        raise HTTPException(status_code=400, detail="没有需要更新的内容")
    changes["updated_at"] = time.time()
    columns = ", ".join(f"{name} = ?" for name in changes)
    with database.connect() as connection:
        changed = connection.execute(
            f"UPDATE users SET {columns} WHERE id = ?", [*changes.values(), user_id]
        ).rowcount
        if not changed:
            raise HTTPException(status_code=404, detail="用户不存在")
        if body.is_active is False:
            now = time.time()
            connection.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            connection.execute(
                """
                UPDATE jobs SET status = 'cancelled', stage = '用户已停用',
                    completed_at = ?, updated_at = ?
                WHERE user_id = ? AND status = 'queued'
                """,
                (now, now, user_id),
            )
        row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    worker.notify()
    return _public_user(row)


@app.delete("/api/admin/users/{user_id}")
def admin_delete_user(
    user_id: str, admin: dict[str, Any] = Depends(admin_csrf_session)
) -> dict[str, bool]:
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="不能删除当前管理员")
    now = time.time()
    with database.connect() as connection:
        changed = connection.execute(
            "UPDATE users SET is_active = 0, updated_at = ? WHERE id = ? AND is_admin = 0",
            (now, user_id),
        ).rowcount
        if not changed:
            raise HTTPException(status_code=404, detail="用户不存在")
        connection.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        connection.execute(
            """
            UPDATE jobs SET status = 'cancelled', stage = '用户已删除',
                completed_at = ?, updated_at = ?
            WHERE user_id = ? AND status = 'queued'
            """,
            (now, now, user_id),
        )
    worker.notify()
    return {"ok": True}


@app.get("/api/admin/queue")
def admin_queue(
    _: dict[str, Any] = Depends(admin_session),
    page: int = Query(default=1, ge=1),
) -> dict[str, Any]:
    with database.connect() as connection:
        total = int(
            connection.execute(
                "SELECT COUNT(*) FROM jobs WHERE deleted_at IS NULL"
            ).fetchone()[0]
        )
        current_page, total_pages, offset = page_window(total, page)
        rows = connection.execute(
            """
            SELECT jobs.*, users.username, users.weight
            FROM jobs JOIN users ON users.id = jobs.user_id
            WHERE jobs.deleted_at IS NULL
            ORDER BY
                CASE jobs.status
                    WHEN 'generating' THEN 0 WHEN 'submitting' THEN 0
                    WHEN 'queued' THEN 1 ELSE 2
                END,
                CASE WHEN jobs.status = 'queued' THEN users.weight END DESC,
                CASE WHEN jobs.status = 'queued' THEN jobs.created_at END ASC,
                jobs.created_at DESC
            LIMIT ? OFFSET ?
            """,
            (PAGE_SIZE, offset),
        ).fetchall()
        status_counts = {
            row["status"]: row["count"]
            for row in connection.execute(
                """
                SELECT status, COUNT(*) AS count FROM jobs
                WHERE deleted_at IS NULL GROUP BY status
                """
            ).fetchall()
        }
        return {
            "items": [_job_payload(connection, row, True) for row in rows],
            "page": current_page,
            "page_size": PAGE_SIZE,
            "total": total,
            "total_pages": total_pages,
            "status_counts": status_counts,
        }


@app.delete("/api/admin/jobs/{job_id}")
def admin_delete_job(
    job_id: str, _: dict[str, Any] = Depends(admin_csrf_session)
) -> dict[str, bool]:
    with database.connect() as connection:
        row = connection.execute(
            "SELECT * FROM jobs WHERE id = ? AND deleted_at IS NULL", (job_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        if row["status"] in ACTIVE_JOB_STATUSES:
            raise HTTPException(status_code=409, detail="正在执行的任务不能删除")
        now = time.time()
        connection.execute(
            "UPDATE jobs SET deleted_at = ?, updated_at = ? WHERE id = ?",
            (now, now, job_id),
        )
    if row["output_path"]:
        path = ensure_within(Path(row["output_path"]), settings.outputs_root)
        if not path.is_symlink():
            path.unlink(missing_ok=True)
    return {"ok": True}


@app.get("/api/admin/llm-config")
def admin_llm_config(_: dict[str, Any] = Depends(admin_session)) -> dict[str, Any]:
    config = _saved_llm_config()
    return {
        "base_url": config.base_url if config else "",
        "model": config.model if config else "",
        "api_key_set": bool(config and config.api_key),
    }


@app.put("/api/admin/llm-config")
def admin_save_llm_config(
    body: LLMConfigBody, _: dict[str, Any] = Depends(admin_csrf_session)
) -> dict[str, Any]:
    config = _effective_llm_config(body)
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO llm_settings(id, base_url, model, api_key, updated_at)
            VALUES (1, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                base_url = excluded.base_url,
                model = excluded.model,
                api_key = excluded.api_key,
                updated_at = excluded.updated_at
            """,
            (config.base_url, config.model, config.api_key, time.time()),
        )
    return {
        "base_url": config.base_url,
        "model": config.model,
        "api_key_set": bool(config.api_key),
    }


@app.post("/api/admin/llm-config/test")
async def admin_test_llm_config(
    body: LLMConfigBody, _: dict[str, Any] = Depends(admin_csrf_session)
) -> dict[str, Any]:
    config = _effective_llm_config(body)
    started = time.perf_counter()
    try:
        reply = await test_connection(config)
    except (RuntimeError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=502, detail=f"模型连接失败：{str(exc)[:500]}") from exc
    return {
        "ok": True,
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "reply": reply[:100],
    }


@app.get("/api/admin/system")
def admin_system(_: dict[str, Any] = Depends(admin_session)) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,power.draw,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        gpus = []
        for line in result.stdout.splitlines():
            index, name, utilization, used, total, power, temperature = (
                item.strip() for item in line.split(",")
            )
            if int(index) not in settings.physical_gpu_ids:
                continue
            gpus.append(
                {
                    "index": int(index),
                    "name": name,
                    "utilization": float(utilization),
                    "memory_used_mb": float(used),
                    "memory_total_mb": float(total),
                    "power_w": float(power),
                    "temperature_c": float(temperature),
                }
            )
    except (OSError, subprocess.SubprocessError, ValueError):
        LOGGER.exception("无法读取 GPU 状态")
        gpus = []
    health = client.health()
    with database.connect() as connection:
        counts = {
            row["status"]: row["count"]
            for row in connection.execute(
                """
                SELECT status, COUNT(*) AS count FROM jobs
                WHERE deleted_at IS NULL GROUP BY status
                """
            ).fetchall()
        }
    return {
        "sglang_online": health.online,
        "sglang_detail": health.detail,
        "gpus": gpus,
        "job_counts": counts,
    }


if settings.frontend_dist.is_dir():
    assets_dir = settings.frontend_dist / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = ensure_within(settings.frontend_dist / path, settings.frontend_dist)
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(settings.frontend_dist / "index.html")


if __name__ == "__main__":
    uvicorn.run(app, host=settings.web_host, port=settings.web_port)
