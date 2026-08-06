#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi

: "${H3_RUNTIME_ROOT:=/data/h3-runtime}"
: "${H3_WEB_PORT:=7861}"
: "${H3_START_SECONDARY:=0}"
: "${H3_SECONDARY_API_PORT:=30012}"
mkdir -p "$H3_RUNTIME_ROOT"

if curl -fsS --max-time 2 http://127.0.0.1:30011/health >/dev/null; then
  echo "SGLang 已运行"
elif pgrep -f 'sglang serve .*MiniMax-H3/Ref2VA.*--port 30011' >/dev/null; then
  echo "SGLang 正在启动"
else
  nohup bash scripts/start_sglang.sh </dev/null >>"$H3_RUNTIME_ROOT/sglang.log" 2>&1 &
  echo "SGLang 已启动，PID $!"
fi

if [[ "$H3_START_SECONDARY" == "1" ]]; then
  if curl -fsS --max-time 2 "http://127.0.0.1:${H3_SECONDARY_API_PORT}/health" >/dev/null; then
    echo "SGLang Secondary 已运行"
  elif pgrep -f "sglang serve .*MiniMax-H3/Ref2VA.*--port ${H3_SECONDARY_API_PORT}" >/dev/null; then
    echo "SGLang Secondary 正在启动"
  else
    nohup bash scripts/start_sglang_secondary.sh </dev/null >>"$H3_RUNTIME_ROOT/sglang-secondary.log" 2>&1 &
    echo "SGLang Secondary 已启动，PID $!"
  fi
fi

if curl -fsS --max-time 2 "http://127.0.0.1:${H3_WEB_PORT}/api/bootstrap/status" >/dev/null; then
  echo "WebUI 已运行"
elif command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"$H3_WEB_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "WebUI 正在启动"
else
  nohup bash scripts/start_webui.sh </dev/null >/dev/null 2>&1 &
  echo "WebUI 已启动，PID $!"
fi
