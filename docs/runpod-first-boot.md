# Primer arranque en RunPod: receta completa

Esta secuencia debe ejecutarse en orden. No iniciar modelos hasta que las comprobaciones pasen.

## 0. Configuración del Pod

Antes de pulsar Deploy:

- GPU: NVIDIA RTX A6000 (48 GB).
- Imagen: plantilla oficial PyTorch con CUDA 12.8.x.
- Disco del contenedor: 50 GB mínimo.
- Recomendado: Volume Disk de 40–60 GB montado en /workspace.
- Puerto HTTP público: 7860.
- Puerto 8765: interno, no es necesario publicarlo.
- Habilitar acceso SSH.

Sin Volume Disk, detener o reiniciar el Pod borra repositorio, entorno y cachés. Para una prueba única se puede continuar sin volumen, pero no se debe detener el Pod entre pasos.

Importante: en un Pod sin volumen, no usar `Edit Pod` para añadir puertos después
del despliegue. Declara `7860/http` al crear el Pod; si falta, crea un Pod nuevo
con ese puerto desde el principio.

## 1. Entrar por SSH

En RunPod: Pods → Pod → Connect → SSH. Copiar el comando que muestra el panel y ejecutarlo desde PowerShell local:

~~~powershell
ssh root@IP_DEL_POD -p PUERTO -i C:\Users\felip\.ssh\id_ed25519
~~~

SSH es preferible al Web Terminal para procesos largos.

## 2. Comprobar hardware antes de instalar

Estos comandos no descargan modelos:

~~~bash
nvidia-smi
python --version
python -c "import torch; print('torch:', torch.__version__); print('torch CUDA:', torch.version.cuda); print('CUDA disponible:', torch.cuda.is_available()); print('GPU:', torch.cuda.get_device_name(0)); print('torch path:', torch.__file__); assert torch.cuda.is_available()"
command -v uv
command -v git
~~~

Esperamos Python 3.12.x, PyTorch 2.8.0+cu128 (o equivalente CUDA 12.8), CUDA disponible, RTX A6000 y torch path dentro de /usr/local/lib/python3.12/dist-packages.

## 3. Clonar el fork

~~~bash
cd /workspace
git clone -b demo-foundation https://github.com/Felipe-717/speech-to-speech.git
cd /workspace/speech-to-speech
~~~

## 4. Crear el entorno Python correcto

La imagen ya trae PyTorch con CUDA. PEP 668 impide instalar directamente en /usr, por lo que creamos un venv que hereda los paquetes globales:

~~~bash
uv venv --system-site-packages .venv
source .venv/bin/activate
which python
python -c "import torch; print(torch.__version__); print(torch.__file__); print(torch.cuda.is_available())"
~~~

Debe aparecer .venv/bin/python, pero torch debe continuar en /usr/local/lib/python3.12/dist-packages/torch y CUDA debe ser True.

## 5. Instalar dependencias dentro del venv

Usar `pip` a traves del Python del venv. En esta imagen `pip` reconoce `torch`
y `torchaudio` instalados globalmente y los deja intactos. No usar `uv pip install`
para este paso: su resolvedor puede intentar descargar otra copia de PyTorch.

~~~bash
python -m pip install --dry-run -e .
python -m pip install -e .
python -m pip install -r demo/requirements.txt
~~~

En el `dry-run` deben aparecer `Requirement already satisfied` para torch y
torchaudio con version `2.8.0+cu128`. Si propone descargar otra version de
torch, detener con Ctrl+C.

Durante la instalación, si aparece una descarga grande de torch, detener con Ctrl+C: se estaría creando una segunda copia. Después verificar:

~~~bash
source .venv/bin/activate
python -c "import torch; print(torch.__version__); print(torch.__file__); print(torch.cuda.is_available())"
python -m pip check
speech-to-speech --help | head -n 20
~~~

## 6. Preparar Gemma

Con el venv activo:

~~~bash
if ! command -v llama >/dev/null 2>&1; then
  curl -LsSf https://llama.app/install.sh | sh
  source /root/.local/bin/env
fi
llama --help | head -n 5
~~~

Modelo:

~~~text
unsloth/gemma-4-12B-it-qat-GGUF:UD-Q4_K_XL
~~~

## 7. Arrancar los procesos

Usar tmux o tres sesiones SSH. Mantener el Pod encendido.

### Terminal 1: Gemma

~~~bash
cd /workspace/speech-to-speech
source .venv/bin/activate
llama serve \
  -hf unsloth/gemma-4-12B-it-qat-GGUF:UD-Q4_K_XL \
  --host 127.0.0.1 --port 8000 --jinja -c 8192 -ngl 99 \
  --reasoning-budget 0 --reasoning-format none \
  --chat-template-kwargs '{"enable_thinking":false}'
~~~

Comprobar desde otra terminal:

~~~bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"gemma-4-12B-it-qat-GGUF","messages":[{"role":"user","content":"Responde OK"}],"max_tokens":8}'
~~~

### Terminal 2: pipeline de voz

~~~bash
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
  --qwen3_tts_language spanish \
  --model_name gemma-4-12B-it-qat-GGUF \
  --responses_api_base_url http://127.0.0.1:8000/v1 \
  --responses_api_api_key local \
  --responses_api_stream \
  --enable_live_transcription
~~~

### Terminal 3: frontend y proxy

~~~bash
cd /workspace/speech-to-speech/demo
source ../.venv/bin/activate
export SPEECH_TO_SPEECH_INTERNAL_URL=ws://127.0.0.1:8765/v1/realtime
export TTS_VOICE=Serena
uvicorn server:app --host 0.0.0.0 --port 7860
~~~

Abrir:

~~~text
https://POD_ID-7860.proxy.runpod.net
~~~

## 8. Criterio de éxito

1. La página carga.
2. Push-to-talk abre el micrófono.
3. Aparece la transcripción.
4. Se escucha Serena.
5. El modo conversación responde.

No añadir todavía RAG, cámara, clonación de voz ni cambios de modelo.

## 9. Detener y conservar datos

- Con Volume Disk: detener conserva /workspace; terminar elimina el Pod.
- Sin Volume Disk: detener o reiniciar borra repositorio, .venv, cachés y modelos.
- Sin volumen, realizar toda la prueba en una sola sesión y terminar el Pod al acabar.

## Errores comunes

- externally managed: se olvidó activar .venv o se usó --system.
- torch aparece bajo .venv: se creó una segunda copia; detener y recrear el venv con --system-site-packages.
- GPU no disponible: plantilla o Pod incorrecto.
- speech-to-speech no existe: la instalación del proyecto no terminó.
