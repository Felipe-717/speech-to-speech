"""Local, persistent RAG index for the experimental demo branch.

The implementation deliberately keeps the operational footprint small: SQLite
stores sources/chunks and an FTS5 index, while a deterministic NumPy vector is
stored beside each chunk for hybrid lexical/vector ranking.  The vectorizer is
dependency-free and can later be replaced by a multilingual encoder without
changing the on-disk schema or API.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import html
import ipaddress
import json
import logging
import os
import re
import socket
import sqlite3
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

try:
    import httpx
except ImportError:  # URL ingestion reports a clear error when requested.
    httpx = None

logger = logging.getLogger("s2s.rag")

_LOCAL_DATA = Path(__file__).resolve().parent.parent / "data"
RAG_ROOT = Path(os.environ["RAG_ROOT"]) if os.environ.get("RAG_ROOT") else (
    Path("/workspace/rag") if Path("/workspace").exists() else _LOCAL_DATA / "rag"
)
KNOWLEDGE_ROOT = Path(os.environ["KNOWLEDGE_ROOT"]) if os.environ.get("KNOWLEDGE_ROOT") else (
    Path("/workspace/knowledge") if Path("/workspace").exists() else _LOCAL_DATA / "knowledge"
)
VECTOR_DIM = 384
CHUNK_WORDS = 700
CHUNK_OVERLAP = 100
MAX_URL_BYTES = 4 * 1024 * 1024


def _clean_text(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _url_is_public(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if host in {"localhost", "localhost.localdomain"}:
        return False
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, None)}
        return all(not ipaddress.ip_address(address).is_private for address in addresses)
    except (OSError, ValueError):
        return False


def _hashed_vector(text: str) -> np.ndarray:
    """Create a normalized multilingual-friendly token/character hash vector."""

    tokens = re.findall(r"[\wÀ-ÿ]+", text.lower())
    features = tokens + [text.lower()[i : i + 3] for i in range(max(0, len(text) - 2))]
    vector = np.zeros(VECTOR_DIM, dtype=np.float32)
    for feature in features:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "little") % VECTOR_DIM
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[index] += sign
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm else vector


def _chunks(text: str, *, size: int = CHUNK_WORDS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    words = _clean_text(text).split()
    if not words:
        return []
    step = max(1, size - overlap)
    return [" ".join(words[start : start + size]) for start in range(0, len(words), step) if words[start : start + size]]


def _extract_file(path: Path) -> list[tuple[str, str]]:
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("Para indexar PDF instala pypdf.") from exc
        reader = PdfReader(str(path))
        return [(f"{path}#page={index + 1}", page.extract_text() or "") for index, page in enumerate(reader.pages)]
    return [(str(path), path.read_text(encoding="utf-8", errors="ignore"))]


def _extract_url(url: str) -> tuple[str, str]:
    if not _url_is_public(url):
        raise ValueError("Solo se permiten URLs públicas HTTP/HTTPS.")
    if httpx is None:
        raise RuntimeError("Para indexar URLs instala httpx.")
    # Do not follow redirects automatically: a public URL must never be able
    # to redirect the indexer into localhost or a private network.
    with httpx.Client(timeout=15.0, follow_redirects=False, headers={"User-Agent": "s2s-demo-rag/1.0"}) as client:
        response = client.get(url)
        if 300 <= response.status_code < 400:
            raise ValueError("La URL devuelve una redirección; usa la URL pública final.")
        response.raise_for_status()
        if len(response.content) > MAX_URL_BYTES:
            raise ValueError("La URL supera el tamaño máximo permitido.")
    body = response.text
    body = re.sub(r"<script\b[^>]*>.*?</script>", " ", body, flags=re.I | re.S)
    body = re.sub(r"<style\b[^>]*>.*?</style>", " ", body, flags=re.I | re.S)
    body = re.sub(r"<[^>]+>", " ", body)
    return url, _clean_text(body)


class RagIndex:
    def __init__(self, root: Path | str | None = None):
        self.root = Path(root) if root else RAG_ROOT
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "vectors").mkdir(exist_ok=True)
        self.db_path = self.root / "index.db"
        self._init_db()

    @contextmanager
    def _connect(self):
        """Yield a short-lived connection and always release Windows locks."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        except BaseException:
            conn.rollback()
            raise
        else:
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sources (
                    id INTEGER PRIMARY KEY,
                    source TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    indexed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY,
                    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                    ordinal INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    vector BLOB NOT NULL,
                    page TEXT,
                    UNIQUE(source_id, ordinal)
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                    text, content='chunks', content_rowid='id'
                );
                """
            )

    def add_source(self, source: str, title: str, text: str) -> int:
        pieces = _chunks(text)
        if not pieces:
            return 0
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            old = conn.execute("SELECT id, source_hash FROM sources WHERE source=?", (source,)).fetchone()
            if old and old["source_hash"] == digest:
                return 0
            if old:
                conn.execute("DELETE FROM chunks WHERE source_id=?", (old["id"],))
                conn.execute("DELETE FROM chunks_fts WHERE rowid NOT IN (SELECT id FROM chunks)")
                source_id = int(old["id"])
                conn.execute(
                    "UPDATE sources SET title=?, source_hash=?, indexed_at=? WHERE id=?",
                    (title, digest, now, source_id),
                )
            else:
                source_id = int(
                    conn.execute(
                        "INSERT INTO sources(source,title,source_hash,indexed_at) VALUES (?,?,?,?)",
                        (source, title, digest, now),
                    ).lastrowid
                )
            for ordinal, piece in enumerate(pieces):
                chunk_id = int(
                    conn.execute(
                        "INSERT INTO chunks(source_id,ordinal,text,vector,page) VALUES (?,?,?,?,?)",
                        (source_id, ordinal, piece, _hashed_vector(piece).tobytes(), None),
                    ).lastrowid
                )
                conn.execute("INSERT INTO chunks_fts(rowid,text) VALUES (?,?)", (chunk_id, piece))
        return len(pieces)

    def ingest_path(self, path: Path | str) -> int:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(path)
        files = [path] if path.is_file() else [p for p in path.rglob("*") if p.suffix.lower() in {".pdf", ".md", ".markdown", ".txt"}]
        total = 0
        for file in files:
            for source, text in _extract_file(file):
                total += self.add_source(source, file.name, text)
        return total

    def ingest_url(self, url: str) -> int:
        source, text = _extract_url(url)
        return self.add_source(source, urllib.parse.urlparse(url).netloc, text)

    def search(self, query: str, limit: int = 5) -> list[dict[str, object]]:
        query = " ".join((query or "").split())
        if not query:
            return []
        qvec = _hashed_vector(query)
        with self._connect() as conn:
            try:
                rows = conn.execute(
                    """
                    SELECT c.id, c.text, c.vector, s.source, s.title
                    FROM chunks_fts f JOIN chunks c ON c.id=f.rowid
                    JOIN sources s ON s.id=c.source_id
                    WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT 40
                    """,
                    (query.replace('"', " "),),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            if not rows:
                rows = conn.execute(
                    "SELECT c.id,c.text,c.vector,s.source,s.title FROM chunks c JOIN sources s ON s.id=c.source_id LIMIT 200"
                ).fetchall()
        ranked = []
        for row in rows:
            vector = np.frombuffer(row["vector"], dtype=np.float32)
            similarity = float(np.dot(qvec, vector))
            ranked.append((similarity, row))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [
            {
                "text": row["text"],
                "source": row["source"],
                "title": row["title"],
                "score": round(score, 4),
            }
            for score, row in ranked[: max(1, min(int(limit), 10))]
        ]

    def status(self) -> dict[str, int | str]:
        with self._connect() as conn:
            sources = int(conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0])
            chunks = int(conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
        return {"db": str(self.db_path), "sources": sources, "chunks": chunks}

    def rebuild(self) -> dict[str, int | str]:
        with self._connect() as conn:
            conn.execute("DELETE FROM chunks_fts")
            conn.execute("DELETE FROM chunks")
            conn.execute("DELETE FROM sources")
        self.ingest_path(KNOWLEDGE_ROOT)
        return self.status()


def main() -> None:
    parser = argparse.ArgumentParser(description="Administra el índice RAG local")
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest")
    ingest.add_argument("--path")
    ingest.add_argument("--url")
    sub.add_parser("status")
    sub.add_parser("rebuild")
    args = parser.parse_args()
    index = RagIndex()
    if args.command == "ingest":
        if bool(args.path) == bool(args.url):
            parser.error("usa exactamente uno de --path o --url")
        count = index.ingest_path(args.path) if args.path else index.ingest_url(args.url)
        print(json.dumps({"chunks_nuevos": count, **index.status()}, ensure_ascii=False))
    elif args.command == "status":
        print(json.dumps(index.status(), ensure_ascii=False))
    else:
        print(json.dumps(index.rebuild(), ensure_ascii=False))


if __name__ == "__main__":
    main()
