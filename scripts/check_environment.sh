#!/usr/bin/env bash
set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi

: "${H3_MODEL_ROOT:=/data/MiniMax-H3/Ref2VA}"
: "${H3_DATA_ROOT:=/data/minimax-h3-webui-data}"
: "${H3_PHYSICAL_GPU_IDS:=0,1,2,3,4,5,6,7}"
: "${H3_WEB_PORT:=7861}"
: "${H3_API_PORT:=30011}"
: "${H3_CONDA_ENV:=minimax-h3-webui}"

failures=0
pass() { printf '通过  %s\n' "$1"; }
fail() { printf '失败  %s\n' "$1" >&2; failures=$((failures + 1)); }

if ! command -v conda >/dev/null 2>&1; then
  fail "未找到 conda"
  exit 1
fi

python_code='
import os
import sys

print(f"Python {sys.version.split()[0]}")
try:
    import torch
except ImportError:
    print("ERROR PyTorch 未安装")
    raise SystemExit(2)

print(f"PyTorch {torch.__version__}")
print(f"CUDA runtime {torch.version.cuda}")
print(f"CUDA available {torch.cuda.is_available()}")
print(f"Visible GPU count {torch.cuda.device_count()}")
if not torch.cuda.is_available():
    print("ERROR torch.cuda.is_available() 为 False")
    raise SystemExit(3)
expected = len(os.environ["H3_PHYSICAL_GPU_IDS"].split(","))
if torch.cuda.device_count() != expected:
    print(f"ERROR 可见 GPU 数量应为 {expected}，当前为 {torch.cuda.device_count()}")
    raise SystemExit(4)
'
python_report="$(H3_PHYSICAL_GPU_IDS="$H3_PHYSICAL_GPU_IDS" CUDA_VISIBLE_DEVICES="$H3_PHYSICAL_GPU_IDS" conda run -n "$H3_CONDA_ENV" python -c "$python_code" 2>&1)"
python_status=$?
printf '%s\n' "$python_report"
if [[ $python_status -eq 0 ]]; then
  pass "Python、PyTorch 与 CUDA"
else
  fail "Python、PyTorch 或 CUDA 检查未通过"
fi

if command -v ffprobe >/dev/null 2>&1; then
  pass "ffprobe $(ffprobe -version 2>/dev/null | head -n 1)"
else
  fail "未找到 ffprobe，请安装 FFmpeg"
fi

if command -v nvidia-smi >/dev/null 2>&1; then
  if nvidia-smi --id="$H3_PHYSICAL_GPU_IDS" --query-gpu=index --format=csv,noheader,nounits >/dev/null 2>&1; then
    pass "nvidia-smi 可读取物理 GPU $H3_PHYSICAL_GPU_IDS"
  else
    fail "nvidia-smi 无法读取物理 GPU $H3_PHYSICAL_GPU_IDS"
  fi
else
  fail "未找到 nvidia-smi"
fi

if [[ -d "$H3_MODEL_ROOT" ]]; then
  ref2va_dir="$(find "$H3_MODEL_ROOT" -maxdepth 4 -type d -iname '*ref2va*' -print -quit 2>/dev/null)"
  if [[ -n "$ref2va_dir" ]] && find "$ref2va_dir" -maxdepth 3 -type f -size +0c \( -name '*.safetensors' -o -name '*.bin' -o -name '*.json' \) -print -quit | grep -q .; then
    pass "Ref2VA 本地权重 $ref2va_dir"
  else
    fail "在 $H3_MODEL_ROOT 中未找到含非空权重或配置文件的 Ref2VA 目录"
  fi
else
  fail "模型目录不存在：$H3_MODEL_ROOT"
fi

for port in "$H3_API_PORT" "$H3_WEB_PORT"; do
  if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    fail "端口 $port 已被占用"
  else
    pass "端口 $port 可用"
  fi
done

if [[ -d "$H3_DATA_ROOT" ]]; then
  [[ -w "$H3_DATA_ROOT" ]] && pass "数据目录可写：$H3_DATA_ROOT" || fail "数据目录不可写：$H3_DATA_ROOT"
else
  data_parent="$H3_DATA_ROOT"
  while [[ ! -e "$data_parent" && "$data_parent" != "/" ]]; do
    data_parent="$(dirname "$data_parent")"
  done
  [[ -d "$data_parent" && -w "$data_parent" ]] && pass "数据目录可在 $data_parent 下创建" || fail "数据目录无法创建：$H3_DATA_ROOT"
fi

exit "$failures"
