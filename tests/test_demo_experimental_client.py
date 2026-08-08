import shutil
import subprocess
from pathlib import Path

import pytest


def test_realtime_client_can_send_text_and_response_instructions():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for demo client tests")
    script = r'''
globalThis.localStorage = { getItem() { return null; } };
globalThis.WebSocket = { OPEN: 1 };
globalThis.CustomEvent = class CustomEvent extends Event {
  constructor(type, init = {}) { super(type); this.detail = init.detail; }
};
const { S2sWsRealtimeClient } = await import("./demo/ws/s2s-ws-client.js");
const client = new S2sWsRealtimeClient({ voice: "Aiden", instructions: "Sé breve.", directUrl: "ws://unused" });
const sent = [];
client._ws = { readyState: 1, send(value) { sent.push(JSON.parse(value)); } };
client._sessionConfigured = true;
client.sendText("Resume el manual", "Tarea activa al 25 por ciento");
if (sent[0].type !== "conversation.item.create") throw new Error("text item not sent");
if (sent[0].item.content[0].text !== "Resume el manual") throw new Error("wrong text");
if (sent[1].type !== "response.create") throw new Error("response not requested");
if (sent[1].response.instructions !== "Tarea activa al 25 por ciento") throw new Error("missing context");
'''
    subprocess.run(
        [node, "--input-type=module", "-e", script],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
    )
