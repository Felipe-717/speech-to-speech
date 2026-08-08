#!/usr/bin/env bash
set -euo pipefail

# One-time RunPod setup. Run this from the checked-out repository before
# opening the three runtime tmux windows.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BRANCH="${S2S_BRANCH:-front-upstream-integration}"
VOICE_DIR="${VOICE_DIR:-/workspace/voices}"

cd "$REPO_DIR"

if [[ -d .git ]]; then
  git fetch origin "$BRANCH"
  if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
    git checkout "$BRANCH"
  else
    git checkout -b "$BRANCH" --track "origin/$BRANCH"
  fi
  git pull --ff-only origin "$BRANCH"
else
  echo "ERROR: ejecuta este script dentro de /workspace/speech-to-speech." >&2
  exit 1
fi

command -v uv >/dev/null || { echo "ERROR: uv no está instalado." >&2; exit 1; }
command -v git >/dev/null || { echo "ERROR: git no está instalado." >&2; exit 1; }

python -c 'import torch; assert torch.cuda.is_available(); print("torch:", torch.__version__); print("torch path:", torch.__file__); print("GPU:", torch.cuda.get_device_name(0))'

if [[ ! -x .venv/bin/python ]]; then
  uv venv --system-site-packages .venv
fi
source .venv/bin/activate

echo "Python del venv: $(command -v python)"
python -c 'import torch, torchaudio; assert torch.cuda.is_available(); print("venv torch:", torch.__version__); print("venv torchaudio:", torchaudio.__version__); print("torch path:", torch.__file__)'

# pip sees the global CUDA Torch through system-site-packages and therefore
# does not download a second Torch wheel. Do not replace these with
# `uv pip install -e .`, whose resolver may select another Torch build.
python -m pip install -e .
python -m pip install -r demo/requirements.txt
python -m pip check

if ! command -v llama >/dev/null 2>&1; then
  curl -LsSf https://llama.app/install.sh | sh
fi
export PATH="/root/.local/bin:$PATH"
command -v llama >/dev/null

mkdir -p "$VOICE_DIR/cache"
if [[ -f "$VOICE_DIR/voz_referencia.wav" && ! -f "$VOICE_DIR/voz_referencia_normalizada.wav" ]]; then
  python - <<'PY'
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

src = "/workspace/voices/voz_referencia.wav"
dst = "/workspace/voices/voz_referencia_normalizada.wav"
audio, sample_rate = sf.read(src, dtype="float32", always_2d=False)
audio = np.asarray(audio, dtype=np.float32)
if audio.ndim > 1:
    audio = audio.mean(axis=1)
if sample_rate != 24000:
    gcd = np.gcd(sample_rate, 24000)
    audio = resample_poly(audio, 24000 // gcd, sample_rate // gcd).astype(np.float32)
peak = float(np.max(np.abs(audio)))
if peak <= 0:
    raise ValueError("La referencia está completamente silenciosa")
audio *= (10 ** (-3 / 20)) / peak
sf.write(dst, audio, 24000, subtype="PCM_16")
print(f"Referencia normalizada: {dst} ({len(audio)/24000:.2f}s)")
PY
else
  if [[ -f "$VOICE_DIR/voz_referencia_normalizada.wav" ]]; then
    echo "Referencia normalizada existente: $VOICE_DIR/voz_referencia_normalizada.wav"
  else
    echo "AVISO: falta $VOICE_DIR/voz_referencia.wav" >&2
    echo "Cópialo desde PowerShell con scp y vuelve a ejecutar este script." >&2
    echo "Ejemplo: scp -P PUERTO_SSH -i C:\\Users\\felip\\.ssh\\id_ed25519 \\\"voz_referencia.wav\\\" root@IP_DEL_POD:$VOICE_DIR/voz_referencia.wav" >&2
  fi
fi

echo
echo "Setup terminado. Siguiente paso: abre tres ventanas tmux y ejecuta:"
echo "  bash scripts/runpod-02-llm.sh"
echo "  bash scripts/runpod-03-pipeline.sh"
echo "  bash scripts/runpod-04-frontend.sh"
