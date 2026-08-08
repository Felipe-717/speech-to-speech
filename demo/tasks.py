"""Cancelable background-task manager for the experimental demo."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, AsyncIterator

try:
    import httpx
except ImportError:  # The manager remains importable for local unit tests.
    httpx = None

try:  # works both as ``uvicorn server:app`` from demo/ and as ``demo.server``
    from .rag import RagIndex
    from .search import format_search_results, search_web
except ImportError:  # pragma: no cover - script-style import used by RunPod
    from rag import RagIndex
    from search import format_search_results, search_web

logger = logging.getLogger("s2s.tasks")

LLM_URL = os.environ.get("LLM_HTTP_URL", "http://127.0.0.1:8000/v1/chat/completions")
LLM_MODEL = os.environ.get("LLM_MODEL", "unsloth/gemma-4-12B-it-qat-GGUF:UD-Q4_K_XL")


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class TaskRecord:
    task_id: str
    session_id: str
    goal: str
    status: str = "queued"
    progress: int = 0
    phase: str = "planning"
    message: str = "Tarea en cola"
    sources: list[dict[str, Any]] = field(default_factory=list)
    partial_result: str = ""
    final_result: str = ""
    error: str = ""
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    cancel_requested: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "session_id": self.session_id,
            "goal": self.goal,
            "status": self.status,
            "progress": self.progress,
            "phase": self.phase,
            "message": self.message,
            "sources": list(self.sources),
            "partial_result": self.partial_result,
            "final_result": self.final_result,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "cancel_requested": self.cancel_requested,
        }


class TaskLimitError(RuntimeError):
    pass


class TaskManager:
    """Own at most one task per browser session and broadcast progress via queues."""

    def __init__(self, rag: RagIndex | None = None):
        self.rag = rag or RagIndex()
        self.tasks: dict[str, TaskRecord] = {}
        self.active_by_session: dict[str, str] = {}
        self.subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}
        self.workers: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    async def create(self, session_id: str, goal: str) -> TaskRecord:
        session_id = (session_id or "").strip() or "anonymous"
        goal = " ".join((goal or "").split())
        if not goal:
            raise ValueError("La tarea necesita un objetivo.")
        async with self._lock:
            active_id = self.active_by_session.get(session_id)
            active = self.tasks.get(active_id or "")
            if active and active.status in {"queued", "running"}:
                raise TaskLimitError("Ya existe una tarea activa para esta sesión.")
            task = TaskRecord(task_id=f"task_{uuid.uuid4().hex[:12]}", session_id=session_id, goal=goal)
            self.tasks[task.task_id] = task
            self.active_by_session[session_id] = task.task_id
            self.workers[task.task_id] = asyncio.create_task(self._run(task))
        await self._publish(task, "task.created")
        return task

    async def get(self, task_id: str) -> TaskRecord | None:
        async with self._lock:
            return self.tasks.get(task_id)

    async def cancel(self, task_id: str) -> TaskRecord | None:
        task = await self.get(task_id)
        if task is None:
            return None
        task.cancel_requested = True
        if task.status in {"queued", "running"}:
            task.message = "Cancelación solicitada"
            await self._publish(task, "task.progress")
        return task

    async def subscribe(self, task_id: str) -> AsyncIterator[dict[str, Any]]:
        task = await self.get(task_id)
        if task is None:
            return
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.subscribers.setdefault(task_id, set()).add(queue)
        await queue.put({"type": "task.snapshot", **task.as_dict()})
        if task.status in {"completed", "failed", "cancelled"}:
            await queue.put({"type": f"task.{task.status}", **task.as_dict()})
        try:
            while True:
                event = await queue.get()
                yield event
                if event["type"] in {"task.completed", "task.failed", "task.cancelled"}:
                    break
        finally:
            self.subscribers.get(task_id, set()).discard(queue)

    async def shutdown(self) -> None:
        for task in self.tasks.values():
            if task.status in {"queued", "running"}:
                task.cancel_requested = True
        workers = list(self.workers.values())
        if workers:
            await asyncio.gather(*workers, return_exceptions=True)

    async def _publish(self, task: TaskRecord, event_type: str) -> None:
        task.updated_at = _now()
        event = {"type": event_type, **task.as_dict()}
        for queue in list(self.subscribers.get(task.task_id, set())):
            await queue.put(event)

    async def _update(self, task: TaskRecord, *, phase: str, progress: int, message: str) -> None:
        task.status = "running"
        task.phase = phase
        task.progress = max(0, min(100, progress))
        task.message = message
        await self._publish(task, "task.progress")

    async def _check_cancel(self, task: TaskRecord) -> None:
        if task.cancel_requested:
            task.status = "cancelled"
            task.phase = "finalizing"
            task.message = "Tarea cancelada"
            await self._publish(task, "task.cancelled")
            raise asyncio.CancelledError

    async def _run(self, task: TaskRecord) -> None:
        try:
            await self._update(task, phase="planning", progress=10, message="Preparando la tarea")
            await self._check_cancel(task)

            await self._update(task, phase="retrieving", progress=25, message="Consultando el RAG local")
            rag_results = await asyncio.to_thread(self.rag.search, task.goal, 5)
            task.sources.extend(rag_results)
            await self._check_cancel(task)

            await self._update(task, phase="searching_web", progress=45, message="Buscando información actual")
            try:
                web_results = await asyncio.to_thread(search_web, task.goal)
            except Exception as exc:
                logger.info("web search unavailable for %s: %r", task.task_id, exc)
                web_results = []
            task.sources.extend(web_results)
            await self._check_cancel(task)

            await self._update(task, phase="reading_sources", progress=60, message="Organizando las fuentes")
            rag_context = "\n\n".join(
                f"Fuente local: {item.get('source')}\n{item.get('text', '')}" for item in rag_results
            )
            web_context = format_search_results(task.goal, web_results)
            prompt = (
                "Completa la siguiente tarea con información verificable. Responde en español, "
                "sé claro y señala las fuentes cuando existan.\n\n"
                f"TAREA:\n{task.goal}\n\nRAG LOCAL:\n{rag_context or 'Sin resultados locales.'}\n\n"
                f"WEB:\n{web_context}"
            )

            await self._update(task, phase="synthesizing", progress=78, message="Gemma está preparando el resultado")
            if httpx is None:
                raise RuntimeError("La síntesis de tareas requiere el paquete httpx.")
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    LLM_URL,
                    json={
                        "model": LLM_MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 1200,
                        "temperature": 0.2,
                    },
                )
                response.raise_for_status()
                data = response.json()
            choices = data.get("choices") or []
            message = choices[0].get("message", {}) if choices else {}
            result = str(message.get("content") or message.get("reasoning_content") or "").strip()
            if not result:
                raise RuntimeError("Gemma no devolvió contenido para la tarea.")
            task.partial_result = result[:2000]
            await self._check_cancel(task)

            await self._update(task, phase="finalizing", progress=100, message="Tarea completada")
            task.status = "completed"
            task.final_result = result
            await self._publish(task, "task.completed")
        except asyncio.CancelledError:
            if task.status != "cancelled":
                task.status = "cancelled"
                await self._publish(task, "task.cancelled")
        except Exception as exc:
            logger.exception("task %s failed", task.task_id)
            task.status = "failed"
            task.error = str(exc)
            task.message = "La tarea falló"
            await self._publish(task, "task.failed")


def task_context(task: TaskRecord | None) -> str:
    """Compact status context attached to the next main-assistant response."""

    if not task or task.status not in {"queued", "running", "completed", "failed", "cancelled"}:
        return ""
    result = task.final_result or task.partial_result
    return (
        "\n\nESTADO DE TAREA EN SEGUNDO PLANO (información interna):\n"
        f"Objetivo: {task.goal}\nEstado: {task.status}\nFase: {task.phase}\n"
        f"Progreso: {task.progress}%\nÚltimo mensaje: {task.message}\n"
        f"Resultado disponible: {'sí' if result else 'no'}\n"
        "Si el usuario pregunta por esta tarea, informa con precisión y no inventes progreso."
    )


def event_json(event: dict[str, Any]) -> str:
    return json.dumps(event, ensure_ascii=False)
