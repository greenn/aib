from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Literal

import httpx
import psutil
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
DEFAULT_MODEL = os.getenv("AIB_DEFAULT_MODEL", "qwen3:4b")
EMBED_MODEL = os.getenv("AIB_EMBED_MODEL", "nomic-embed-text")
REQUEST_TIMEOUT = float(os.getenv("AIB_REQUEST_TIMEOUT", "600"))
UI_DIR = Path(__file__).resolve().parent / "ui"

CONFIGURED_MODELS = [
    {
        "name": "qwen3:4b",
        "role": "fast",
        "description": "Fast/default local LLM",
        "thinking": True,
    },
    {
        "name": "qwen3:8b",
        "role": "quality",
        "description": "Higher-quality text model",
        "thinking": True,
    },
    {
        "name": "gemma3:4b",
        "role": "vision",
        "description": "Text and image-capable local model",
        "thinking": False,
    },
    {
        "name": "nomic-embed-text",
        "role": "embedding",
        "description": "Embeddings and semantic search",
        "thinking": False,
    },
]

app = FastAPI(
    title="aib",
    description="Local backend for AI models",
    version="0.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/ui", StaticFiles(directory=UI_DIR), name="ui")


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1)
    model: str = DEFAULT_MODEL
    system: str | None = None
    history: list[ChatMessage] = Field(default_factory=list)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    keep_alive: str = "30m"
    think: bool | None = False


class EmbedRequest(BaseModel):
    input: str | list[str]
    model: str = EMBED_MODEL
    keep_alive: str = "10m"


def model_process_snapshot() -> dict[str, Any]:
    processes: list[dict[str, float | int | str]] = []
    total_rss = 0
    total_cpu_seconds = 0.0

    for process in psutil.process_iter(["pid", "name", "memory_info", "cpu_times"]):
        try:
            name = (process.info.get("name") or "").lower()
            if "llama-server" not in name:
                continue

            memory_info = process.info.get("memory_info")
            cpu_times = process.info.get("cpu_times")
            rss = int(memory_info.rss) if memory_info else 0
            cpu_seconds = float(cpu_times.user + cpu_times.system) if cpu_times else 0.0
            total_rss += rss
            total_cpu_seconds += cpu_seconds
            processes.append(
                {
                    "pid": int(process.info["pid"]),
                    "name": name,
                    "rss_gb": round(rss / (1024**3), 3),
                    "cpu_seconds": round(cpu_seconds, 3),
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return {
        "rss_gb": round(total_rss / (1024**3), 3),
        "cpu_seconds": round(total_cpu_seconds, 3),
        "processes": processes,
    }


def resource_snapshot() -> dict[str, Any]:
    memory = psutil.virtual_memory()
    return {
        "system_ram_total_gb": round(memory.total / (1024**3), 2),
        "system_ram_used_gb": round(memory.used / (1024**3), 2),
        "system_ram_available_gb": round(memory.available / (1024**3), 2),
        "system_ram_percent": float(memory.percent),
        "system_cpu_percent": float(psutil.cpu_percent(interval=None)),
        "model": model_process_snapshot(),
    }


def cpu_map(snapshot: dict[str, Any]) -> dict[int, float]:
    return {
        int(item["pid"]): float(item["cpu_seconds"])
        for item in snapshot.get("model", {}).get("processes", [])
    }


def cpu_work_seconds(start: dict[str, Any], end: dict[str, Any]) -> float:
    start_cpu = cpu_map(start)
    total = 0.0
    for pid, end_value in cpu_map(end).items():
        total += max(0.0, end_value - start_cpu.get(pid, 0.0))
    return round(total, 3)


def build_messages(request: ChatRequest) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if request.system:
        messages.append({"role": "system", "content": request.system})
    messages.extend(message.model_dump() for message in request.history)
    messages.append({"role": "user", "content": request.prompt})
    return messages


def build_chat_payload(request: ChatRequest, *, stream: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": request.model,
        "messages": build_messages(request),
        "stream": stream,
        "keep_alive": request.keep_alive,
        "options": {"temperature": request.temperature},
    }
    if request.think is not None:
        payload["think"] = request.think
    return payload


def ndjson(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


async def ollama_request(method: str, path: str, **kwargs: Any) -> httpx.Response:
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.request(method, f"{OLLAMA_URL}{path}", **kwargs)
            response.raise_for_status()
            return response
    except httpx.ConnectError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Ollama is not available at {OLLAMA_URL}",
        ) from exc
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text
        raise HTTPException(status_code=exc.response.status_code, detail=detail) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "service": "aib",
        "version": app.version,
        "chat": "/chat",
        "docs": "/docs",
    }


@app.get("/chat", response_class=FileResponse)
async def chat_ui() -> FileResponse:
    return FileResponse(UI_DIR / "index.html")


@app.get("/health")
async def health() -> dict[str, Any]:
    try:
        response = await ollama_request("GET", "/api/version")
        version = response.json().get("version")
        ollama = {"status": "ok", "version": version, "url": OLLAMA_URL}
    except HTTPException as exc:
        ollama = {"status": "unavailable", "url": OLLAMA_URL, "detail": exc.detail}

    resources = resource_snapshot()
    return {
        "status": "ok" if ollama["status"] == "ok" else "degraded",
        "service": "aib",
        "version": app.version,
        "default_model": DEFAULT_MODEL,
        "models_path": os.getenv("OLLAMA_MODELS"),
        "memory": {
            "total_gb": resources["system_ram_total_gb"],
            "used_gb": resources["system_ram_used_gb"],
            "available_gb": resources["system_ram_available_gb"],
            "percent": resources["system_ram_percent"],
        },
        "ollama": ollama,
    }


@app.get("/resources")
async def resources() -> dict[str, Any]:
    return resource_snapshot()


@app.get("/models")
async def models() -> dict[str, Any]:
    response = await ollama_request("GET", "/api/tags")
    installed_raw = response.json().get("models", [])
    installed_names = {item.get("name") for item in installed_raw}

    configured = []
    for model in CONFIGURED_MODELS:
        item = dict(model)
        item["installed"] = model["name"] in installed_names
        configured.append(item)

    return {
        "default": DEFAULT_MODEL,
        "embedding_default": EMBED_MODEL,
        "configured": configured,
        "installed": installed_raw,
    }


@app.post("/chat")
async def chat(request: ChatRequest) -> dict[str, Any]:
    started_at = time.perf_counter()
    start_resources = resource_snapshot()
    response = await ollama_request("POST", "/api/chat", json=build_chat_payload(request, stream=False))
    data = response.json()
    message = data.get("message") or {}
    end_resources = resource_snapshot()

    return {
        "model": data.get("model", request.model),
        "response": message.get("content", ""),
        "thinking": message.get("thinking"),
        "done": data.get("done", False),
        "done_reason": data.get("done_reason"),
        "total_duration": data.get("total_duration"),
        "load_duration": data.get("load_duration"),
        "prompt_eval_count": data.get("prompt_eval_count"),
        "prompt_eval_duration": data.get("prompt_eval_duration"),
        "eval_count": data.get("eval_count"),
        "eval_duration": data.get("eval_duration"),
        "server_wall_seconds": round(time.perf_counter() - started_at, 3),
        "resources": {
            "start": start_resources,
            "end": end_resources,
            "model_ram_peak_gb": max(
                float(start_resources["model"]["rss_gb"]),
                float(end_resources["model"]["rss_gb"]),
            ),
            "model_cpu_work_seconds": cpu_work_seconds(start_resources, end_resources),
        },
    }


@app.post("/chat/stream")
async def chat_stream(chat_request: ChatRequest, request: Request) -> StreamingResponse:
    payload = build_chat_payload(chat_request, stream=True)

    async def generate():
        started_at = time.perf_counter()
        start_resources = resource_snapshot()
        peak_model_ram = float(start_resources["model"]["rss_gb"])
        yield ndjson(
            {
                "type": "start",
                "model": chat_request.model,
                "think": chat_request.think,
                "resources": start_resources,
            }
        )

        final_data: dict[str, Any] = {}
        try:
            timeout = httpx.Timeout(REQUEST_TIMEOUT, connect=30.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST",
                    f"{OLLAMA_URL}/api/chat",
                    json=payload,
                ) as response:
                    if response.status_code >= 400:
                        body = await response.aread()
                        yield ndjson(
                            {
                                "type": "error",
                                "detail": body.decode("utf-8", errors="replace"),
                            }
                        )
                        return

                    async for line in response.aiter_lines():
                        if await request.is_disconnected():
                            return
                        if not line:
                            continue

                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        current_resources = resource_snapshot()
                        peak_model_ram = max(
                            peak_model_ram,
                            float(current_resources["model"]["rss_gb"]),
                        )

                        message = data.get("message") or {}
                        thinking = message.get("thinking") or ""
                        content = message.get("content") or ""

                        if thinking:
                            yield ndjson({"type": "thinking", "text": thinking})
                        if content:
                            yield ndjson({"type": "token", "text": content})

                        if data.get("done"):
                            final_data = data
                            break

            end_resources = resource_snapshot()
            peak_model_ram = max(
                peak_model_ram,
                float(end_resources["model"]["rss_gb"]),
            )
            yield ndjson(
                {
                    "type": "done",
                    "model": final_data.get("model", chat_request.model),
                    "done_reason": final_data.get("done_reason"),
                    "total_duration": final_data.get("total_duration"),
                    "load_duration": final_data.get("load_duration"),
                    "prompt_eval_count": final_data.get("prompt_eval_count"),
                    "prompt_eval_duration": final_data.get("prompt_eval_duration"),
                    "eval_count": final_data.get("eval_count"),
                    "eval_duration": final_data.get("eval_duration"),
                    "server_wall_seconds": round(time.perf_counter() - started_at, 3),
                    "resources": {
                        "start": start_resources,
                        "end": end_resources,
                        "model_ram_peak_gb": round(peak_model_ram, 3),
                        "model_cpu_work_seconds": cpu_work_seconds(start_resources, end_resources),
                    },
                }
            )
        except httpx.ConnectError:
            yield ndjson({"type": "error", "detail": f"Ollama is not available at {OLLAMA_URL}"})
        except httpx.HTTPError as exc:
            yield ndjson({"type": "error", "detail": str(exc)})

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/embed")
async def embed(request: EmbedRequest) -> dict[str, Any]:
    payload = {
        "model": request.model,
        "input": request.input,
        "keep_alive": request.keep_alive,
    }
    response = await ollama_request("POST", "/api/embed", json=payload)
    return response.json()
