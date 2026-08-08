from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_front_keeps_upstream_contract_and_removes_legacy_transport():
    html = (REPO_ROOT / "demo" / "index.html").read_text(encoding="utf-8")
    main = (REPO_ROOT / "demo" / "main.js").read_text(encoding="utf-8")

    for selector_id in (
        "main-circle",
        "circle-caption",
        "mic-btn",
        "stop-btn",
        "bubble-stack",
        "chat-panel",
        "chat-history",
        "mode-live",
        "mode-ptt",
    ):
        assert f'id="{selector_id}"' in html

    assert "legacy-realtime-bridge.js" not in html
    assert 'const VOICE_ONLY_DEMO = false' in main
    assert 'id="text-composer"' in html
    assert 'id="task-card"' in html
    assert "\nvoid autoStartCamera();\n" not in main
    assert "\nvoid watchCameraPermission();\n" not in main


def test_front_uses_the_direct_websocket_transport():
    main = (REPO_ROOT / "demo" / "main.js").read_text(encoding="utf-8")
    assert 'const transport = "ws"' in main
    assert 'tools: VOICE_ONLY_DEMO ? [] : activeToolDefs()' in main
