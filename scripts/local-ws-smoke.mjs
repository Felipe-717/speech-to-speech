#!/usr/bin/env node
/** Small dependency-free WebSocket smoke test for local-mic-harness.mjs. */

import { createHash, randomBytes } from "node:crypto";
import { createConnection } from "node:net";

const key = randomBytes(16).toString("base64");
const socket = createConnection(8765, "127.0.0.1");
let buffer = Buffer.alloc(0);
let upgraded = false;
let sent = false;

function frame(payload) {
  const body = Buffer.from(payload);
  const mask = randomBytes(4);
  let header;
  if (body.length < 126) {
    header = Buffer.from([0x81, 0x80 | body.length]);
  } else if (body.length < 65536) {
    header = Buffer.alloc(4);
    header[0] = 0x81;
    header[1] = 0x80 | 126;
    header.writeUInt16BE(body.length, 2);
  } else {
    throw new Error("smoke payload unexpectedly large");
  }
  const out = Buffer.concat([header, mask, body]);
  const maskStart = header.length;
  for (let i = 0; i < body.length; i += 1) out[maskStart + 4 + i] = body[i] ^ mask[i % 4];
  return out;
}

function send(event) {
  socket.write(frame(JSON.stringify(event)));
}

function sendTestEvents() {
  send({ type: "session.update", session: { type: "realtime" } });
  send({ type: "input_audio_buffer.append", audio: Buffer.alloc(1280).toString("base64") });
  send({ type: "input_audio_buffer.commit" });
  sent = true;
}

socket.on("connect", () => {
  socket.write([
    "GET /v1/realtime HTTP/1.1",
    "Host: 127.0.0.1:8765",
    "Upgrade: websocket",
    "Connection: Upgrade",
    `Sec-WebSocket-Key: ${key}`,
    "Sec-WebSocket-Version: 13",
    "\r\n",
  ].join("\r\n"));
});

socket.on("data", chunk => {
  buffer = Buffer.concat([buffer, chunk]);
  if (!upgraded) {
    const headerEnd = buffer.indexOf("\r\n\r\n");
    if (headerEnd < 0) return;
    const headers = buffer.subarray(0, headerEnd).toString();
    if (!headers.includes("101 Switching Protocols")) throw new Error("WebSocket upgrade failed");
    upgraded = true;
    buffer = buffer.subarray(headerEnd + 4);
    sendTestEvents();
  }
});

setTimeout(() => {
  if (!sent) throw new Error("WebSocket test did not send events");
  console.log("local WebSocket smoke passed: session.update, append(1280 bytes), commit");
  socket.destroy();
}, 500);

socket.on("error", error => {
  console.error(error.message);
  process.exitCode = 1;
});
