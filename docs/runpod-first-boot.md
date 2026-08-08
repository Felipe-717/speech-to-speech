# Primer arranque en RunPod

Este documento define el intento pagado inicial. No crear el Pod hasta que la
matriz y los comandos estén confirmados.

## Decisión de infraestructura

Usar un Pod NVIDIA con la plantilla oficial de PyTorch, no la plantilla vLLM.
La razón es que el proceso principal necesita PyTorch, Parakeet TDT y Qwen3-TTS;
el LLM se ejecutará como un servicio OpenAI-compatible separado dentro del
mismo Pod. La [documentación de RunPod](https://docs.runpod.io/pods/templates/create-custom-template)
muestra como base reciente
`runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404`; si no aparece en el selector,
usar la variante oficial PyTorch más reciente con CUDA 12.8.x.

Configuración prevista:

- GPU: RTX A6000 (48 GB VRAM).
- Disco del contenedor: 50 GB mínimo.
- Volumen persistente: 40–60 GB en `/workspace` para conservar cachés de
  Hugging Face y no pagar descargas repetidas.
- Puerto HTTP público: `7860`.
- Puerto Realtime: solamente interno, `8765`.

El servidor del demo ahora puede actuar como proxy WebSocket same-origin cuando
se define `SPEECH_TO_SPEECH_INTERNAL_URL`. Esto evita exponer el puerto 8765 al
navegador. RunPod advierte que su proxy HTTP tiene un timeout de 100 segundos y
que WebSocket persistente suele funcionar mejor por TCP; para esta demo el
proxy same-origin mantiene tráfico frecuente de audio y simplifica el primer
arranque. Si se observan cortes por inactividad, pasaremos el Realtime a un
puerto TCP dedicado.

## Matriz de versiones

La matriz se deriva del `pyproject.toml` del fork:

| Componente | Valor inicial |
|---|---|
| Python | 3.12 recomendado; mínimo 3.10 |
| PyTorch | 2.8.x CUDA 12.8.x en la imagen oficial |
| Transformers | `>=4.57.0` en Linux |
| websockets | `>=12.0` |
| STT | `parakeet-tdt` en CUDA, `float16` |
| TTS | `qwen3`, backend `ggml`, voz `Serena` |
| LLM | Gemma 4 12B GGUF, cuantización `UD-Q4_K_XL` |

El [modelo Gemma indicado](https://huggingface.co/unsloth/gemma-4-12B-it-qat-GGUF)
publica una ruta oficial de `llama-server` y expone una API compatible con
OpenAI. Para el primer intento es preferible esa ruta a
forzar GGUF experimental en vLLM. vLLM queda como optimización posterior cuando
la ruta de audio ya esté estable.

## Preflight sin descargar modelos

Ejecutar en la terminal del Pod después de clonarlo, antes de instalar el
pipeline:

```bash
nvidia-smi
python --version
python - <<'PY'
import torch
print("torch", torch.__version__)
print("cuda", torch.version.cuda)
print("available", torch.cuda.is_available())
if not torch.cuda.is_available():
    raise SystemExit("CUDA no está disponible")
print("gpu", torch.cuda.get_device_name(0))
print("vram_gb", round(torch.cuda.get_device_properties(0).total_memory / 2**30, 1))
PY
```

Solo continuar si aparece la RTX A6000, CUDA disponible y al menos 40 GB de
VRAM visible. Este bloque no descarga ningún modelo.

## Instalación reproducible

```bash
cd /workspace
git clone -b demo-foundation https://github.com/Felipe-717/speech-to-speech.git
cd speech-to-speech
curl -LsSf https://astral.sh/uv/install.sh | sh
source /root/.local/bin/env
# PEP 668 bloquea instalaciones en /usr. Este venv hereda el torch global de
# la imagen PyTorch y evita crear una segunda copia pesada.
uv venv --system-site-packages .venv
source .venv/bin/activate
uv pip install -e .
uv pip install -r demo/requirements.txt
python -c 'import torch; print(torch.__file__); print(torch.__version__, torch.version.cuda)'
```

La primera instalación se hace una sola vez en el volumen persistente. No
arrancar todavía el servidor si `nvidia-smi` o la prueba de PyTorch fallan.
El `torch` que debe aparecer después de activar el venv seguirá estando en
`/usr/local/lib/python3.12/dist-packages`. Si la ruta muestra `.venv` para
`torch`, detenerse: se estaría instalando una segunda copia CUDA.

## Orden de arranque

Terminal 1: LLM local compatible con OpenAI. El nombre y la etiqueta GGUF son
los publicados por el modelo:

```bash
if ! command -v llama >/dev/null 2>&1; then
  curl -LsSf https://llama.app/install.sh | sh
  source /root/.local/bin/env
fi
llama serve \
  -hf unsloth/gemma-4-12B-it-qat-GGUF:UD-Q4_K_XL \
  --host 127.0.0.1 --port 8000 --jinja -c 8192 -ngl 99
```

Antes de iniciar voz, verificar que el LLM responde:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"gemma-4-12B-it-qat-GGUF","messages":[{"role":"user","content":"Responde OK"}],"max_tokens":8}'
```

Terminal 2: pipeline Realtime, con el backend escuchando solo dentro del Pod:

```bash
cd /workspace/speech-to-speech
source .venv/bin/activate
speech-to-speech serve \
  --host 0.0.0.0 --port 8765 \
  --stt parakeet-tdt \
  --parakeet_tdt_device cuda \
  --parakeet_tdt_compute_type float16 \
  --llm_backend chat-completions \
  --tts qwen3 \
  --qwen3_tts_device cuda \
  --qwen3_tts_backend ggml \
  --qwen3_tts_speaker Serena \
  --model_name gemma-4-12B-it-qat-GGUF \
  --responses_api_base_url http://127.0.0.1:8000/v1 \
  --responses_api_api_key local \
  --responses_api_stream \
  --enable_live_transcription
```

Terminal 3: frontend/proxy. El valor interno no se envía al navegador:

```bash
cd /workspace/speech-to-speech/demo
source ../.venv/bin/activate
export SPEECH_TO_SPEECH_INTERNAL_URL=ws://127.0.0.1:8765/v1/realtime
export TTS_VOICE=Serena
uvicorn server:app --host 0.0.0.0 --port 7860
```

Abrir `https://<POD_ID>-7860.proxy.runpod.net`. La interfaz conecta al
same-origin `/v1/realtime`; no hay que escribir una URL de backend en el
navegador.

## Criterio de éxito del primer intento

Antes de probar RAG o clonar voz, deben cumplirse estos cuatro puntos:

1. `/health` carga la interfaz.
2. El botón de pulsar para hablar abre el micrófono.
3. Se ve transcripción del usuario y respuesta del asistente.
4. Se escucha Serena sin repetir, cortar o quedarse en silencio.

Si falla cualquier punto, se detiene el Pod y se corrige solo esa capa. No se
añaden RAG, cámara, clonación ni cambios de modelo en el mismo intento.
