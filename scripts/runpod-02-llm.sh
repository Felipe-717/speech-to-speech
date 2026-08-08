#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_DIR"
source .venv/bin/activate
export PATH="/root/.local/bin:$PATH"

command -v llama >/dev/null || { echo "ERROR: ejecuta runpod-01-setup.sh primero." >&2; exit 1; }

exec llama serve \
  -hf unsloth/gemma-4-12B-it-qat-GGUF:UD-Q4_K_XL \
  --host 127.0.0.1 \
  --port 8000 \
  --jinja \
  -c 8192 \
  -ngl 99 \
  --reasoning-budget 0 \
  --reasoning-format none \
  --chat-template-kwargs '{"enable_thinking":false}'
