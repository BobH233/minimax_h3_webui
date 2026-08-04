from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class GenerationLimits:
    prompt_max_chars: int = 4000
    seconds_min: int = 4
    seconds_max: int = 15
    seed_min: int = 0
    seed_max: int = 2**32 - 1
    steps_min: int = 1
    steps_max: int = 100
    flow_shift_min: float = 0.0
    flow_shift_max: float = 30.0
    image_max_count: int = 9
    video_max_count: int = 3
    audio_max_count: int = 3
    media_max_count: int = 12
    media_duration_min: float = 2.0
    media_duration_max: float = 15.0
    video_total_seconds: float = 15.0
    audio_total_seconds: float = 15.0
    image_max_bytes: int = 25 * 1024**2
    video_max_bytes: int = 500 * 1024**2
    audio_max_bytes: int = 200 * 1024**2
    session_max_bytes: int = 2 * 1024**3


LIMITS = GenerationLimits()
ASPECT_RATIOS = {
    "自动": "auto",
    "16:9": "16:9",
    "9:16": "9:16",
    "1:1": "1:1",
    "4:3": "4:3",
    "3:4": "3:4",
    "21:9": "21:9",
}
OUTPUT_SIZE_CHOICES = [
    ("自动（1344×768）", "自动"),
    ("16:9（1344×768）", "16:9"),
    ("9:16（768×1344）", "9:16"),
    ("1:1（768×768）", "1:1"),
    ("4:3（1024×768）", "4:3"),
    ("3:4（768×1024）", "3:4"),
    ("21:9（1536×672）", "21:9"),
]


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} 必须是整数，当前值为 {raw!r}") from exc
    if value < minimum:
        raise ValueError(f"{name} 必须大于等于 {minimum}，当前值为 {value}")
    return value


def _float_env(name: str, default: float, minimum: float = 0.1) -> float:
    raw = os.getenv(name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} 必须是数字，当前值为 {raw!r}") from exc
    if value < minimum:
        raise ValueError(f"{name} 必须大于等于 {minimum}，当前值为 {value}")
    return value


@dataclass(frozen=True)
class Settings:
    model_root: Path
    api_base: str
    web_host: str
    web_port: int
    data_root: Path
    poll_seconds: float
    task_timeout_seconds: int
    physical_gpu_ids: tuple[int, ...]
    request_connect_timeout: float
    request_read_timeout: float
    session_days: int = 30
    secure_cookie: bool = False
    outbound_proxy: str = "http://127.0.0.1:8897"

    @classmethod
    def from_env(cls) -> Settings:
        api_base = os.getenv("H3_API_BASE", "http://127.0.0.1:30011").rstrip("/")
        if not api_base.startswith(("http://127.0.0.1", "http://localhost")):
            raise ValueError("H3_API_BASE 必须指向本机 127.0.0.1 或 localhost")

        gpu_raw = os.getenv("H3_PHYSICAL_GPU_IDS", "0,1,2,3,4,5,6,7")
        try:
            gpu_ids = tuple(int(item.strip()) for item in gpu_raw.split(",") if item.strip())
        except ValueError as exc:
            raise ValueError("H3_PHYSICAL_GPU_IDS 必须是逗号分隔的整数") from exc
        if not gpu_ids:
            raise ValueError("H3_PHYSICAL_GPU_IDS 不能为空")

        host = os.getenv("H3_WEB_HOST", "127.0.0.1")
        if host not in {"127.0.0.1", "localhost", "0.0.0.0"}:
            raise ValueError("H3_WEB_HOST 仅允许 127.0.0.1、localhost 或 0.0.0.0")

        data_root = Path(
            os.getenv("H3_DATA_ROOT", "/data/minimax-h3-webui-data")
        ).expanduser()
        if data_root.resolve() in {Path("/"), Path.home().resolve()}:
            raise ValueError("H3_DATA_ROOT 不能是根目录或用户主目录")

        outbound_proxy = os.getenv(
            "H3_OUTBOUND_PROXY", "http://127.0.0.1:8897"
        ).strip().rstrip("/")
        parsed_proxy = urlsplit(outbound_proxy)
        if parsed_proxy.scheme not in {"http", "https"} or not parsed_proxy.netloc:
            raise ValueError("H3_OUTBOUND_PROXY 必须是有效的 HTTP 或 HTTPS 代理地址")

        return cls(
            model_root=Path(
                os.getenv("H3_MODEL_ROOT", "/data/MiniMax-H3/Ref2VA")
            ).expanduser(),
            api_base=api_base,
            web_host=host,
            web_port=_int_env("H3_WEB_PORT", 7860),
            data_root=data_root,
            poll_seconds=_float_env("H3_POLL_SECONDS", 2.0),
            task_timeout_seconds=_int_env("H3_TASK_TIMEOUT_SECONDS", 7200),
            physical_gpu_ids=gpu_ids,
            request_connect_timeout=_float_env("H3_CONNECT_TIMEOUT_SECONDS", 3.0),
            request_read_timeout=_float_env("H3_READ_TIMEOUT_SECONDS", 30.0),
            session_days=_int_env("H3_SESSION_DAYS", 30),
            secure_cookie=os.getenv("H3_SECURE_COOKIE", "0") == "1",
            outbound_proxy=outbound_proxy,
        )

    @property
    def uploads_root(self) -> Path:
        return self.data_root / "assets"

    @property
    def outputs_root(self) -> Path:
        return self.data_root / "outputs"

    @property
    def temp_root(self) -> Path:
        return self.data_root / "tmp"

    @property
    def thumbnails_root(self) -> Path:
        return self.data_root / "thumbnails"

    @property
    def database_path(self) -> Path:
        return self.data_root / "h3-webui.sqlite3"

    @property
    def frontend_dist(self) -> Path:
        return Path(__file__).resolve().parent / "frontend" / "dist"

    def ensure_directories(self) -> None:
        for path in (
            self.data_root,
            self.uploads_root,
            self.outputs_root,
            self.temp_root,
            self.thumbnails_root,
        ):
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.chmod(0o700)


def validate_generation_parameters(
    prompt: str,
    seconds: int,
    aspect_ratio: str,
    seed: int,
    num_inference_steps: int,
    flow_shift: float,
    audio_flow_shift: float,
) -> list[str]:
    errors: list[str] = []

    def integer_value(label: str, value: int, minimum: int, maximum: int) -> None:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            errors.append(f"{label}必须是整数")
            return
        if not numeric.is_integer() or not minimum <= numeric <= maximum:
            errors.append(f"{label}必须为 {minimum}-{maximum} 的整数")

    stripped = prompt.strip()
    if not stripped:
        errors.append("请输入提示词")
    elif len(stripped) > LIMITS.prompt_max_chars:
        errors.append(
            f"提示词为 {len(stripped)} 个字符，最多允许 {LIMITS.prompt_max_chars} 个"
        )
    integer_value("生成时长", seconds, LIMITS.seconds_min, LIMITS.seconds_max)
    if aspect_ratio not in ASPECT_RATIOS:
        errors.append("画面比例无效")
    integer_value("Seed", seed, LIMITS.seed_min, LIMITS.seed_max)
    integer_value("推理步数", num_inference_steps, LIMITS.steps_min, LIMITS.steps_max)
    for label, value in (
        ("视频 flow shift", flow_shift),
        ("音频 flow shift", audio_flow_shift),
    ):
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            errors.append(f"{label}必须是数字")
            continue
        if not LIMITS.flow_shift_min <= numeric <= LIMITS.flow_shift_max:
            errors.append(
                f"{label} 必须为 {LIMITS.flow_shift_min:g}-{LIMITS.flow_shift_max:g}"
            )
    return errors
