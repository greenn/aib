from __future__ import annotations

import os
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

load_dotenv()

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
DEFAULT_MODEL = os.getenv("AIB_DEFAULT_MODEL", "qwen3:4b")
EMBED_MODEL = os.getenv("AIB_EMBED_MODEL", "nomic-embed-text")
REQUEST_TIMEOUT = float(os.getenv("AIB_REQUEST_TIMEOUT", "600"))

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
    version="0.1.0",
)

# Development default. The service is bound to 127.0.0.1 by the startup script.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1)
    model: str = DEFAULT_MODEL
    system: str | None = None
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    keep_alive: str = "10m"


class EmbedRequest(BaseModel):
    input: str | list[str]
    model: str = EMBED_MODEL
    keep_alive: str = "10m"


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
        "docs": "/docs",
    }


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
    payload: dict[str, Any] = {
        "model": request.model,
        "prompt": request.prompt,
        "stream": False,
        "keep_alive": request.keep_alive,
        "options": {"temperature": request.temperature},
    }
    if request.system:
        payload["system"] = request.system

    response = await ollama_request("POST", "/api/generate", json=payload)
    data = response.json()

    return {
        "model": data.get("model", request.model),
        "response": data.get("response", ""),
        "done": data.get("done", False),
        "done_reason": data.get("done_reason"),
        "total_duration": data.get("total_duration"),
        "load_duration": data.get("load_duration"),
        "prompt_eval_count": data.get("prompt_eval_count"),
        "prompt_eval_duration": data.get("prompt_eval_duration"),
        "eval_count": data.get("eval_count"),
        "eval_duration": data.get("eval_duration"),
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
