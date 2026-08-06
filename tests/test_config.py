from __future__ import annotations

from config import ASPECT_RATIOS, OUTPUT_SIZE_CHOICES, Settings, validate_generation_parameters


def test_output_size_choices_keep_supported_aspect_values() -> None:
    assert {value for _, value in OUTPUT_SIZE_CHOICES} == set(ASPECT_RATIOS)


def test_integer_generation_parameters_reject_fractions() -> None:
    errors = validate_generation_parameters(
        "prompt",
        4.5,  # type: ignore[arg-type]
        "自动",
        3.2,  # type: ignore[arg-type]
        50.1,  # type: ignore[arg-type]
        12,
        3,
    )
    assert "生成时长必须为 4-15 的整数" in errors
    assert "Seed必须为 0-4294967295 的整数" in errors
    assert "推理步数必须为 1-100 的整数" in errors


def test_secondary_backend_configuration(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("H3_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("H3_PHYSICAL_GPU_IDS", "0,1,2,3,4,5,6,7")
    monkeypatch.setenv("H3_PRIMARY_GPU_IDS", "4,5,6,7")
    monkeypatch.setenv("H3_SECONDARY_API_BASE", "http://127.0.0.1:30111")
    monkeypatch.setenv("H3_SECONDARY_GPU_IDS", "0,1,2,3")

    settings = Settings.from_env()

    assert [backend.id for backend in settings.backends] == ["primary", "secondary"]
    assert settings.backends[0].name == "GPU 4–7"
    assert settings.backends[1].api_base.endswith(":30111")
