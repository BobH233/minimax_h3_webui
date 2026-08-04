from __future__ import annotations

from config import ASPECT_RATIOS, OUTPUT_SIZE_CHOICES, validate_generation_parameters


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
