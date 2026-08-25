from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import httpx
import psutil
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
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
    version="0.5.1",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/ui", StaticFiles(directory=UI_DIR), name="ui")


# Do not put prompts or generated text in this registry: /health is a local
# diagnostic endpoint and must remain safe to open in a browser.  It only
# records the request's technical state so REA can show that Орфо is actually
# being processed by AIB rather than merely waiting on its HTTP request.
active_requests: dict[str, dict[str, Any]] = {}
last_request: dict[str, Any] | None = None


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

    # Optional opaque caller label for local diagnostics. It must never contain
    # prompt text; REA uses a recording ID here to match /health activity.
    activity_label: str | None = Field(default=None, max_length=160)


class PromptConfigUpdate(BaseModel):
    system_prompt: str
    runtime_prompt: str


class EmbedRequest(BaseModel):
    input: str | list[str]
    model: str = EMBED_MODEL
    keep_alive: str = "10m"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def start_activity(
    *,
    kind: str,
    model: str,
    prompt_preset: str | None = None,
    think: bool | None = None,
    label: str | None = None,
) -> str:
    request_id = uuid4().hex
    active_requests[request_id] = {
        "id": request_id,
        "kind": kind,
        "model": model,
        "promptPreset": prompt_preset,
        "think": think,
        "label": label,
        "phase": "Отправляем запрос в Ollama",
        "startedAt": utc_now(),
        "_startedAt": time.monotonic(),
    }
    return request_id


def update_activity(request_id: str, phase: str) -> None:
    activity = active_requests.get(request_id)
    if activity:
        activity["phase"] = phase


def finish_activity(request_id: str, status: str) -> None:
    global last_request
    activity = active_requests.pop(request_id, None)
    if not activity:
        return
    elapsed = max(0.0, time.monotonic() - float(activity["_startedAt"]))
    last_request = {
        key: value
        for key, value in activity.items()
        if not key.startswith("_")
    }
    last_request.update(
        {
            "status": status,
            "finishedAt": utc_now(),
            "elapsedSeconds": round(elapsed, 1),
        }
    )


def active_requests_payload() -> list[dict[str, Any]]:
    activities: list[dict[str, Any]] = []
    for activity in active_requests.values():
        public = {key: value for key, value in activity.items() if not key.startswith("_")}
        public["elapsedSeconds"] = round(max(0.0, time.monotonic() - float(activity["_startedAt"])), 1)
        activities.append(public)
    return sorted(activities, key=lambda item: str(item["startedAt"]))


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


def format_health_age(seconds: Any) -> str:
    try:
        total = max(0, int(float(seconds)))
    except (TypeError, ValueError):
        return "—"
    minutes, remainder = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours} ч")
    if minutes:
        parts.append(f"{minutes} мин")
    if remainder or not parts:
        parts.append(f"{remainder} с")
    return " ".join(parts)


def health_html(payload: dict[str, Any]) -> str:
    activities = payload.get("activeRequests") if isinstance(payload.get("activeRequests"), list) else []
    busy = bool(activities)
    state = "Выполняется запрос к модели" if busy else "AIB готов к работе"
    state_class = "busy" if busy else "ready"
    ollama = payload.get("ollama") if isinstance(payload.get("ollama"), dict) else {}
    ollama_state = "Подключён" if ollama.get("status") == "ok" else "Недоступен"
    active_cards = "".join(
        f"<section class=\"active-card\"><strong>{escape(str(item.get('kind') or 'Запрос'))}</strong>"
        f"<span>{escape(str(item.get('phase') or 'Обработка'))}</span>"
        f"<span>Модель: {escape(str(item.get('model') or '—'))} · {escape(format_health_age(item.get('elapsedSeconds')))}</span>"
        f"</section>"
        for item in activities
    ) or '<section class="active-card"><strong>Активных запросов нет</strong><span>Новые запросы появятся здесь во время работы с моделью.</span></section>'
    last = payload.get("lastRequest") if isinstance(payload.get("lastRequest"), dict) else None
    last_text = "Пока нет завершённых запросов"
    if last:
        last_text = (
            f"{last.get('kind') or 'Запрос'} · {last.get('model') or '—'} · "
            f"{last.get('status') or '—'} · {format_health_age(last.get('elapsedSeconds'))}"
        )
    return f"""<!doctype html>
<html lang=\"ru\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <meta http-equiv=\"refresh\" content=\"2\">
  <title>AIB — статус</title>
  <style>
    :root{{color-scheme:dark;font-family:Inter,Segoe UI,Arial,sans-serif;background:#102a37;color:#ecf4f6}}
    body{{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;background:radial-gradient(circle at top,#1b5362,#102a37 58%)}}
    main{{width:min(720px,100%);border:1px solid #4d737e;border-radius:12px;background:rgba(21,54,67,.92);box-shadow:0 20px 60px rgba(0,0,0,.28);overflow:hidden}}
    header{{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:24px;border-bottom:1px solid #456773}}h1{{margin:0;font-size:24px;font-weight:650}}.version{{color:#a9c2c8;font-size:13px}}
    .state{{display:flex;align-items:center;gap:9px;padding:12px 24px;background:rgba(20,116,118,.16);font-weight:650}}.dot{{width:10px;height:10px;border-radius:50%;background:#69dfba;box-shadow:0 0 0 4px rgba(105,223,186,.12)}}.busy .dot{{background:#f4c32e;box-shadow:0 0 0 4px rgba(244,195,46,.12);animation:pulse 1.1s ease-in-out infinite}}
    .grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;padding:20px 24px}}.card,.active-card{{padding:14px;border:1px solid #456773;border-radius:7px;background:rgba(12,42,54,.48)}}.card span,.active-card span{{display:block;margin-top:6px;color:#bed1d5;font-size:13px;overflow-wrap:anywhere}}.card strong,.active-card strong{{font-size:13px}}.number{{color:#72e3df;font-size:25px!important;font-weight:700;line-height:1.1}}.active-card{{margin:0 24px 12px;border-color:#5a858f}}.active-card strong{{color:#f4d26d}}footer{{display:flex;justify-content:space-between;gap:12px;padding:16px 24px;color:#a8c2c8;font-size:12px;border-top:1px solid #456773}}a{{color:#7ce5e1}}@keyframes pulse{{50%{{opacity:.42;transform:scale(.72)}}}}@media(max-width:520px){{body{{padding:12px}}header{{padding:18px}}.grid{{grid-template-columns:1fr;padding:16px}}.active-card{{margin:0 16px 12px}}footer{{padding:14px 16px}}}}
  </style>
</head>
<body>
  <main>
    <header><div><h1>AIB (Орфо)</h1><span class=\"version\">Локальный сервис · версия {escape(str(payload.get('version') or '—'))}</span></div><a href=\"?format=json\">JSON</a></header>
    <div class=\"state {state_class}\"><span class=\"dot\"></span>{state}</div>
    <div class=\"grid\">
      <section class=\"card\"><strong>Активные запросы</strong><span class=\"number\">{len(activities)}</span></section>
      <section class=\"card\"><strong>Модель по умолчанию</strong><span>{escape(str(payload.get('default_model') or '—'))}</span></section>
      <section class=\"card\"><strong>Ollama</strong><span>{escape(ollama_state)} · {escape(str(ollama.get('version') or '—'))}</span></section>
      <section class=\"card\"><strong>Последний запрос</strong><span>{escape(last_text)}</span></section>
    </div>
    {active_cards}
    <footer><span>Страница обновляется каждые 2 секунды.</span><span>API: <code>/health</code></span></footer>
  </main>
</body>
</html>"""


def wants_html_health(request: Request) -> bool:
    requested_format = request.query_params.get("format", "").lower()
    if requested_format == "json":
        return False
    if requested_format == "html":
        return True
    return "text/html" in request.headers.get("accept", "").lower()


@app.get("/health", response_model=None)
async def health(request: Request) -> dict[str, Any] | HTMLResponse:
    try:
        response = await ollama_request("GET", "/api/version")
        version = response.json().get("version")
        ollama = {"status": "ok", "version": version, "url": OLLAMA_URL}
    except HTTPException as exc:
        ollama = {"status": "unavailable", "url": OLLAMA_URL, "detail": exc.detail}

    resources = resource_snapshot()
    activities = active_requests_payload()
    payload = {
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
        "activeRequests": len(activities),
        "activeRequestDetails": activities,
        "lastRequest": last_request,
    }
    if wants_html_health(request):
        return HTMLResponse(health_html(payload), headers={"Cache-Control": "no-store"})
    return payload


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
    activity_id = start_activity(
        kind="chat",
        model=request.model,
        prompt_preset=request.prompt_preset,
        think=request.think,
        label=request.activity_label,
    )
    try:
        update_activity(activity_id, "Модель Ollama обрабатывает запрос")
        response = await ollama_request("POST", "/api/chat", json=payload)
        data = response.json()
        message = data.get("message") or {}
        end_resources = resource_snapshot()
        result = {
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
    except Exception:
        finish_activity(activity_id, "error")
        raise
    finish_activity(activity_id, "completed")
    return result


@app.post("/chat/stream")
async def chat_stream(chat_request: ChatRequest, request: Request) -> StreamingResponse:
    payload, prompt_metadata = build_chat_payload(chat_request, stream=True)

    async def generate():
        activity_id = start_activity(
            kind="chat_stream",
            model=chat_request.model,
            prompt_preset=chat_request.prompt_preset,
            think=chat_request.think,
            label=chat_request.activity_label,
        )
        result_status = "error"
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
            update_activity(activity_id, "Модель Ollama готовит ответ")
            timeout = httpx.Timeout(REQUEST_TIMEOUT, connect=30.0)
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
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
                            result_status = "cancelled"
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
                            update_activity(activity_id, "Модель формирует рассуждение")
                            yield ndjson({"type": "thinking", "text": thinking})
                        if content:
                            update_activity(activity_id, "Модель формирует ответ")
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
            result_status = "completed"
        except httpx.ConnectError:
            yield ndjson({"type": "error", "detail": f"Ollama is not available at {OLLAMA_URL}"})
        except httpx.HTTPError as exc:
            yield ndjson({"type": "error", "detail": str(exc)})
        finally:
            finish_activity(activity_id, result_status)

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
    activity_id = start_activity(kind="embed", model=request.model)
    try:
        update_activity(activity_id, "Модель Ollama создаёт эмбеддинги")
        response = await ollama_request("POST", "/api/embed", json=payload)
        result = response.json()
    except Exception:
        finish_activity(activity_id, "error")
        raise
    finish_activity(activity_id, "completed")
    return result
