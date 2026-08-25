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

API_DIR = Path(__file__).resolve().parent
REPO_ROOT = API_DIR.parent
UI_DIR = API_DIR / "ui"
DEFAULT_PROMPTS_PATH = API_DIR / "default_prompts.json"
LOCAL_PROMPTS_PATH = REPO_ROOT / "local" / "prompt-config.json"

CONFIGURED_MODELS = [
    {
        "name": "qwen3:4b",
        "role": "fast",
        "developer": "Qwen / Alibaba",
        "parameters": "4B",
        "ollama_size": "2.5 GB",
        "context": "256K",
        "modalities": ["text"],
        "description": "Fast/default local LLM",
        "thinking": True,
    },
    {
        "name": "qwen3:8b",
        "role": "quality",
        "developer": "Qwen / Alibaba",
        "parameters": "8B",
        "ollama_size": "5.2 GB",
        "context": "40K",
        "modalities": ["text"],
        "description": "Higher-quality text model",
        "thinking": True,
    },
    {
        "name": "gemma3:4b",
        "role": "vision",
        "developer": "Google DeepMind",
        "parameters": "4B",
        "ollama_size": "3.3 GB",
        "context": "128K",
        "modalities": ["text", "image"],
        "description": "Text and image-capable local model",
        "thinking": False,
    },
    {
        "name": "nomic-embed-text",
        "role": "embedding",
        "developer": "Nomic AI",
        "parameters": "137M",
        "ollama_size": "274 MB",
        "context": "2K model metadata / 8K configured",
        "modalities": ["text"],
        "description": "Embeddings and semantic search; not a chat model",
        "thinking": False,
    },
]

app = FastAPI(
    title="aib",
    description="Local backend for AI models",
    version="0.5.0",
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
    history: list[ChatMessage] = Field(default_factory=list)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    keep_alive: str = "30m"
    think: bool | None = False

    # Prompt preset controls which aib-owned pre-prompt layer is used.
    # general = repository defaults; custom = locally saved/editable prompts;
    # raw = no aib system/runtime prompt at all.
    prompt_preset: Literal["general", "custom", "raw"] = "general"

    # Per-request switches/overrides. Raw preset always disables these aib layers.
    use_system_prompt: bool = True
    use_runtime_prompt: bool = True
    system_prompt: str | None = None
    runtime_prompt: str | None = None

    # Explicit caller-owned extra system instructions. This is not an aib preset layer.
    # If omitted in raw mode, the model receives no system message from aib/caller.
    system: str | None = None


class PromptConfigUpdate(BaseModel):
    system_prompt: str
    runtime_prompt: str


class EmbedRequest(BaseModel):
    input: str | list[str]
    model: str = EMBED_MODEL
    keep_alive: str = "10m"


class SafeFormatDict(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def repository_prompt_defaults() -> dict[str, str]:
    data = read_json(DEFAULT_PROMPTS_PATH)
    return {
        "system_prompt": str(data.get("system_prompt", "")),
        "runtime_prompt": str(data.get("runtime_prompt", "")),
    }


def load_prompt_config() -> dict[str, str]:
    config = repository_prompt_defaults()
    local = read_json(LOCAL_PROMPTS_PATH)
    for key in ("system_prompt", "runtime_prompt"):
        if key in local and isinstance(local[key], str):
            config[key] = local[key]
    return config


def save_prompt_config(config: dict[str, str]) -> None:
    LOCAL_PROMPTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = LOCAL_PROMPTS_PATH.with_suffix(".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temp_path.replace(LOCAL_PROMPTS_PATH)


def runtime_variables(model: str) -> dict[str, str]:
    return {
        "model": model,
        "ollama_url": OLLAMA_URL,
        "models_path": os.getenv("OLLAMA_MODELS") or str(REPO_ROOT / "local" / "models"),
        "aib_version": app.version,
    }


def render_runtime_prompt(template: str, model: str) -> str:
    return template.format_map(SafeFormatDict(runtime_variables(model)))


def preset_prompt_config(preset: str) -> dict[str, str]:
    if preset == "general":
        return repository_prompt_defaults()
    if preset == "custom":
        return load_prompt_config()
    return {"system_prompt": "", "runtime_prompt": ""}


def prompt_layers(request: ChatRequest) -> tuple[list[str], dict[str, Any]]:
    preset = request.prompt_preset
    base = preset_prompt_config(preset)
    parts: list[str] = []

    # Raw means no aib-owned pre-prompts, even if overrides were supplied.
    aib_prompts_enabled = preset != "raw"
    use_system = aib_prompts_enabled and request.use_system_prompt
    use_runtime = aib_prompts_enabled and request.use_runtime_prompt

    system_text = request.system_prompt if request.system_prompt is not None else base["system_prompt"]
    runtime_template = request.runtime_prompt if request.runtime_prompt is not None else base["runtime_prompt"]

    if use_system and system_text.strip():
        parts.append(system_text.strip())

    rendered_runtime = ""
    if use_runtime and runtime_template.strip():
        rendered_runtime = render_runtime_prompt(runtime_template, request.model).strip()
        if rendered_runtime:
            parts.append(rendered_runtime)

    # Explicit caller-owned system instructions are intentionally independent
    # from the preset. In raw mode, omit `system` too if a truly empty system
    # message is desired.
    if request.system and request.system.strip():
        parts.append("Request-specific system instructions:\n" + request.system.strip())

    metadata = {
        "preset": preset,
        "use_system_prompt": use_system,
        "use_runtime_prompt": use_runtime,
        "system_prompt_source": (
            "disabled-by-raw"
            if preset == "raw"
            else "request" if request.system_prompt is not None else preset
        ),
        "runtime_prompt_source": (
            "disabled-by-raw"
            if preset == "raw"
            else "request" if request.runtime_prompt is not None else preset
        ),
        "request_system_extra": bool(request.system and request.system.strip()),
        "rendered_runtime_prompt": rendered_runtime,
        "system_message_present": bool(parts),
    }
    return parts, metadata


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


def build_messages(request: ChatRequest) -> tuple[list[dict[str, str]], dict[str, Any]]:
    messages: list[dict[str, str]] = []
    layers, metadata = prompt_layers(request)
    if layers:
        messages.append({"role": "system", "content": "\n\n".join(layers)})

    messages.extend(message.model_dump() for message in request.history)
    messages.append({"role": "user", "content": request.prompt})
    return messages, metadata


def build_chat_payload(request: ChatRequest, *, stream: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    messages, prompt_metadata = build_messages(request)
    payload: dict[str, Any] = {
        "model": request.model,
        "messages": messages,
        "stream": stream,
        "keep_alive": request.keep_alive,
        "options": {"temperature": request.temperature},
    }
    if request.think is not None:
        payload["think"] = request.think
    return payload, prompt_metadata


def ndjson(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


async def ollama_request(method: str, path: str, **kwargs: Any) -> httpx.Response:
    try:
        # Ollama is always local. On Windows, httpx may otherwise honour a
        # system proxy rule for 127.0.0.1 and receive a misleading HTTP 502.
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, trust_env=False) as client:
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
        "prompt_config": "/prompt-config",
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


@app.get("/prompt-config")
async def get_prompt_config(model: str = DEFAULT_MODEL) -> dict[str, Any]:
    custom = load_prompt_config()
    general = repository_prompt_defaults()
    return {
        "current": custom,
        "repository_defaults": general,
        "presets": {
            "general": {
                "label": "General",
                "description": "Repository system + runtime prompts.",
                "system_prompt": general["system_prompt"],
                "runtime_prompt": general["runtime_prompt"],
                "aib_prompt_layers": True,
            },
            "custom": {
                "label": "Custom",
                "description": "Locally saved/editable system + runtime prompts.",
                "system_prompt": custom["system_prompt"],
                "runtime_prompt": custom["runtime_prompt"],
                "aib_prompt_layers": True,
            },
            "raw": {
                "label": "Raw · no aib prompts",
                "description": "No aib system/runtime prompt is added. Model weights and Ollama chat template still remain.",
                "system_prompt": "",
                "runtime_prompt": "",
                "aib_prompt_layers": False,
            },
        },
        "local_override_exists": LOCAL_PROMPTS_PATH.exists(),
        "local_override_path": str(LOCAL_PROMPTS_PATH),
        "runtime_variables": runtime_variables(model),
        "resolved_runtime_prompt": render_runtime_prompt(custom["runtime_prompt"], model),
        "request_parameters": {
            "prompt_preset": "general|custom|raw; default general",
            "use_system_prompt": "bool; applies to general/custom; raw always disables aib system prompt",
            "use_runtime_prompt": "bool; applies to general/custom; raw always disables aib runtime prompt",
            "system_prompt": "string|null; per-request override for general/custom",
            "runtime_prompt": "string|null; per-request template override for general/custom",
            "system": "string|null; explicit caller-owned extra system instructions; independent of preset",
        },
    }


@app.put("/prompt-config")
async def put_prompt_config(update: PromptConfigUpdate) -> dict[str, Any]:
    config = {
        "system_prompt": update.system_prompt,
        "runtime_prompt": update.runtime_prompt,
    }
    save_prompt_config(config)
    return {
        "saved": True,
        "path": str(LOCAL_PROMPTS_PATH),
        "current": config,
    }


@app.delete("/prompt-config")
async def reset_prompt_config() -> dict[str, Any]:
    try:
        LOCAL_PROMPTS_PATH.unlink(missing_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "reset": True,
        "current": repository_prompt_defaults(),
    }


@app.post("/chat")
async def chat(request: ChatRequest) -> dict[str, Any]:
    started_at = time.perf_counter()
    start_resources = resource_snapshot()
    payload, prompt_metadata = build_chat_payload(request, stream=False)
    response = await ollama_request("POST", "/api/chat", json=payload)
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
        "prompt_layers": prompt_metadata,
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
    payload, prompt_metadata = build_chat_payload(chat_request, stream=True)

    async def generate():
        started_at = time.perf_counter()
        start_resources = resource_snapshot()
        peak_model_ram = float(start_resources["model"]["rss_gb"])
        yield ndjson(
            {
                "type": "start",
                "model": chat_request.model,
                "think": chat_request.think,
                "prompt_layers": prompt_metadata,
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
                    "prompt_layers": prompt_metadata,
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
