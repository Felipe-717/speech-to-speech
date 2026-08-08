# Rama experimental: agente, RAG y búsqueda web gratuita

Esta fase se desarrolla en `feature/agent-rag-web`. La rama `main` conserva la
demo estable de voz y no debe usarse para validar estas funciones.

## Instalación en el Pod

Después de clonar el fork, cambia a la rama experimental:

```bash
cd /workspace/speech-to-speech
git fetch origin feature/agent-rag-web
git checkout feature/agent-rag-web
source .venv/bin/activate
python -m pip install -e .
python -m pip install -r demo/requirements.txt
```

El buscador usa `ddgs` y no requiere ninguna clave. El backend consulta
DuckDuckGo directamente, limita cada respuesta a cinco resultados y aplica una
cache breve. Puede sufrir límites del proveedor; no se utilizan Selenium,
CAPTCHA bypass ni proxies rotatorios.

La caché de voz clonada validada está versionada en `assets/voice-cache/`.
`runpod-01-setup.sh` la copia a `/workspace/voices/cache`, y el pipeline la usa
directamente sin volver a procesar el WAV.

## Directorios persistentes

Monta un volumen en `/workspace` y prepara:

```bash
mkdir -p /workspace/knowledge /workspace/rag
python -m demo.rag status
```

Añade documentos e indexa explícitamente:

```bash
python -m demo.rag ingest --path /workspace/knowledge
python -m demo.rag ingest --url https://ejemplo.com/documentacion
python -m demo.rag status
```

SQLite queda en `/workspace/rag/index.db`; los documentos originales no se
modifican. Sin volumen persistente, habrá que reindexar después de destruir el
Pod.

## Procesos

Arranca Gemma y el pipeline de voz con los scripts habituales:

```bash
bash scripts/runpod-02-llm.sh
bash scripts/runpod-03-pipeline.sh
```

En otra ventana, inicia el frontend:

```bash
export RAG_ROOT=/workspace/rag
export KNOWLEDGE_ROOT=/workspace/knowledge
bash scripts/runpod-04-frontend.sh
```

Abre el frontend mediante el túnel SSH ya validado. La entrada de texto usa la
misma sesión WebSocket que el micrófono.

## Tareas en segundo plano

El modelo puede crear una tarea con `start_background_task`. El frontend abre
SSE en `/api/tasks/{task_id}/events` y muestra una tarjeta con fase, progreso,
fuentes, resultado y cancelación.

El estado más reciente se adjunta como instrucciones internas a la siguiente
respuesta realtime. Si el usuario pregunta por el progreso, el asistente usa
`get_task_status`; `cancel_background_task` detiene la tarea activa.

Solo se permite una tarea activa por sesión en esta primera versión. Las tareas
no sobreviven a un reinicio del servidor; el RAG sí sobrevive si `/workspace`
es persistente.
