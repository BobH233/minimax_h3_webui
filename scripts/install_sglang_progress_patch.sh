#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi

: "${H3_SGLANG_IMAGE:=/data/images/sglang-dev.sif}"
: "${H3_RUNTIME_ROOT:=/data/h3-runtime}"
: "${H3_SGLANG_PROGRESS_OVERLAY:=$H3_RUNTIME_ROOT/sglang-progress-overlay.img}"

EXPECTED_COMMIT="12eadf86f12aec2e6f81a6e38b61b964a4c6b529"
PATCH_FILE="$PROJECT_ROOT/patches/sglang-h3-progress.patch"
MARKER="/sgl-workspace/sglang/.h3-webui-progress-patch"

for path in "$H3_SGLANG_IMAGE" "$PATCH_FILE"; do
  if [[ ! -f "$path" ]]; then
    echo "Missing required file: $path" >&2
    exit 1
  fi
done

if [[ -f "$H3_SGLANG_PROGRESS_OVERLAY" ]]; then
  if apptainer exec --overlay "$H3_SGLANG_PROGRESS_OVERLAY:ro" \
    "$H3_SGLANG_IMAGE" test -f "$MARKER"; then
    echo "SGLang progress patch is already installed: $H3_SGLANG_PROGRESS_OVERLAY"
    exit 0
  fi
  echo "Overlay already exists and was not created by this installer: $H3_SGLANG_PROGRESS_OVERLAY" >&2
  exit 1
fi

mkdir -p "$(dirname "$H3_SGLANG_PROGRESS_OVERLAY")"
temporary_overlay="$H3_SGLANG_PROGRESS_OVERLAY.tmp.$$"
trap 'rm -f "$temporary_overlay"' EXIT

apptainer overlay create --size 128 --sparse "$temporary_overlay"
apptainer exec \
  --overlay "$temporary_overlay" \
  --bind "$PATCH_FILE:/h3-progress.patch:ro" \
  "$H3_SGLANG_IMAGE" \
  bash -s -- "$EXPECTED_COMMIT" "$MARKER" <<'SCRIPT'
set -Eeuo pipefail
cd /sgl-workspace/sglang

expected_commit="$1"
marker="$2"
actual_commit="$(git rev-parse HEAD)"
if [[ "$actual_commit" != "$expected_commit" ]]; then
  echo "Unsupported SGLang commit: $actual_commit (expected $expected_commit)" >&2
  exit 1
fi

patch --dry-run -p1 </h3-progress.patch
patch -p1 </h3-progress.patch
python -m py_compile \
  python/sglang/multimodal_gen/runtime/entrypoints/openai/protocol.py \
  python/sglang/multimodal_gen/runtime/entrypoints/openai/video_api.py \
  python/sglang/multimodal_gen/runtime/pipelines_core/stages/model_specific_stages/minimax_h3/stages/denoising.py
printf '%s\n' "$actual_commit" >"$marker"
SCRIPT

mv "$temporary_overlay" "$H3_SGLANG_PROGRESS_OVERLAY"
trap - EXIT
echo "Installed SGLang progress patch: $H3_SGLANG_PROGRESS_OVERLAY"
