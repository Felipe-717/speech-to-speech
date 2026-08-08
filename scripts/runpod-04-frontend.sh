#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_DIR/demo"
source ../.venv/bin/activate

unset LOAD_BALANCER_URL SPEECH_TO_SPEECH_INTERNAL_URL
export SPEECH_TO_SPEECH_URL="${SPEECH_TO_SPEECH_URL:-ws://127.0.0.1:8765/v1/realtime}"

exec uvicorn server:app --host 0.0.0.0 --port 7860
