#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi

: "${H3_DATA_ROOT:=/data/minimax-h3-webui-data}"
: "${H3_CONDA_ENV:=h3-webui}"

if [[ -n "${H3_PYTHON:-}" ]]; then
  python_cmd=("$H3_PYTHON")
elif command -v conda >/dev/null 2>&1; then
  python_cmd=(conda run --no-capture-output -n "$H3_CONDA_ENV" python)
else
  echo "错误：未配置 H3_PYTHON，且未找到 conda。" >&2
  exit 1
fi
if ! "${python_cmd[@]}" -c 'import fastapi, multipart, PIL, requests, uvicorn' >/dev/null 2>&1; then
  echo "错误：WebUI Python 环境缺少依赖。" >&2
  exit 1
fi

mkdir -p "$H3_DATA_ROOT/logs"
chmod 700 "$H3_DATA_ROOT" "$H3_DATA_ROOT/logs"
exec > >(tee -a "$H3_DATA_ROOT/logs/webui.log") 2>&1

echo "启动 MiniMax-H3 Ref2VA WebUI"
exec "${python_cmd[@]}" app.py
