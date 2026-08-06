#!/usr/bin/env bash
set -Eeuo pipefail

port="${1:-}"
if [[ "$port" != "30011" && "$port" != "30012" ]]; then
  echo "Usage: $0 30011|30012" >&2
  exit 2
fi

mapfile -t pids < <(pgrep -f "sglang serve .*--port ${port}($| )" || true)
if [[ ${#pids[@]} -eq 0 ]]; then
  echo "SGLang :${port} 未运行"
  exit 0
fi

kill "${pids[@]}"
echo "SGLang :${port} 已停止"
