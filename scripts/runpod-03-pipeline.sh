#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_DIR"

# The shared launcher performs the Gemma health check, validates the cloned
# voice reference, and starts Parakeet + Gemma + Qwen3-TTS.
exec bash "$SCRIPT_DIR/runpod-pipeline.sh"
