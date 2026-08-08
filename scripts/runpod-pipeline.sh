#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
source .venv/bin/activate

export OPENAI_API_KEY="${OPENAI_API_KEY:-local}"

if ! curl -fsS http://127.0.0.1:8000/health >/dev/null; then
  echo "ERROR: Gemma no responde en http://127.0.0.1:8000/health" >&2
  echo "Inicia primero llama serve en otra ventana de tmux." >&2
  exit 1
fi

REF_AUDIO="/workspace/voices/voz_referencia_normalizada.wav"
if [[ ! -f "$REF_AUDIO" ]]; then
  echo "ERROR: falta $REF_AUDIO" >&2
  echo "Copia y normaliza primero el WAV de referencia." >&2
  exit 1
fi

REF_TEXT='Sistemas en linea. Soy el asistente tecnico del equipo y estare disponible durante todo el montaje del robot. He revisado la biblioteca: contamos con el microcontrolador Raspberry Pi Pico, el encoder magnetico AS5600 y el controlador de motores DRV8833. El encoder responde en la direccion I2C cero equis treinta y seis. Antes del arranque conviene revisar el diseno del cableado y el ajuste de la llave de alimentacion. Empezamos por la alimentacion o por el control de los motores?'

exec speech-to-speech serve \
  --host 0.0.0.0 \
  --port 8765 \
  --stt parakeet-tdt \
  --parakeet_tdt_device cuda \
  --parakeet_tdt_compute_type float16 \
  --llm_backend chat-completions \
  --tts qwen3 \
  --qwen3_tts_model_name Qwen/Qwen3-TTS-12Hz-1.7B-Base \
  --qwen3_tts_device cuda \
  --qwen3_tts_backend ggml \
  --qwen3_tts_ref_audio "$REF_AUDIO" \
  --qwen3_tts_ref_text "$REF_TEXT" \
  --qwen3_tts_ref_cache_dir /workspace/voices/cache \
  --qwen3_tts_xvec_only false \
  --qwen3_tts_language spanish \
  --model_name gemma-4-12B-it-qat-GGUF \
  --responses_api_base_url http://127.0.0.1:8000/v1 \
  --responses_api_api_key local \
  --responses_api_stream \
  --enable_live_transcription
