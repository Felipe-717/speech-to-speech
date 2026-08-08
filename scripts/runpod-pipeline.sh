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
CACHE_SPK="${QWEN3_TTS_REF_SPK:-}"
CACHE_RVQ="${QWEN3_TTS_REF_RVQ:-}"
if [[ -z "$CACHE_SPK" ]]; then
  CACHE_SPK="$(find /workspace/voices/cache -maxdepth 1 -type f -name '*.spk' -print -quit 2>/dev/null || true)"
fi
if [[ -z "$CACHE_RVQ" && -n "$CACHE_SPK" && -f "${CACHE_SPK%.spk}.rvq" ]]; then
  CACHE_RVQ="${CACHE_SPK%.spk}.rvq"
fi
if [[ -n "$CACHE_SPK" && ! -f "$CACHE_SPK" ]]; then
  echo "ERROR: QWEN3_TTS_REF_SPK no existe: $CACHE_SPK" >&2
  exit 1
fi
if [[ -n "$CACHE_RVQ" && ! -f "$CACHE_RVQ" ]]; then
  echo "ERROR: QWEN3_TTS_REF_RVQ no existe: $CACHE_RVQ" >&2
  exit 1
fi
if [[ -z "$CACHE_SPK" && ! -f "$REF_AUDIO" ]]; then
  echo "ERROR: falta la cache de voz y también $REF_AUDIO" >&2
  echo "Ejecuta runpod-01-setup.sh o copia/normaliza el WAV de referencia." >&2
  exit 1
fi

REF_TEXT='Sistemas en linea. Soy el asistente tecnico del equipo y estare disponible durante todo el montaje del robot. He revisado la biblioteca: contamos con el microcontrolador Raspberry Pi Pico, el encoder magnetico AS5600 y el controlador de motores DRV8833. El encoder responde en la direccion I2C cero equis treinta y seis. Antes del arranque conviene revisar el diseno del cableado y el ajuste de la llave de alimentacion. Empezamos por la alimentacion o por el control de los motores?'

QWEN_REF_ARGS=(
  --qwen3_tts_ref_text "$REF_TEXT"
  --qwen3_tts_xvec_only false
  --qwen3_tts_language spanish
)
if [[ -n "$CACHE_SPK" ]]; then
  echo "Usando cache de voz: $CACHE_SPK${CACHE_RVQ:+ y $CACHE_RVQ}"
  QWEN_REF_ARGS+=(--qwen3_tts_ref_spk "$CACHE_SPK")
  [[ -n "$CACHE_RVQ" ]] && QWEN_REF_ARGS+=(--qwen3_tts_ref_rvq "$CACHE_RVQ")
else
  echo "Usando WAV de referencia y generando cache en /workspace/voices/cache"
  QWEN_REF_ARGS+=(
    --qwen3_tts_ref_audio "$REF_AUDIO"
    --qwen3_tts_ref_cache_dir /workspace/voices/cache
  )
fi

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
  "${QWEN_REF_ARGS[@]}" \
  --model_name gemma-4-12B-it-qat-GGUF \
  --responses_api_base_url http://127.0.0.1:8000/v1 \
  --responses_api_api_key local \
  --responses_api_stream \
  --enable_live_transcription
