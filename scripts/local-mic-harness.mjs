#!/usr/bin/env node
/**
 * Dependency-free local Realtime harness.
 *
 * Serves demo/ on :7860 and accepts a minimal OpenAI-Realtime-style WebSocket
 * on :8765. It is intentionally not a speech backend: it verifies that the
 * upstream browser client opens the socket and sends 16 kHz PCM16 frames.
 */

import { createHash } from "node:crypto";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(fileURLToPath(new URL("../demo", import.meta.url)));
const HTTP_PORT = Number(process.env.LOCAL_HTTP_PORT || 7860);
const WS_PORT = Number(process.env.LOCAL_WS_PORT || 8765);
const clients = new Set();

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".svg": "image/svg+xml",
  ".json": "application/json; charset=utf-8",
  ".wav": "audio/wav",
};

function json(type, extra = {}) {
  return JSON.stringify({ type, event_id: `mock_${Date.now()}_${Math.random().toString(16).slice(2)}`, ...extra });
}

function frameText(text) {
  const payload = Buffer.from(text);
  if (payload.length < 126) return Buffer.concat([Buffer.from([0x81, payload.length]), payload]);
  if (payload.length < 65536) {
    const header = Buffer.alloc(4);
    header[0] = 0x81;
    header[1] = 126;
    header.writeUInt16BE(payload.length, 2);
    return Buffer.concat([header, payload]);
  }
  const header = Buffer.alloc(10);
  header[0] = 0x81;
  header[1] = 127;
  header.writeBigUInt64BE(BigInt(payload.length), 2);
  return Buffer.concat([header, payload]);
}

function framePong(payload) {
  const body = Buffer.from(payload);
  return Buffer.concat([Buffer.from([0x8a, body.length]), body]);
}

function send(client, event) {
  if (!client.socket.destroyed) client.socket.write(frameText(typeof event === "string" ? event : JSON.stringify(event)));
}

function pcmToneBase64(durationMs = 120, sampleRate = 16000) {
  const samples = Math.round(sampleRate * durationMs / 1000);
  const pcm = Buffer.alloc(samples * 2);
  for (let i = 0; i < samples; i += 1) {
    const value = Math.round(Math.sin(i * 2 * Math.PI * 440 / sampleRate) * 3000);
    pcm.writeInt16LE(value, i * 2);
  }
  return pcm.toString("base64");
}

function handleEvent(client, text) {
  let event;
  try { event = JSON.parse(text); } catch { return; }
  const type = event?.type;
  if (type === "session.update") {
    client.configured = true;
    send(client, json("session.updated", { session: event.session || { type: "realtime" } }));
    return;
  }
  if (type === "input_audio_buffer.append") {
    const bytes = Buffer.from(String(event.audio || ""), "base64").length;
    client.frames += 1;
    client.audioBytes += bytes;
    if (bytes !== 1280) {
      console.warn(`[mock] frame ${client.frames}: expected 1280 bytes, got ${bytes}`);
    }
    if (!client.speechStarted) {
      client.speechStarted = true;
      send(client, json("input_audio_buffer.speech_started", {
        item_id: "mock_item_1",
        audio_start_ms: 0,
      }));
    }
    if (client.frames === 1 || client.frames % 25 === 0) {
      console.log(`[mock] audio frame #${client.frames}: ${bytes} bytes`);
    }
    return;
  }
  if (type === "input_audio_buffer.commit") {
    if (!client.speechStarted) return;
    send(client, json("input_audio_buffer.speech_stopped", {
      item_id: "mock_item_1",
      audio_end_ms: Math.round(client.audioBytes / 32),
    }));
    send(client, json("conversation.item.input_audio_transcription.completed", {
      item_id: "mock_item_1",
      transcript: "Prueba de microfono local recibida.",
    }));
    send(client, json("response.created", {
      response: { id: "mock_response_1", status: "in_progress" },
    }));
    send(client, json("response.output_audio_transcript.delta", {
      response_id: "mock_response_1",
      delta: "Recibi tu audio local.",
    }));
    send(client, json("response.output_audio_transcript.done", {
      response_id: "mock_response_1",
      transcript: "Recibi tu audio local.",
    }));
    send(client, json("response.output_audio.delta", {
      response_id: "mock_response_1",
      delta: pcmToneBase64(),
    }));
    send(client, json("response.output_audio.done", { response_id: "mock_response_1" }));
    send(client, json("response.done", {
      response: { id: "mock_response_1", status: "completed", output: [] },
    }));
    console.log(`[mock] turn complete: ${client.frames} frames, ${client.audioBytes} bytes`);
    client.speechStarted = false;
  }
}

function consumeFrames(client) {
  while (client.buffer.length >= 2) {
    const first = client.buffer[0];
    const second = client.buffer[1];
    const masked = Boolean(second & 0x80);
    let length = second & 0x7f;
    let offset = 2;
    if (length === 126) {
      if (client.buffer.length < 4) return;
      length = client.buffer.readUInt16BE(2);
      offset = 4;
    } else if (length === 127) {
      if (client.buffer.length < 10) return;
      const big = client.buffer.readBigUInt64BE(2);
      if (big > BigInt(Number.MAX_SAFE_INTEGER)) throw new Error("WebSocket frame too large");
      length = Number(big);
      offset = 10;
    }
    const maskOffset = masked ? 4 : 0;
    const total = offset + maskOffset + length;
    if (client.buffer.length < total) return;
    const mask = masked ? client.buffer.subarray(offset, offset + 4) : null;
    const start = offset + maskOffset;
    const payload = Buffer.from(client.buffer.subarray(start, start + length));
    client.buffer = client.buffer.subarray(total);
    if (mask) for (let i = 0; i < payload.length; i += 1) payload[i] ^= mask[i % 4];
    const opcode = first & 0x0f;
    if (opcode === 0x1) handleEvent(client, payload.toString("utf8"));
    else if (opcode === 0x8) { client.socket.end(); return; }
    else if (opcode === 0x9) client.socket.write(framePong(payload));
  }
}

function acceptWebSocket(req, socket, head = Buffer.alloc(0)) {
  const key = req.headers["sec-websocket-key"];
  const accept = createHash("sha1").update(`${key}258EAFA5-E914-47DA-95CA-C5AB0DC85B11`).digest("base64");
  socket.write([
    "HTTP/1.1 101 Switching Protocols",
    "Upgrade: websocket",
    "Connection: Upgrade",
    `Sec-WebSocket-Accept: ${accept}`,
    "\r\n",
  ].join("\r\n"));
  const client = { socket, buffer: Buffer.alloc(0), configured: false, speechStarted: false, frames: 0, audioBytes: 0 };
  clients.add(client);
  if (head.length) client.buffer = Buffer.from(head);
  socket.on("data", chunk => { client.buffer = Buffer.concat([client.buffer, chunk]); consumeFrames(client); });
  socket.on("close", () => clients.delete(client));
  socket.on("error", () => clients.delete(client));
  send(client, json("session.created", { session: { id: "mock_session", type: "realtime" } }));
  console.log("[mock] WebSocket client connected");
}

const httpServer = createServer(async (req, res) => {
  if (req.url === "/health") {
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ status: "ok" }));
    return;
  }
  if (req.url === "/api/config") {
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ search: false, lb: false, allowDirect: true, s2sUrl: `ws://127.0.0.1:${WS_PORT}/v1/realtime`, rtc: false, iceServers: [], startupGreeting: "", auth: false }));
    return;
  }
  if (req.url === "/api/me") {
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ enabled: false }));
    return;
  }
  const pathname = decodeURIComponent((req.url || "/").split("?")[0]);
  const relative = pathname === "/" ? "index.html" : pathname.replace(/^\/+/, "");
  const file = resolve(join(ROOT, normalize(relative)));
  if (!file.startsWith(ROOT)) { res.writeHead(403); res.end("Forbidden"); return; }
  try {
    const body = await readFile(file);
    res.writeHead(200, { "content-type": MIME[extname(file).toLowerCase()] || "application/octet-stream" });
    res.end(body);
  } catch {
    res.writeHead(404); res.end("Not found");
  }
});

const wsServer = createServer();
wsServer.on("upgrade", (req, socket, head) => {
  if (!req.url?.startsWith("/v1/realtime")) { socket.destroy(); return; }
  acceptWebSocket(req, socket, head);
});

httpServer.listen(HTTP_PORT, "127.0.0.1", () => console.log(`[mock] HTTP http://127.0.0.1:${HTTP_PORT}`));
wsServer.listen(WS_PORT, "127.0.0.1", () => console.log(`[mock] WS ws://127.0.0.1:${WS_PORT}/v1/realtime`));

function shutdown() {
  for (const client of clients) client.socket.destroy();
  httpServer.close();
  wsServer.close();
}
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
