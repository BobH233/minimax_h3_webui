#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi

: "${H3_SECONDARY_API_PORT:=30012}"
: "${H3_SECONDARY_GPU_IDS:=0,1,2,3}"
: "${H3_RUNTIME_ROOT:=/data/h3-runtime}"

export H3_INSTANCE_API_PORT="$H3_SECONDARY_API_PORT"
export H3_INSTANCE_GPU_IDS="$H3_SECONDARY_GPU_IDS"
export H3_INSTANCE_RUNTIME_ROOT="$H3_RUNTIME_ROOT/secondary"

exec bash scripts/start_sglang.sh
