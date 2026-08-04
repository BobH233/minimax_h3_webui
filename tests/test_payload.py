from __future__ import annotations

import pytest

from config import Settings
from h3_client import build_payload, compile_prompt_mentions
from media import MediaAsset, labels_for_assets, mentions_for_assets


def asset(
    settings: Settings, kind: str, name: str, duration: float | None = None
) -> MediaAsset:
    path = settings.uploads_root / "session" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fixture")
    return MediaAsset(name, kind, str(path), name, 7, duration)  # type: ignore[arg-type]


def test_labels_and_payload_preserve_per_type_order(settings: Settings) -> None:
    assets = [
        asset(settings, "audio", "sound.wav", 4),
        asset(settings, "image", "first.png"),
        asset(settings, "video", "clip.mp4", 4),
        asset(settings, "image", "second.png"),
    ]

    assert list(labels_for_assets(assets).values()) == [
        "<Audio 1>",
        "<Picture 1>",
        "<Video 1>",
        "<Picture 2>",
    ]
    assert list(mentions_for_assets(assets).values()) == [
        "@音频1",
        "@图1",
        "@视频1",
        "@图2",
    ]

    payload = build_payload(
        settings,
        assets,
        prompt="让 @图1 的人物参考 @音频1，并看向 @图2。",
        seconds=5,
        aspect_ratio="16:9",
        seed=3101,
        num_inference_steps=50,
        flow_shift=12,
        audio_flow_shift=3,
    )

    assert [condition["type"] for condition in payload["conditions"]] == [
        "image",
        "image",
        "video",
        "audio",
    ]
    assert payload["conditions"][0]["uri"].endswith("first.png")
    assert payload["prompt"] == (
        "让 <Picture 1> 的人物参考 <Audio 1>，并看向 <Picture 2>。"
    )
    assert payload["seconds"] == payload["target"]["duration_seconds"] == 5
    assert payload["target"] == {
        "short_edge": 768,
        "aspect_ratio": "16:9",
        "duration_seconds": 5,
    }
    assert payload["seed"] == 3101


def test_prompt_mentions_reject_missing_assets(settings: Settings) -> None:
    assets = [asset(settings, "image", "image.png")]
    with pytest.raises(ValueError, match="素材引用不存在：@图2"):
        compile_prompt_mentions("@图2 向前走", assets)
def test_auto_aspect_ratio_mapping(settings: Settings) -> None:
    payload = build_payload(
        settings,
        [asset(settings, "image", "image.png")],
        prompt="测试",
        seconds=4,
        aspect_ratio="自动",
        seed=0,
        num_inference_steps=1,
        flow_shift=0,
        audio_flow_shift=30,
    )
    assert payload["target"]["aspect_ratio"] == "auto"
