# Asistente de voz

Demo de un agente de voz en español con conversación en vivo y pulsar para
hablar. El navegador captura el micrófono por WebSocket, Parakeet transcribe,
Gemma responde y Qwen3-TTS reproduce una voz clonada a partir de una referencia
WAV.

## Créditos y licencia

Este proyecto parte de [huggingface/speech-to-speech](https://github.com/huggingface/speech-to-speech), cuyo transporte realtime, servidores y componentes de audio se conservan como base técnica. El frontend de esta demo y la integración de RunPod pertenecen a este fork.

Créditos upstream: [Hugging Face](https://huggingface.co/),
[tfrere](https://huggingface.co/tfrere),
[A-Mahla](https://huggingface.co/A-Mahla) y
[andito](https://huggingface.co/andito).

El proyecto mantiene la licencia [Apache 2.0](./LICENSE) y los avisos de
copyright del repositorio original. Consulta el repositorio upstream para la
documentación general de sus componentes intercambiables.

## Qué incluye esta demo

- Frontend cálido personalizado, basado en el handoff de `Voicebot/web`.
- WebSocket upstream compatible con `/v1/realtime`.
- Modo **En vivo** con VAD del backend.
- Modo **Pulsar para hablar** con mouse, touch o barra espaciadora.
- ASR Parakeet TDT en GPU.
- LLM local Gemma 4 servido por `llama`.
- Qwen3-TTS Base con referencia de voz clonada y caché `.spk/.rvq`.
- Historial visual de conversación, sin cámara, RAG ni entrada de texto en esta fase.

## Arquitectura

```text
Micrófono del navegador
        │ PCM16 mono / 16 kHz, bloques de 40 ms
        ▼
Frontend personalizado ── WebSocket ──► speech-to-speech :8765
                                         │
                                         ├─ Parakeet TDT (ASR)
                                         ├─ Gemma 4 12B vía llama :8000
                                         └─ Qwen3-TTS Base (voz clonada)
```

El navegador debe abrirse preferiblemente en `http://localhost:7860` mediante
un túnel SSH. Así el WebSocket se conecta a
`ws://localhost:8765/v1/realtime` y los permisos del micrófono son confiables.

## Montaje recomendado en RunPod

### 1. Crear el Pod

Usa:

- GPU: NVIDIA RTX A6000 (48 GB).
- Template: PyTorch oficial con CUDA 12.8.x.
- Disco del contenedor: mínimo 50 GB.
- Recomendado: Volume Disk de 40–60 GB montado en `/workspace`.
- Puerto HTTP público: `7860`.
- SSH habilitado.

Sin volumen persistente, detener o reiniciar el Pod elimina el repositorio, el
entorno, los modelos descargados y la caché de voz.

### 2. Conectarse por SSH

Ejecuta en PowerShell el comando que entrega RunPod:

```powershell
ssh root@IP_DEL_POD -p PUERTO_SSH -i C:\Users\TU_USUARIO\.ssh\id_ed25519
```

### 3. Clonar `main`

```bash
cd /workspace
git clone -b main https://github.com/Felipe-717/speech-to-speech.git
cd /workspace/speech-to-speech
```

### 4. Copiar la referencia de voz

Desde la sesión SSH del Pod:

```bash
mkdir -p /workspace/voices
```

Desde PowerShell local, reemplaza los valores de RunPod:

```powershell
scp -P PUERTO_SSH `
  -i C:\Users\TU_USUARIO\.ssh\id_ed25519 `
  "C:\ruta\a\tu\voz_referencia.wav" `
  root@IP_DEL_POD:/workspace/voices/voz_referencia.wav
```

Comprueba la copia:

```bash
ls -lh /workspace/voices/voz_referencia.wav
```

### 5. Ejecutar el setup inicial

Este comando se ejecuta una vez por Pod. Crea un entorno virtual que hereda el
PyTorch CUDA global de la imagen; no instala una segunda copia pesada de Torch.

```bash
cd /workspace/speech-to-speech
bash scripts/runpod-01-setup.sh
```

El script instala las dependencias, prepara `llama` y genera
`/workspace/voices/voz_referencia_normalizada.wav` en mono PCM16/24 kHz.

### 6. Abrir tmux y arrancar las tres ventanas

```bash
tmux new -s voicebot
```

En cada ventana, ejecuta un script distinto. `Ctrl+B`, luego `C`, crea una
nueva ventana; `Ctrl+B`, luego `0`, `1` o `2`, cambia entre ellas.

Ventana 0 — Gemma:

```bash
bash scripts/runpod-02-llm.sh
```

Ventana 1 — pipeline de voz:

```bash
bash scripts/runpod-03-pipeline.sh
```

Ventana 2 — frontend:

```bash
bash scripts/runpod-04-frontend.sh
```

El orden es obligatorio: Gemma, pipeline y frontend.

### 7. Crear el túnel local

Mantén esta ventana de PowerShell abierta:

```powershell
ssh -N `
  -L 7860:127.0.0.1:7860 `
  -L 8765:127.0.0.1:8765 `
  -p PUERTO_SSH `
  -i C:\Users\TU_USUARIO\.ssh\id_ed25519 `
  root@IP_DEL_POD
```

Abre:

```text
http://localhost:7860
```

Acepta únicamente el permiso del micrófono. La cámara está desactivada en esta
versión.

## Comprobaciones antes de hablar

En otra ventana SSH:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8765/health
find /workspace/voices/cache -maxdepth 1 -type f -printf '%f\n'
```

La caché debe contener, después del primer arranque de Qwen3-TTS, archivos
`.spk`, `.rvq` y `.json`. Si no hay `.rvq`, se conserva la transcripción de la
referencia y se utiliza el `.spk` disponible.

## Pruebas de la interfaz

### Conversación en vivo

1. Selecciona **En vivo**.
2. Inicia el orbe y acepta el micrófono.
3. Habla en español y haz una pausa.
4. Comprueba transcripción, respuesta de Gemma y audio clonado.

### Pulsar para hablar

1. Selecciona **Pulsar para hablar**.
2. Mantén pulsado el orbe o la barra espaciadora.
3. Habla y suelta para cerrar el turno.
4. Repite con mouse, touch y teclado.

En las herramientas de desarrollador debe verse:

- WebSocket `101 Switching Protocols` hacia `ws://localhost:8765/v1/realtime`.
- Eventos `input_audio_buffer.append`.
- Frames de aproximadamente 40 ms: 640 muestras, 1280 bytes PCM16 antes de Base64.
- `speech_started`, `speech_stopped`, transcripción y audio de respuesta.

## Verificaciones locales sin GPU

Desde el repositorio:

```bash
node --check demo/main.js
node --check demo/ui/chat.js
node --check demo/ws/s2s-ws-client.js
node scripts/local-ws-smoke.mjs
```

El smoke WebSocket requiere que el harness local esté escuchando en los puertos
`7860` y `8765`:

```bash
node scripts/local-mic-harness.mjs
```

## Estado y límites actuales

- No se incluye RAG todavía.
- No se incluye cámara.
- No se incluye entrada de texto.
- El modelo LLM fijado para la demo es
  `unsloth/gemma-4-12B-it-qat-GGUF:UD-Q4_K_XL`.
- El modelo TTS fijado es `Qwen/Qwen3-TTS-12Hz-1.7B-Base`.
- La referencia de voz debe conservarse en un volumen persistente si se quiere
  reutilizar entre Pods.

## Detener y volver a iniciar

Con Volume Disk, detener el Pod conserva el repositorio, el entorno y la caché.
Al volver a iniciarlo:

```bash
cd /workspace/speech-to-speech
git pull --ff-only origin main
source .venv/bin/activate
bash scripts/runpod-02-llm.sh
bash scripts/runpod-03-pipeline.sh
bash scripts/runpod-04-frontend.sh
```

Sin volumen persistente, crea un Pod nuevo y repite desde la copia del WAV.

## Documentación de referencia

- [Receta completa de RunPod](./docs/runpod-first-boot.md)
- Handoff del frontend personalizado: conserva el documento de diseño del proyecto fuera del repositorio si contiene rutas locales.
- [Repositorio upstream](https://github.com/huggingface/speech-to-speech)
