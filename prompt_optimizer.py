from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx

PROMPT_MARKER = "################ PUT YOUR PROMPT HERE ################"
OUTPUT_START = "@new_prompt_start"
OUTPUT_END = "@new_prompt_end"
SYSTEM_PROMPT = (
    "严格遵循用户给出的 MiniMax H3 提示词规范。保留所有 @素材引用。"
    "如果用户消息附带参考图片，必须按每张图片前标注的 @图N 对应关系观察和理解图片，不得交换或重编号。"
    "在完整实现用户意图、保留必要主体定义和镜头细节的前提下尽可能精简，删除重复、空泛和无助于生成的描述，最终提示词正文不超过 4000 个字符。"
    "所有人物、动物、道具、玩具和物体都只能使用从 1 开始连续编号的 <Subject x> 标签；"
    "禁止使用 <Object x>、<Animal x>、<Prop x>、<Item x> 或任何其他实体标签。"
    "输出必须以 @new_prompt_start 单独一行开始，以 @new_prompt_end 单独一行结束；"
    "两个标记之外不要输出任何内容，不要使用 Markdown 代码块。"
)


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    model: str
    api_key: str
    outbound_proxy: str = "http://127.0.0.1:8897"

    @property
    def endpoint(self) -> str:
        base = self.base_url.rstrip("/")
        return base if base.endswith("/chat/completions") else f"{base}/chat/completions"

    @property
    def headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @property
    def proxy(self) -> str | None:
        hostname = urlsplit(self.base_url).hostname
        return None if hostname in {"127.0.0.1", "localhost", "::1"} else self.outbound_proxy


def validated_config(
    base_url: str,
    model: str,
    api_key: str,
    outbound_proxy: str = "http://127.0.0.1:8897",
) -> LLMConfig:
    base_url = base_url.strip().rstrip("/")
    model = model.strip()
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Base URL 必须是有效的 HTTP 或 HTTPS 地址")
    if parsed.username or parsed.password:
        raise ValueError("Base URL 不能包含用户名或密码")
    if not model:
        raise ValueError("请输入模型名")
    return LLMConfig(
        base_url=base_url,
        model=model,
        api_key=api_key.strip(),
        outbound_proxy=outbound_proxy,
    )


def render_template(path: Path, prompt: str) -> str:
    template = path.read_text(encoding="utf-8")
    if template.count(PROMPT_MARKER) != 1:
        raise ValueError("提示词模板缺少唯一的替换标记")
    return template.replace(PROMPT_MARKER, prompt.strip())


def extract_delta_text(payload: dict) -> str:
    try:
        content = payload["choices"][0]["delta"].get("content", "")
    except (KeyError, IndexError, TypeError):
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            item.get("text", "") for item in content if isinstance(item, dict)
        )
    return ""


class PromptMarkerParser:
    def __init__(self) -> None:
        self.buffer = ""
        self.started = False
        self.done = False
        self._trim_newline = False

    def feed(self, chunk: str) -> str:
        if self.done:
            return ""
        self.buffer += chunk
        if not self.started:
            index = self.buffer.find(OUTPUT_START)
            if index < 0:
                self.buffer = self.buffer[-(len(OUTPUT_START) - 1) :]
                return ""
            self.buffer = self.buffer[index + len(OUTPUT_START) :]
            self.started = True
            self._trim_newline = True

        if self._trim_newline:
            if self.buffer.startswith("\r\n"):
                self.buffer = self.buffer[2:]
                self._trim_newline = False
            elif self.buffer.startswith("\n"):
                self.buffer = self.buffer[1:]
                self._trim_newline = False
            elif self.buffer == "\r" or not self.buffer:
                return ""
            else:
                self._trim_newline = False

        index = self.buffer.find(OUTPUT_END)
        if index >= 0:
            value = self.buffer[:index]
            self.buffer = ""
            self.done = True
            return value
        safe_length = max(0, len(self.buffer) - len(OUTPUT_END) + 1)
        value = self.buffer[:safe_length]
        self.buffer = self.buffer[safe_length:]
        return value


def _user_content(content: str, images: list[tuple[str, str]]) -> str | list[dict]:
    if not images:
        return content
    parts: list[dict] = [
        {
            "type": "text",
            "text": (
                f"{content}\n\n"
                "下面附带当前选中的参考图片。每张图片前的文字标明它对应的 @图N；"
                "请先观察图片中的主体身份、外观、服装、道具与场景，再结合用户需求优化提示词，严格保持对应关系。"
            ),
        }
    ]
    for index, (mention, data_uri) in enumerate(images, 1):
        parts.extend(
            [
                {"type": "text", "text": f"参考图片 {index}，对应 {mention}。"},
                {"type": "image_url", "image_url": {"url": data_uri, "detail": "low"}},
            ]
        )
    return parts


def _payload(
    config: LLMConfig,
    content: str,
    *,
    stream: bool,
    images: list[tuple[str, str]] | None = None,
) -> dict:
    return {
        "model": config.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _user_content(content, images or [])},
        ],
        "stream": stream,
    }


def _upstream_error(response: httpx.Response) -> str:
    try:
        detail = response.json()
        message = detail.get("error", {}).get("message") or detail.get("detail")
        if message:
            return str(message)[:500]
    except (ValueError, TypeError, AttributeError):
        pass
    return response.text[:500] or f"HTTP {response.status_code}"


async def test_connection(config: LLMConfig) -> str:
    timeout = httpx.Timeout(30, connect=10)
    async with httpx.AsyncClient(
        timeout=timeout, proxy=config.proxy, trust_env=False
    ) as client:
        response = await client.post(
            config.endpoint,
            headers=config.headers,
            json={
                "model": config.model,
                "messages": [
                    {"role": "system", "content": "只回复 hello"},
                    {"role": "user", "content": "hello"},
                ],
                "stream": False,
            },
        )
    if response.is_error:
        raise RuntimeError(_upstream_error(response))
    try:
        return str(response.json()["choices"][0]["message"]["content"]).strip()
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("模型返回格式不是 OpenAI Chat Completions") from exc


async def stream_completion(
    config: LLMConfig, content: str, images: list[tuple[str, str]] | None = None
) -> AsyncIterator[str]:
    parser = PromptMarkerParser()
    timeout = httpx.Timeout(180, connect=10)
    async with httpx.AsyncClient(
        timeout=timeout, proxy=config.proxy, trust_env=False
    ) as client, client.stream(
        "POST",
        config.endpoint,
        headers=config.headers,
        json=_payload(config, content, stream=True, images=images),
    ) as response:
        if response.is_error:
            await response.aread()
            raise RuntimeError(_upstream_error(response))
        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                delta = extract_delta_text(json.loads(data))
            except json.JSONDecodeError:
                continue
            if delta:
                value = parser.feed(delta)
                if value:
                    yield value
                if parser.done:
                    return
    if not parser.started:
        raise RuntimeError("模型未返回 @new_prompt_start 标记")
    if not parser.done:
        raise RuntimeError("模型未返回 @new_prompt_end 标记")
