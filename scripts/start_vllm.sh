#!/usr/bin/env bash
set -Eeuo pipefail

: "${H3_MODEL:=/data/MiniMax-H3/Ref2VA}"
: "${H3_VLLM_ENV:=/data/envs/h3-vllm}"
: "${H3_RUNTIME_ROOT:=/data/h3-vllm-runtime}"
: "${H3_API_HOST:=127.0.0.1}"
: "${H3_API_PORT:=30011}"

mkdir -p "$H3_RUNTIME_ROOT"
mkdir -p "$H3_RUNTIME_ROOT/cache/torchinductor" "$H3_RUNTIME_ROOT/tmp"

export CUDA_VISIBLE_DEVICES=0,1,2,3,4,5,6,7
export LD_LIBRARY_PATH="$H3_VLLM_ENV/lib:${LD_LIBRARY_PATH:-}"
export XDG_CACHE_HOME="$H3_RUNTIME_ROOT/cache"
export TORCHINDUCTOR_CACHE_DIR="$H3_RUNTIME_ROOT/cache/torchinductor"
export TMPDIR="$H3_RUNTIME_ROOT/tmp"
export FLASHINFER_DISABLE_VERSION_CHECK=1
export NCCL_NVLS_ENABLE=0
export VLLM_WORKER_MULTIPROC_METHOD=spawn
export VLLM_OMNI_VIDEO_SYNC_TIMEOUT=1800
export PYTHONUNBUFFERED=1

exec "$H3_VLLM_ENV/bin/vllm" serve "$H3_MODEL" \
  --omni \
  --host "$H3_API_HOST" \
  --port "$H3_API_PORT" \
  --trust-remote-code \
  --num-gpus 8 \
  --usp 8 \
  --ring 1 \
  --use-hsdp \
  --hsdp-shard-size 8 \
  --text-encoder-tp-size 8 \
  --vae-patch-parallel-size 8 \
  --vae-parallel-mode tile \
  --vae-use-tiling \
  --diffusion-attention-backend TORCH_SDPA
