from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from config import Settings
from media import MediaValidationError, ensure_within, ingest_upload


def test_rejects_path_traversal(settings: Settings, tmp_path: Path) -> None:
    with pytest.raises(MediaValidationError, match="受控数据目录"):
        ensure_within(tmp_path / "outside.txt", settings.data_root)


def test_rejects_symlink_upload(settings: Settings, tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (2, 2)).save(source)
    link = tmp_path / "link.png"
    link.symlink_to(source)
    with pytest.raises(MediaValidationError, match="不安全"):
        ingest_upload(link, "image", "session", settings)


def test_rejects_bad_extension_and_disguised_image(
    settings: Settings, tmp_path: Path
) -> None:
    text = tmp_path / "file.txt"
    text.write_text("not an image")
    with pytest.raises(MediaValidationError, match="不支持"):
        ingest_upload(text, "image", "session", settings)

    fake = tmp_path / "fake.png"
    fake.write_text("not an image")
    with pytest.raises(MediaValidationError, match="可解码"):
        ingest_upload(fake, "image", "session", settings)


def test_ingests_valid_image(settings: Settings, tmp_path: Path) -> None:
    source = tmp_path / "valid.webp"
    Image.new("RGB", (4, 3), "red").save(source)
    uploaded = ingest_upload(source, "image", "session", settings)
    assert Path(uploaded.path).is_file()
    assert Path(uploaded.path).stat().st_mode & 0o777 == 0o600
