# Primer arranque en RunPod

Receta secuencial para la demo estable y para `feature/agent-rag-web`. La rama
experimental mantiene el mismo pipeline de voz y añade texto, RAG y tareas de
fondo.

## 0. Crear el Pod

- GPU: NVIDIA RTX A6000 (48 GB).
- Imagen: plantilla oficial PyTorch con CUDA 12.8.x.
- Disco del contenedor: 50 GB mínimo.
- Volume Disk recomendado: 40–60 GB montado en `/workspace`.
- Puerto HTTP público: `7860`.
- SSH habilitado.

Sin volumen persistente, detener o destruir el Pod elimina el entorno, modelos,
índice RAG y cachés. La caché de voz versionada en el repositorio se puede
volver a copiar automáticamente, pero los modelos grandes tendrán que
descargarse de nuevo.

## 1. Conectarse y comprobar la GPU

Ejecuta el comando SSH que entrega RunPod desde PowerShell:

```powershell
ssh root@IP_DEL_POD -p PUERTO_SSH -i C:\Users\TU_USUARIO\.ssh\id_ed25519
```

En el Pod, antes de instalar:

```bash
nvidia-smi
python --version
python -c "import torch; print(torch.__version__); print(torch.version.cuda); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0)); print(torch.__file__)"
command -v uv
command -v git
```

Debe aparecer CUDA disponible y una RTX A6000. El `torch` debe venir de la
imagen global, no de un wheel nuevo dentro del entorno virtual.

## 2. Clonar la rama

Para esta rama experimental:

```bash
cd /workspace
export S2S_BRANCH=feature/agent-rag-web
git clone -b "$S2S_BRANCH" https://github.com/Felipe-717/speech-to-speech.git
cd /workspace/speech-to-speech
```

Para la demo estable, usa `export S2S_BRANCH=main` y clona `main` en su lugar.

## 3. Ejecutar el setup único

Este script crea `.venv` con `--system-site-packages`, conserva el PyTorch/CUDA
global, instala las dependencias, prepara `llama` y copia la caché de voz
validada desde `assets/voice-cache/` a `/workspace/voices/cache`.

```bash
cd /workspace/speech-to-speech
bash scripts/runpod-01-setup.sh
```

No uses `uv pip install --system`. Si ya existe `.venv`, el script lo reutiliza.
Comprueba después:

```bash
source .venv/bin/activate
python -c "import torch, torchaudio; print(torch.__version__, torchaudio.__version__, torch.cuda.is_available())"
python -m pip check
find /workspace/voices/cache -maxdepth 1 -type f -printf '%f\n'
```

La caché incluida contiene `.spk`, `.rvq` y `.json`; no hace falta subir el WAV
para probar esta voz. Si deseas regenerarla o reemplazarla, copia un WAV propio
con `scp` y el setup lo normalizará cuando no exista ya una caché utilizable:

```powershell
scp -P PUERTO_SSH `
  -i C:\Users\TU_USUARIO\.ssh\id_ed25519 `
  "C:\ruta\a\tu\voz_referencia.wav" `
  root@IP_DEL_POD:/workspace/voices/voz_referencia.wav
```

## 4. Abrir tmux y ejecutar las ventanas

```bash
tmux new -s voicebot
```

En la ventana 0 ejecuta Gemma y déjalo corriendo:

```bash
bash scripts/runpod-02-llm.sh
```

Pulsa `Ctrl+B`, luego `C`. En la ventana 1 ejecuta el pipeline de voz:

```bash
bash scripts/runpod-03-pipeline.sh
```

El lanzador usa automáticamente la caché `.spk/.rvq` incluida. Solo utiliza el
WAV normalizado como fallback si no encuentra un `.spk`.

Pulsa `Ctrl+B`, luego `C` otra vez. En la ventana 2 ejecuta el frontend:

```bash
bash scripts/runpod-04-frontend.sh
```

El frontend queda en `0.0.0.0:7860` y el pipeline realtime en
`0.0.0.0:8765`.

## 5. Comprobaciones del backend

Desde otra sesión SSH:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8765/health
curl http://127.0.0.1:7860/health
find /workspace/voices/cache -maxdepth 1 -type f -printf '%f\n'
```

En la rama experimental, prepara el RAG si tienes documentos:

```bash
mkdir -p /workspace/knowledge /workspace/rag
source /workspace/speech-to-speech/.venv/bin/activate
python -m demo.rag ingest --path /workspace/knowledge
python -m demo.rag status
```

El índice queda en `/workspace/rag/index.db` y sobrevive si `/workspace` es un
volumen persistente. `ddgs` no necesita API key; si DuckDuckGo limita la
consulta, la herramienta devuelve un error controlado.

## 6. Túnel local para el navegador

Mantén esta ventana de PowerShell abierta:

```powershell
ssh -N `
  -L 7860:127.0.0.1:7860 `
  -L 8765:127.0.0.1:8765 `
  -p PUERTO_SSH `
  -i C:\Users\TU_USUARIO\.ssh\id_ed25519 `
  root@IP_DEL_POD
```

Abre `http://localhost:7860`. Acepta únicamente el permiso del micrófono; la
cámara está desactivada. El navegador debe mostrar un WebSocket `101` hacia
`ws://localhost:8765/v1/realtime`.

## 7. Pruebas de la demo experimental

- En vivo: habla y haz una pausa; comprueba transcripción y respuesta hablada.
- Push-to-talk: mantén pulsado el orbe o la barra espaciadora y suelta para
  cerrar el turno.
- Texto: escribe en el compositor mientras el micrófono está silenciado.
- RAG: pregunta por un documento indexado y confirma las fuentes.
- Web: solicita información actual y confirma resultados DuckDuckGo.
- Tarea: pide una investigación larga; observa fases, progreso, fuentes y
  cancelación. Pregunta por el estado mientras la tarea sigue activa.

En DevTools deben verse eventos `input_audio_buffer.append` y bloques de audio
PCM16 mono de 16 kHz, aproximadamente 40 ms por bloque (1280 bytes antes de
Base64).

## 8. Detener

Con volumen persistente, detener el Pod conserva `/workspace`, incluida la
caché y el índice RAG. Sin volumen, conserva el Pod encendido durante toda la
prueba o tendrás que repetir instalación y descargas.
