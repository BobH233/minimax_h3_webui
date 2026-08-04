from __future__ import annotations

from base64 import b64decode
from io import BytesIO

from PIL import Image

from config import Settings
from media import (
    LLM_IMAGE_MAX_BYTES,
    MediaAsset,
    ensure_thumbnail,
    image_llm_data_uri,
    image_preview_data_uri,
    validate_assets,
)


def item(index: int, kind: str, duration: float | None = None) -> MediaAsset:
    return MediaAsset(str(index), kind, f"/tmp/{index}", f"{index}.dat", 1, duration)  # type: ignore[arg-type]


def test_media_count_limits() -> None:
    images = [item(index, "image") for index in range(10)]
    assert "图片最多为 9 个" in validate_assets(images)
    mixed = [item(index, "image") for index in range(9)] + [
        item(20 + index, "video", 2) for index in range(3)
    ]
    mixed.append(item(30, "audio", 2))
    assert "素材总数最多为 12 个" in validate_assets(mixed)


def test_duration_boundaries_and_totals() -> None:
    valid = [item(1, "image"), item(2, "video", 2), item(3, "video", 13)]
    assert validate_assets(valid) == []
    over_total = [item(1, "image"), item(2, "audio", 8), item(3, "audio", 7.1)]
    assert any("音频总时长" in error for error in validate_assets(over_total))
    assert any(
        "视频时长必须" in error
        for error in validate_assets([item(1, "image"), item(2, "video", 1.9)])
    )
    assert any(
        "音频时长必须" in error
        for error in validate_assets([item(1, "image"), item(2, "audio", 15.1)])
    )


def test_audio_cannot_be_the_only_reference() -> None:
    errors = validate_assets([item(1, "audio", 4)])
    assert "音频不能作为唯一参考，请添加图片或视频" in errors


def test_image_preview_is_embedded_thumbnail(settings: Settings) -> None:
    path = settings.uploads_root / "preview.png"
    Image.new("RGB", (200, 100), "red").save(path)
    preview = image_preview_data_uri(
        MediaAsset("image", "image", str(path), path.name, path.stat().st_size),
        settings,
    )
    assert preview and preview.startswith("data:image/jpeg;base64,")


def test_thumbnail_is_fixed_size_and_reused(settings: Settings) -> None:
    path = settings.uploads_root / "large.png"
    Image.new("RGB", (1200, 600), "red").save(path)
    asset = MediaAsset("asset", "image", str(path), path.name, path.stat().st_size)
    thumbnail = ensure_thumbnail(asset, settings)
    with Image.open(thumbnail) as image:
        assert image.size == (480, 360)
        assert image.format == "JPEG"
    assert ensure_thumbnail(asset, settings) == thumbnail


def test_llm_image_preserves_frame_and_stays_under_limit(settings: Settings) -> None:
    path = settings.uploads_root / "llm.png"
    Image.effect_noise((2400, 1200), 100).convert("RGB").save(path)
    asset = MediaAsset("llm", "image", str(path), path.name, path.stat().st_size)

    data_uri = image_llm_data_uri(asset, settings)
    value = b64decode(data_uri.partition(",")[2])

    assert data_uri.startswith("data:image/jpeg;base64,")
    assert len(value) < LLM_IMAGE_MAX_BYTES
    with Image.open(BytesIO(value)) as image:
        assert image.size == (1280, 640)
