/**
 * Compatibility socket for the original Spanish Voicebot interface.
 *
 * The old UI speaks a tiny custom protocol (`pulsar_fin`, `texto`, and binary
 * PCM). The current speech-to-speech backend speaks the OpenAI Realtime event
 * protocol. This adapter keeps the UI reusable while translating at the
 * browser boundary; it can be removed once the UI is migrated to the native
 * S2S client.
 */

const NativeWebSocket = globalThis.WebSocket;
const INPUT_RATE = 16_000;
const OUTPUT_RATE = 16_000;

function bytesToBase64(bytes) {
  let binary = "";
  const view = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  const step = 0x8000;
  for (let i = 0; i < view.length; i += step) {
    binary += String.fromCharCode(...view.subarray(i, i + step));
  }
  return btoa(binary);
}

function base64ToBytes(value) {
  const binary = atob(value || "");
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) out[i] = binary.charCodeAt(i);
  return out;
}

function resamplePcm48To16(input) {
  // The AudioWorklet posts an ArrayBuffer, while callers may also provide a
  // typed-array view. Handle both explicitly; treating an ArrayBuffer like a
  // view leaves the source empty in some browsers.
  const source = input instanceof Int16Array
    ? input
    : input instanceof ArrayBuffer
      ? new Int16Array(input)
      : ArrayBuffer.isView(input)
        ? new Int16Array(input.buffer, input.byteOffset, Math.floor(input.byteLength / 2))
        : new Int16Array(0);
  const length = Math.floor(source.length / 3);
  const output = new Int16Array(length);
  for (let i = 0; i < length; i += 1) {
    // Averaging three samples is cheap and avoids aliasing the microphone's
    // 48 kHz stream when the realtime server expects 16 kHz PCM.
    const j = i * 3;
    output[i] = Math.round((source[j] + source[j + 1] + source[j + 2]) / 3);
  }
  return output;
}

function pcm16Silence(milliseconds) {
  return new Int16Array(Math.floor(INPUT_RATE * milliseconds / 1000));
}

export class VoicebotRealtimeSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  constructor(requestedUrl = "") {
    this.requestedUrl = requestedUrl;
    this.readyState = VoicebotRealtimeSocket.CONNECTING;
    this.binaryType = "arraybuffer";
    this._listeners = new Map();
    this._native = null;
    this._configured = false;
    this._closedByUser = false;
    this._userTranscripts = new Map();
    this._pending = [];
    this._connect();
  }

  addEventListener(type, listener, options = {}) {
    if (typeof listener !== "function") return;
    let set = this._listeners.get(type);
    if (!set) this._listeners.set(type, set = new Set());
    if (options.once) {
      const once = (event) => {
        set.delete(once);
        listener(event);
      };
      set.add(once);
    } else {
      set.add(listener);
    }
  }

  removeEventListener(type, listener) {
    this._listeners.get(type)?.delete(listener);
  }

  _emit(type, event = {}) {
    const prop = this[`on${type}`];
    if (typeof prop === "function") prop.call(this, event);
    for (const listener of this._listeners.get(type) || []) listener.call(this, event);
  }

  async _connect() {
    try {
      const url = await this._resolveUrl();
      if (this._closedByUser) return;
      this._native = new NativeWebSocket(url);
      this._native.binaryType = "arraybuffer";
      this._native.addEventListener("open", (event) => {
        this.readyState = VoicebotRealtimeSocket.OPEN;
        for (const message of this._pending.splice(0)) this._sendRealtime(message);
        this._emit("open", event);
      });
      this._native.addEventListener("message", (event) => this._receive(event.data));
      this._native.addEventListener("error", (event) => this._emit("error", event));
      this._native.addEventListener("close", (event) => {
        this.readyState = VoicebotRealtimeSocket.CLOSED;
        this._emit("close", event);
      });
    } catch (error) {
      this.readyState = VoicebotRealtimeSocket.CLOSED;
      this._emit("error", { error });
      this._emit("close", { code: 1006, reason: String(error?.message || error) });
    }
  }

  async _resolveUrl() {
    let value = this.requestedUrl;
    if (!value || value.endsWith("/ws") || value.includes("/ws?")) {
      try {
        const response = await fetch("/api/config", { cache: "no-store" });
        if (response.ok) value = (await response.json()).s2sUrl || value;
      } catch {
        // A plain static server has no config endpoint; same-origin fallback
        // remains useful for local testing.
      }
    }
    if (!value || value.endsWith("/ws") || value.includes("/ws?")) {
      const proto = location.protocol === "https:" ? "wss:" : "ws:";
      value = `${proto}//${location.host}/v1/realtime`;
    }
    if (value.startsWith("http://")) value = `ws://${value.slice(7)}`;
    if (value.startsWith("https://")) value = `wss://${value.slice(8)}`;
    if (!value.includes("/v1/realtime")) value = `${value.replace(/\/$/, "")}/v1/realtime`;
    return value;
  }

  send(data) {
    if (typeof data === "string") {
      let message;
      try { message = JSON.parse(data); } catch { return; }
      this._translateLegacy(message);
      return;
    }
    if (data instanceof ArrayBuffer || ArrayBuffer.isView(data)) {
      const pcm = resamplePcm48To16(data);
      this._sendRealtime({ type: "input_audio_buffer.append", audio: bytesToBase64(pcm) });
    }
  }

  _sendRealtime(message) {
    if (!this._native || this._native.readyState !== NativeWebSocket.OPEN) {
      this._pending.push(message);
      return;
    }
    // The backend rejects audio until session.update has been accepted. The
    // microphone can start producing chunks immediately after the socket's
    // open event, so hold those chunks behind session.created/session.update.
    if (!this._configured && message.type !== "session.update") {
      this._pending.push(message);
      return;
    }
    this._native.send(JSON.stringify(message));
  }

  _translateLegacy(message) {
    const type = message?.type;
    if (type === "pulsar_inicio") return;
    if (type === "pulsar_fin" || type === "fin_de_turno") {
      // The backend uses server VAD. A short, real-time silence tail gives it
      // an unambiguous speech_stopped event; commit is retained for bookkeeping.
      this._sendSilenceAndCommit(600);
      return;
    }
    if (type === "modo" || type === "voz") return;
    if (type === "texto" && typeof message.text === "string" && message.text.trim()) {
      this._sendRealtime({
        type: "conversation.item.create",
        item: {
          type: "message",
          role: "user",
          content: [{ type: "input_text", text: message.text.trim() }],
        },
      });
      this._sendRealtime({ type: "response.create" });
    }
  }

  _sendSilenceAndCommit(milliseconds) {
    const silence = pcm16Silence(milliseconds);
    this._sendRealtime({ type: "input_audio_buffer.append", audio: bytesToBase64(silence) });
    this._sendRealtime({ type: "input_audio_buffer.commit" });
  }

  async _receive(raw) {
    let text = typeof raw === "string" ? raw : "";
    if (!text && raw instanceof Blob) text = await raw.text();
    if (!text && raw instanceof ArrayBuffer) text = new TextDecoder().decode(raw);
    let event;
    try { event = JSON.parse(text); } catch { return; }
    const type = event?.type;
    if (!type) return;

    if (type === "session.created") {
      this._sendRealtime({
        type: "session.update",
        session: {
          type: "realtime",
          instructions: "Responde en español de forma natural, breve y útil.",
          audio: { output: { voice: "Serena" } },
        },
      });
      this._configured = true;
      for (const pending of this._pending.splice(0)) this._sendRealtime(pending);
      this._legacy({ type: "estado", estado: "escuchando" });
      return;
    }
    if (type === "session.updated") return;

    if (type === "input_audio_buffer.speech_started") {
      this._legacy({ type: "interrupcion" });
      this._legacy({ type: "estado", estado: "hablando" });
      return;
    }
    if (type === "input_audio_buffer.speech_stopped") {
      this._legacy({ type: "estado", estado: "pensando" });
      return;
    }
    if (type === "conversation.item.input_audio_transcription.delta") {
      if (event.delta) {
        const id = event.item_id || "current";
        const previous = this._userTranscripts.get(id) || "";
        const text = !previous
          ? event.delta
          : event.delta.startsWith(previous)
            ? event.delta
            : previous.endsWith(event.delta)
              ? previous
              : `${previous}${event.delta}`;
        this._userTranscripts.set(id, text);
        this._legacy({ type: "parcial", text });
      }
      return;
    }
    if (type === "conversation.item.input_audio_transcription.completed") {
      if (event.transcript) {
        this._legacy({ type: "transcripcion", role: "user", text: event.transcript });
        this._userTranscripts.delete(event.item_id || "current");
      }
      return;
    }
    if (type === "response.audio_transcript.delta" || type === "response.output_audio_transcript.delta") {
      if (event.delta) this._legacy({ type: "transcripcion", role: "assistant", text: event.delta, kind: "live" });
      return;
    }
    if (type === "response.output_audio.delta" || type === "response.audio.delta") {
      if (event.delta) {
        this._legacy({ type: "audio", sample_rate: OUTPUT_RATE });
        this._emit("message", { data: base64ToBytes(event.delta).buffer });
      }
      return;
    }
    if (type === "response.created") {
      this._legacy({ type: "estado", estado: "pensando" });
      return;
    }
    if (type === "response.done") {
      this._legacy({ type: "estado", estado: "escuchando" });
      return;
    }
    if (type === "error") {
      const error = event.error || {};
      this._legacy({ type: "error", mensaje: error.message || "Error del servidor Realtime" });
    }
  }

  _legacy(message) {
    this._emit("message", { data: JSON.stringify(message) });
  }

  close(code = 1000, reason = "") {
    this._closedByUser = true;
    this.readyState = VoicebotRealtimeSocket.CLOSING;
    this._native?.close(code, reason);
  }
}
