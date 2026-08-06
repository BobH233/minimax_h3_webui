#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi

: "${H3_MODEL_PATH:=/data/MiniMax-H3/Ref2VA}"
: "${H3_SGLANG_IMAGE:=/data/images/sglang-dev.sif}"
: "${H3_CUDA_COMPAT:=/data/cuda-compat/13.0/root/usr/local/cuda-13.0/compat}"
: "${H3_GPU_IDS:=0,1,2,3}"
: "${H3_API_HOST:=127.0.0.1}"
: "${H3_API_PORT:=30011}"
: "${H3_MASTER_PORT:=30005}"
: "${H3_SCHEDULER_PORT:=5555}"
: "${H3_HF_HOME:=/data/huggingface_home}"
: "${H3_RUNTIME_ROOT:=/data/h3-runtime}"
: "${H3_HOST_DATA_ROOT:=/data}"
: "${H3_HTTP_PROXY:=http://127.0.0.1:8897}"

H3_GPU_IDS="${H3_INSTANCE_GPU_IDS:-$H3_GPU_IDS}"
H3_API_PORT="${H3_INSTANCE_API_PORT:-$H3_API_PORT}"
H3_MASTER_PORT="${H3_INSTANCE_MASTER_PORT:-$H3_MASTER_PORT}"
H3_SCHEDULER_PORT="${H3_INSTANCE_SCHEDULER_PORT:-$H3_SCHEDULER_PORT}"
H3_RUNTIME_ROOT="${H3_INSTANCE_RUNTIME_ROOT:-$H3_RUNTIME_ROOT}"

for path in "$H3_MODEL_PATH/model_index.json" "$H3_SGLANG_IMAGE" "$H3_CUDA_COMPAT/libcuda.so.1"; do
  if [[ ! -e "$path" ]]; then
    echo "Missing required path: $path" >&2
    exit 1
  fi
done

mkdir -p "$H3_RUNTIME_ROOT/tmp" "$H3_RUNTIME_ROOT/cache"

export APPTAINERENV_CUDA_VISIBLE_DEVICES="$H3_GPU_IDS"
export APPTAINERENV_LD_LIBRARY_PATH="/cuda-compat:/.singularity.d/libs:/usr/local/cuda/lib64"
export APPTAINERENV_HF_HOME="$H3_HF_HOME"
export APPTAINERENV_TMPDIR="$H3_RUNTIME_ROOT/tmp"
export APPTAINERENV_XDG_CACHE_HOME="$H3_RUNTIME_ROOT/cache"
export APPTAINERENV_HTTP_PROXY="$H3_HTTP_PROXY"
export APPTAINERENV_HTTPS_PROXY="$H3_HTTP_PROXY"
export APPTAINERENV_ALL_PROXY="$H3_HTTP_PROXY"
export APPTAINERENV_NO_PROXY="127.0.0.1,localhost"
export APPTAINERENV_PYTHONUNBUFFERED=1
export APPTAINERENV_NCCL_NVLS_ENABLE=0
export APPTAINERENV_PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export APPTAINERENV_SGLANG_USE_RUNAI_MODEL_STREAMER=0

exec apptainer exec \
  --cleanenv \
  --nv \
  --bind "$H3_HOST_DATA_ROOT:$H3_HOST_DATA_ROOT" \
  --bind "$H3_CUDA_COMPAT:/cuda-compat:ro" \
  "$H3_SGLANG_IMAGE" \
  sglang serve \
  --model-path "$H3_MODEL_PATH" \
  --num-gpus 4 \
  --tp-size 2 \
  --ulysses-degree 2 \
  --performance-mode speed \
  --strict-ports \
  --master-port "$H3_MASTER_PORT" \
  --scheduler-port "$H3_SCHEDULER_PORT" \
  --host "$H3_API_HOST" \
  --port "$H3_API_PORT"
