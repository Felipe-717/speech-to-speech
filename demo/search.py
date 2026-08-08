"""Small, keyless web-search adapter used by the demo and task worker.

The default provider is DuckDuckGo through the ``ddgs`` package.  Keeping the
provider behind this module means a future SearXNG adapter can be added without
changing the frontend tools or task protocol.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

logger = logging.getLogger("s2s.search")

MAX_RESULTS = 5
CACHE_TTL_SECONDS = 60.0


@dataclass(frozen=True)
class SearchResult:
    title: str
    snippet: str
    url: str

    def as_dict(self) -> dict[str, str]:
        return {"title": self.title, "snippet": self.snippet, "url": self.url}


_cache: dict[str, tuple[float, list[SearchResult]]] = {}
_cache_lock = threading.Lock()


def _cached(query: str) -> list[SearchResult] | None:
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(query)
        if hit and hit[0] > now:
            return list(hit[1])
        if hit:
            _cache.pop(query, None)
    return None


def search_web(query: str, *, max_results: int = MAX_RESULTS) -> list[dict[str, str]]:
    """Search DuckDuckGo and return a stable, small result shape.

    ``ddgs`` performs the network request in a synchronous worker.  Callers in
    FastAPI should use ``asyncio.to_thread`` so the realtime HTTP server stays
    responsive while the provider is slow or rate-limited.
    """

    query = " ".join((query or "").split())
    if not query:
        return []
    limit = max(1, min(int(max_results), MAX_RESULTS))
    cached = _cached(query)
    if cached is not None:
        return [item.as_dict() for item in cached[:limit]]

    try:
        from ddgs import DDGS
    except ImportError as exc:  # pragma: no cover - depends on deployment extras
        raise RuntimeError("La búsqueda DuckDuckGo requiere instalar el paquete ddgs.") from exc

    try:
        raw = DDGS().text(query, backend="duckduckgo", max_results=limit)
        results = [
            SearchResult(
                title=str(item.get("title") or "").strip(),
                snippet=str(item.get("body") or item.get("snippet") or "").strip(),
                url=str(item.get("href") or item.get("url") or "").strip(),
            )
            for item in raw
        ]
        results = [item for item in results if item.title or item.snippet or item.url]
    except Exception as exc:  # provider-specific errors vary between ddgs versions
        logger.warning("DuckDuckGo search failed: %r", exc)
        raise RuntimeError("DuckDuckGo no está disponible temporalmente.") from exc

    with _cache_lock:
        _cache[query] = (time.monotonic() + CACHE_TTL_SECONDS, results)
    return [item.as_dict() for item in results]


def format_search_results(query: str, results: list[dict[str, str]]) -> str:
    """Turn search results into compact context for Gemma."""

    lines = [f"Resultados de DuckDuckGo para: {query}"]
    for result in results[:MAX_RESULTS]:
        lines.append(
            f"- {result.get('title', '')}: {result.get('snippet', '')} ({result.get('url', '')})"
        )
    if len(lines) == 1:
        lines.append("No se encontraron resultados.")
    return "\n".join(lines)
