from pathlib import Path

import pytest

from prompt_optimizer import (
    PROMPT_MARKER,
    LLMConfig,
    PromptMarkerParser,
    _payload,
    extract_delta_text,
    render_template,
    validated_config,
)


def test_prompt_optimizer_helpers(tmp_path: Path) -> None:
    config = validated_config("https://api.example.com/v1/", "model", " key ")
    assert config.endpoint == "https://api.example.com/v1/chat/completions"
    assert config.headers["Authorization"] == "Bearer key"
    assert config.proxy == "http://127.0.0.1:8897"
    direct = LLMConfig("https://api.example.com/v1/chat/completions", "model", "")
    assert direct.endpoint.endswith("/chat/completions")
    assert LLMConfig("http://127.0.0.1:8000/v1", "model", "").proxy is None

    template = tmp_path / "prompt.txt"
    template.write_text(f"before\n{PROMPT_MARKER}\nafter", encoding="utf-8")
    assert render_template(template, "  @图1 跑起来  ") == "before\n@图1 跑起来\nafter"
    assert extract_delta_text({"choices": [{"delta": {"content": "hello"}}]}) == "hello"
    payload = _payload(
        config,
        "prompt",
        stream=True,
        images=[("@图1", "data:image/jpeg;base64,abc")],
    )
    user_content = payload["messages"][1]["content"]
    assert user_content[1]["text"] == "参考图片 1，对应 @图1。"
    assert user_content[2]["image_url"]["url"] == "data:image/jpeg;base64,abc"

    parser = PromptMarkerParser()
    chunks = ["ignored\n@new_", "prompt_start\n@图1 跑", "起来\n@new_prompt_", "end\nignored"]
    assert "".join(parser.feed(chunk) for chunk in chunks) == "@图1 跑起来\n"
    assert parser.done

    with pytest.raises(ValueError):
        validated_config("file:///tmp/model", "model", "")
