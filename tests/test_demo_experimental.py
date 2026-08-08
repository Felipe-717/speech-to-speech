import importlib
import sys
from pathlib import Path

import pytest

DEMO_DIR = Path(__file__).resolve().parents[1] / "demo"
sys.path.insert(0, str(DEMO_DIR))
rag = importlib.import_module("rag")
tasks = importlib.import_module("tasks")


def test_rag_index_persists_text_and_metadata(tmp_path):
    source = tmp_path / "manual.md"
    source.write_text("El encoder AS5600 responde por I2C cero equis treinta y seis.", encoding="utf-8")
    index = rag.RagIndex(tmp_path / "rag")
    assert index.ingest_path(source) == 1
    result = index.search("AS5600 I2C")
    assert result and "AS5600" in result[0]["text"]
    assert index.status()["sources"] == 1
    reopened = rag.RagIndex(tmp_path / "rag")
    assert reopened.status()["chunks"] == 1
    assert reopened.search("encoder")


def test_rag_documents_groups_pdf_pages(tmp_path):
    index = rag.RagIndex(tmp_path / "rag")
    index.add_source("/tmp/driver.pdf#page=1", "driver.pdf", "Uno dos tres")
    index.add_source("/tmp/driver.pdf#page=2", "driver.pdf", "Cuatro cinco seis")
    documents = index.documents()
    assert len(documents) == 1
    assert documents[0]["title"] == "driver.pdf"
    assert documents[0]["pages"] == 2


def test_document_and_activity_panels_keep_the_three_card_contract():
    index = (DEMO_DIR / "index.html").read_text(encoding="utf-8")
    main = (DEMO_DIR / "main.js").read_text(encoding="utf-8")
    server = (DEMO_DIR / "server.py").read_text(encoding="utf-8")
    assert 'id="knowledge-list"' in index
    assert 'id="activity-list"' in index
    assert "const PANEL_PAGE_SIZE = 3" in main
    assert '"/api/rag/documents"' in server


def test_rag_rejects_private_urls():
    with pytest.raises(ValueError):
        rag._extract_url("http://127.0.0.1:8000/health")


def test_task_context_contains_latest_progress():
    task = tasks.TaskRecord(task_id="task_test", session_id="s", goal="Preparar resumen")
    task.status = "running"
    task.phase = "searching_web"
    task.progress = 42
    task.message = "Consultando fuentes"
    context = tasks.task_context(task)
    assert "Preparar resumen" in context
    assert "42%" in context
    assert "searching_web" in context
