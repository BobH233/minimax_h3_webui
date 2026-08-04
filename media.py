from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from base64 import b64encode
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path
from typing import Literal

from PIL import Image, ImageOps, UnidentifiedImageError

from config import LIMITS, Settings

MediaKind = Literal["image", "video", "audio"]
ALLOWED_EXTENSIONS: dict[MediaKind, set[str]] = {
    "image": {".jpg", ".jpeg", ".png", ".webp"},
    "video": {".mp4", ".mov", ".webm"},
    "audio": {".mp3", ".wav", ".m4a", ".flac", ".ogg"},
}
MAX_BYTES = {
    "image": LIMITS.image_max_bytes,
    "video": LIMITS.video_max_bytes,
    "audio": LIMITS.audio_max_bytes,
}
MAX_COUNTS = {
    "image": LIMITS.image_max_count,
    "video": LIMITS.video_max_count,
    "audio": LIMITS.audio_max_count,
}
LABELS = {"image": "Picture", "video": "Video", "audio": "Audio"}
MENTION_LABELS = {"image": "图", "video": "视频", "audio": "音频"}
THUMBNAIL_SIZE = (480, 360)
LLM_IMAGE_MAX_BYTES = 500 * 1024


class MediaValidationError(ValueError):
    pass


@dataclass(frozen=True)
class MediaAsset:
    id: str
    kind: MediaKind
    path: str
    original_name: str
    size_bytes: int
    duration_seconds: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict) -> MediaAsset:
        return cls(**value)


def ensure_within(path: Path, root: Path) -> Path:
    resolved_root = root.resolve()
    resolved = path.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise MediaValidationError("路径不在受控数据目录内")
    return resolved


def image_preview_data_uri(asset: MediaAsset, settings: Settings) -> str | None:
    if asset.kind != "image":
        return None
    path = ensure_within(Path(asset.path), settings.uploads_root)
    if path.is_symlink() or not path.is_file():
        return None
    try:
        with Image.open(path) as source:
            image = ImageOps.fit(
                ImageOps.exif_transpose(source).convert("RGB"),
                (64, 64),
                method=Image.Resampling.LANCZOS,
            )
            output = BytesIO()
            image.save(output, format="JPEG", quality=72, optimize=True)
    except (UnidentifiedImageError, OSError):
        return None
    return f"data:image/jpeg;base64,{b64encode(output.getvalue()).decode()}"


def image_llm_data_uri(asset: MediaAsset, settings: Settings) -> str:
    if asset.kind != "image":
        raise MediaValidationError("该素材不是图片")
    path = ensure_within(Path(asset.path), settings.uploads_root)
    if path.is_symlink() or not path.is_file():
        raise MediaValidationError("素材文件不存在或不安全")
    try:
        with Image.open(path) as original:
            base = ImageOps.exif_transpose(original)
            base.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
            base = base.convert("RGB")
            for size in (1280, 1024, 768, 512, 384):
                image = base.copy()
                image.thumbnail((size, size), Image.Resampling.LANCZOS)
                for quality in (78, 65, 52, 40, 30):
                    output = BytesIO()
                    image.save(output, format="JPEG", quality=quality, optimize=True)
                    value = output.getvalue()
                    if len(value) < LLM_IMAGE_MAX_BYTES:
                        return f"data:image/jpeg;base64,{b64encode(value).decode()}"
    except (UnidentifiedImageError, OSError) as exc:
        raise MediaValidationError("无法压缩参考图片") from exc
    raise MediaValidationError("参考图片压缩后仍然过大")


def file_uri(asset: MediaAsset, settings: Settings) -> str:
    path = ensure_within(Path(asset.path), settings.data_root)
    if path.is_symlink() or not path.is_file():
        raise MediaValidationError("素材文件不存在或不安全")
    return path.as_uri()


def ensure_thumbnail(asset: MediaAsset, settings: Settings) -> Path:
    if asset.kind not in {"image", "video"}:
        raise MediaValidationError("该素材没有缩略图")
    source = ensure_within(Path(asset.path), settings.uploads_root)
    if source.is_symlink() or not source.is_file():
        raise MediaValidationError("素材文件不存在或不安全")
    destination = ensure_within(
        settings.thumbnails_root / f"{asset.id}.jpg", settings.thumbnails_root
    )
    if destination.is_file() and not destination.is_symlink():
        return destination
    temporary = ensure_within(
        settings.thumbnails_root / f".{asset.id}.{uuid.uuid4().hex}.jpg",
        settings.thumbnails_root,
    )
    try:
        if asset.kind == "image":
            with Image.open(source) as original:
                image = ImageOps.fit(
                    ImageOps.exif_transpose(original).convert("RGB"),
                    THUMBNAIL_SIZE,
                    method=Image.Resampling.LANCZOS,
                )
                image.save(temporary, format="JPEG", quality=78, optimize=True)
        else:
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-ss",
                    "0.5",
                    "-i",
                    str(source),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=480:360:force_original_aspect_ratio=increase,crop=480:360",
                    "-q:v",
                    "4",
                    "-y",
                    str(temporary),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0 or not temporary.is_file():
                raise MediaValidationError("无法生成视频缩略图")
        temporary.chmod(0o600)
        os.replace(temporary, destination)
    except (UnidentifiedImageError, OSError, subprocess.TimeoutExpired) as exc:
        raise MediaValidationError("无法生成素材缩略图") from exc
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def probe_media(
    path: Path, expected_kind: Literal["video", "audio"] | None = None
) -> dict:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration,format_name:stream=codec_type,duration",
                "-of",
                "json",
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError as exc:
        raise MediaValidationError("未找到 ffprobe，请先安装 FFmpeg") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaValidationError("ffprobe 检查超时") from exc
    if result.returncode != 0:
        raise MediaValidationError("文件不是可读取的音视频媒体")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MediaValidationError("ffprobe 返回了无效结果") from exc

    stream_types = {stream.get("codec_type") for stream in data.get("streams", [])}
    required_type = (
        "video"
        if expected_kind == "video"
        else "audio"
        if expected_kind == "audio"
        else None
    )
    if required_type and required_type not in stream_types:
        raise MediaValidationError(
            f"文件不包含有效的{'视频' if required_type == 'video' else '音频'}流"
        )

    raw_durations = [data.get("format", {}).get("duration")]
    raw_durations.extend(stream.get("duration") for stream in data.get("streams", []))
    durations: list[float] = []
    for value in raw_durations:
        try:
            durations.append(float(value))
        except (TypeError, ValueError):
            continue
    if not durations or max(durations) <= 0:
        raise MediaValidationError("无法读取媒体时长")
    data["duration_seconds"] = max(durations)
    return data


def _validate_file(path: Path, kind: MediaKind) -> float | None:
    if kind == "image":
        try:
            with Image.open(path) as image:
                image.verify()
        except (UnidentifiedImageError, OSError) as exc:
            raise MediaValidationError("文件不是可解码的图片") from exc
        return None

    duration = probe_media(path, kind)["duration_seconds"]
    if not LIMITS.media_duration_min <= duration <= LIMITS.media_duration_max:
        raise MediaValidationError(
            f"{'视频' if kind == 'video' else '音频'}时长必须为 "
            f"{LIMITS.media_duration_min:g}-{LIMITS.media_duration_max:g} 秒，当前为 {duration:.1f} 秒"
        )
    return duration


def ingest_upload(
    source: str | Path, kind: MediaKind, session_id: str, settings: Settings
) -> MediaAsset:
    source_path = Path(source)
    if source_path.is_symlink() or not source_path.is_file():
        raise MediaValidationError("上传文件不存在或不安全")
    extension = source_path.suffix.lower()
    if extension not in ALLOWED_EXTENSIONS[kind]:
        allowed = "、".join(sorted(ALLOWED_EXTENSIONS[kind]))
        raise MediaValidationError(
            f"不支持 {extension or '无扩展名'} 文件，允许：{allowed}"
        )
    size = source_path.stat().st_size
    if size <= 0 or size > MAX_BYTES[kind]:
        raise MediaValidationError(
            f"文件大小必须大于 0 且不超过 {MAX_BYTES[kind] // 1024**2} MiB"
        )

    session_dir = ensure_within(
        settings.uploads_root / session_id, settings.uploads_root
    )
    session_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination = ensure_within(
        session_dir / f"{uuid.uuid4().hex}{extension}", settings.uploads_root
    )
    try:
        with (
            source_path.open("rb") as source_file,
            destination.open("xb") as destination_file,
        ):
            shutil.copyfileobj(source_file, destination_file, length=1024 * 1024)
        destination.chmod(0o600)
        duration = _validate_file(destination, kind)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return MediaAsset(
        id=uuid.uuid4().hex,
        kind=kind,
        path=str(destination),
        original_name=source_path.name,
        size_bytes=size,
        duration_seconds=duration,
    )


def labels_for_assets(assets: Iterable[MediaAsset]) -> dict[str, str]:
    counters: dict[str, int] = {kind: 0 for kind in ALLOWED_EXTENSIONS}
    labels: dict[str, str] = {}
    for asset in assets:
        counters[asset.kind] += 1
        labels[asset.id] = f"<{LABELS[asset.kind]} {counters[asset.kind]}>"
    return labels


def mentions_for_assets(assets: Iterable[MediaAsset]) -> dict[str, str]:
    counters: dict[str, int] = {kind: 0 for kind in ALLOWED_EXTENSIONS}
    mentions: dict[str, str] = {}
    for asset in assets:
        counters[asset.kind] += 1
        mentions[asset.id] = f"@{MENTION_LABELS[asset.kind]}{counters[asset.kind]}"
    return mentions


def media_kind_for_path(path: str | Path) -> MediaKind:
    extension = Path(path).suffix.lower()
    for kind, extensions in ALLOWED_EXTENSIONS.items():
        if extension in extensions:
            return kind
    raise MediaValidationError(f"不支持 {extension or '无扩展名'} 文件")


def validate_assets(assets: list[MediaAsset]) -> list[str]:
    errors: list[str] = []
    if len(assets) > LIMITS.media_max_count:
        errors.append(f"素材总数最多为 {LIMITS.media_max_count} 个")
    session_bytes = sum(asset.size_bytes for asset in assets)
    if session_bytes > LIMITS.session_max_bytes:
        errors.append(
            f"单个会话素材总大小不能超过 {LIMITS.session_max_bytes // 1024**3} GiB"
        )

    for kind, maximum in MAX_COUNTS.items():
        kind_assets = [asset for asset in assets if asset.kind == kind]
        if len(kind_assets) > maximum:
            kind_name = {"image": "图片", "video": "视频", "audio": "音频"}[kind]
            errors.append(f"{kind_name}最多为 {maximum} 个")
        if kind in {"video", "audio"}:
            for asset in kind_assets:
                duration = asset.duration_seconds
                if (
                    duration is None
                    or not LIMITS.media_duration_min
                    <= duration
                    <= LIMITS.media_duration_max
                ):
                    kind_name = "视频" if kind == "video" else "音频"
                    errors.append(
                        f"{kind_name}时长必须为 {LIMITS.media_duration_min:g}-{LIMITS.media_duration_max:g} 秒"
                    )
            total = sum(asset.duration_seconds or 0 for asset in kind_assets)
            maximum_duration = (
                LIMITS.video_total_seconds
                if kind == "video"
                else LIMITS.audio_total_seconds
            )
            if total > maximum_duration + 1e-6:
                kind_name = "视频" if kind == "video" else "音频"
                errors.append(
                    f"{kind_name}总时长不能超过 {maximum_duration:g} 秒，当前为 {total:.1f} 秒"
                )
    if assets and not any(asset.kind in {"image", "video"} for asset in assets):
        errors.append("音频不能作为唯一参考，请添加图片或视频")
    if not any(asset.kind in {"image", "video"} for asset in assets):
        errors.append("请至少添加一张图片或一段视频")
    return list(dict.fromkeys(errors))


def remove_asset_file(asset: MediaAsset, settings: Settings) -> None:
    path = ensure_within(Path(asset.path), settings.uploads_root)
    if path.is_symlink():
        raise MediaValidationError("拒绝删除符号链接")
    path.unlink(missing_ok=True)
