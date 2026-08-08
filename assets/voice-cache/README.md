# Caché de voz clonada

Estos archivos son la referencia Qwen3-TTS Base validada para la demo:

- `*.spk`: embedding del hablante.
- `*.rvq`: códigos acústicos para ICL.
- `*.json`: metadatos generados por `qwentts.cpp`.

El WAV original no se publica. `scripts/runpod-01-setup.sh` copia esta caché a
`/workspace/voices/cache` cuando el Pod no tiene ya una caché personalizada.
El pipeline la usa directamente y solo necesita el WAV si se desea regenerar o
reemplazar la voz.
