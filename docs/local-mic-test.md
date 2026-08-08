# Prueba local del micrófono y transporte realtime

Esta prueba no usa Python, GPU, RunPod ni un modelo. Sirve para comprobar que el frontend upstream abre el WebSocket y envía audio en el formato esperado antes de pagar una hora de GPU.

## 1. Arrancar el arnés

Desde la raíz del repositorio:

```powershell
node scripts/local-mic-harness.mjs
```

El arnés queda escuchando en:

- `http://127.0.0.1:7860` — frontend upstream.
- `ws://127.0.0.1:8765/v1/realtime` — WebSocket mock.

Abrir `http://127.0.0.1:7860` en un navegador normal del computador, conceder el permiso del micrófono y pulsar el orb. El navegador integrado de Codex puede quedarse esperando permiso porque normalmente no expone un dispositivo de audio; en ese caso se usa la prueba automática de abajo.

## 2. Prueba automática del WebSocket

En otra terminal, ejecutar:

```powershell
node scripts/local-ws-smoke.mjs
```

La terminal del arnés debe mostrar:

```text
[mock] WebSocket client connected
[mock] audio frame #1: 1280 bytes
[mock] turn complete: 1 frames, 1280 bytes
```

## 3. Qué valida y qué no

Valida el contrato que estaba fallando en el fork: conexión al endpoint, eventos realtime, bloques mono PCM16 de 16 kHz y respuesta de audio. No valida la calidad del ASR, el LLM ni Qwen3-TTS; esas partes requieren el Pod.

Para detener el arnés, pulsar `Ctrl+C` en su terminal. No se generan modelos ni archivos persistentes.
