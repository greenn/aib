from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import httpx
import psutil
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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
    },
    {
        "name": "qwen3:8b",
        "role": "quality",
        "description": "Higher-quality text model",
    },
    {
        "name": "gemma3:4b",
        "role": "vision",
        "description": "Text and image-capable local model",
    },
    {
        "name": "nomic-embed-text",
        "role": "embedding",
        "description": "Embeddings and semantic search",
    },
]

app = FastAPI(
    title="aib",
    description="Local backend for AI models",
    version="0.2.0",
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
    keep_alive: str = "10m"


class EmbedRequest(BaseModel):
    input: str | list[str]
    model: str = EMBED_MODEL
    keep_alive: str = "10m"


def memory_snapshot() -> dict[str, float]:
    memory = psutil.virtual_memory()
    return {
        "total_gb": round(memory.total / (1024**3), 2),
        "used_gb": round(memory.used / (1024**3), 2),
        "available_gb": round(memory.available / (1024**3), 2),
        "percent": float(memory.percent),
    }


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

    return {
        "status": "ok" if ollama["status"] == "ok" else "degraded",
        "service": "aib",
        "version": app.version,
        "default_model": DEFAULT_MODEL,
        "models_path": os.getenv("OLLAMA_MODELS"),
        "memory": memory_snapshot(),
        "ollama": ollama,
    }


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
    messages: list[dict[str, str]] = []
    if request.system:
        messages.append({"role": "system", "content": request.system})
    messages.extend(message.model_dump() for message in request.history)
    messages.append({"role": "user", "content": request.prompt})

    payload: dict[str, Any] = {
        "model": request.model,
        "messages": messages,
        "stream": False,
        "keep_alive": request.keep_alive,
        "options": {"temperature": request.temperature},
    }

    response = await ollama_request("POST", "/api/chat", json=payload)
    data = response.json()
    message = data.get("message") or {}

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
        "memory": memory_snapshot(),
    }


@app.post("/embed")
async def embed(request: EmbedRequest) -> dict[str, Any]:
    payload = {
        "model": request.model,
        "input": request.input,
        "keep_alive": request.keep_alive,
    }
    response = await ollama_request("POST", "/api/embed", json=payload)
    return response.json()
