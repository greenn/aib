# aib

Local backend for AI models.

`aib` provides one local HTTP API for applications that need access to local LLMs. The repository is intended to be cloned to `J:\dv\aib` on Windows. Large model files are stored locally and are never committed to GitHub.

## Structure

```text
aib/
├─ api/       HTTP API and local test UI
├─ local/     local-model setup and configuration
└─ gemini/    Gemini integration (later)
```

## First local models

| Model | Role |
| --- | --- |
| `qwen3:4b` | Fast/default local LLM |
| `qwen3:8b` | Higher-quality text model |
| `gemma3:4b` | Text and image-capable local model |
| `nomic-embed-text` | Embeddings / semantic search |

Models are downloaded by Ollama into:

```text
J:\dv\aib\local\models
```

## Quick start on Windows

Clone/pull the repository to `J:\dv\aib` and run:

```powershell
cd J:\dv\aib
powershell -ExecutionPolicy Bypass -File .\local\setup.ps1
```

The setup script checks Ollama/Python, configures model storage on `J:`, creates the Python virtual environment, installs API dependencies and checks/downloads the configured models.

Start `aib`:

```powershell
powershell -ExecutionPolicy Bypass -File .\local\start.ps1
```

The startup script prefers port `8282`. If Windows has reserved or blocked it, `aib` automatically selects another bindable local port and prints the actual URL.

## Local chat UI

Open `/chat` on the same host and port printed by `start.ps1`:

```text
http://127.0.0.1:<port>/chat
```

The UI provides model selection, Thinking On/Off, streaming output, Stop, a separate Reasoning panel, live/final resource metrics and prompt presets.

### Prompt presets

`aib` 0.5 provides three prompt modes:

- **General** — repository System prompt + Runtime context. This is the normal/recommended baseline.
- **Custom** — locally saved/editable System prompt + Runtime context from `local/prompt-config.json`.
- **Raw · no aib prompts** — `aib` adds no System prompt and no Runtime context.

Raw mode is useful for comparing the model's behavior without any instructions added by `aib`. It does **not** remove behavior learned into model weights, the tokenizer/chat template, Ollama's model template, or other model-internal alignment.

The Custom preset can be edited from the **Prompts** panel. The local config is ignored by Git and is not published to the repository.

## API prompt controls

Both `POST /chat` and `POST /chat/stream` accept:

```json
{
  "prompt_preset": "general",
  "use_system_prompt": true,
  "use_runtime_prompt": true,
  "system_prompt": null,
  "runtime_prompt": null,
  "system": null
}
```

`prompt_preset` accepts `general`, `custom`, or `raw`.

For a clean aib-level request:

```json
{
  "prompt": "Who are you?",
  "model": "qwen3:4b",
  "prompt_preset": "raw"
}
```

In `raw` mode, the aib System/Runtime layers are disabled. If the caller also omits the explicit `system` field, `aib` sends no system message before the conversation.

Repository General prompts live in:

```text
api/default_prompts.json
```

Custom prompts are saved locally in:

```text
local/prompt-config.json
```

Runtime-template variables:

```text
{model}
{ollama_url}
{models_path}
{aib_version}
```

## API

- `GET /health` — service status, memory and Ollama connectivity.
- `GET /resources` — live local CPU/RAM/model-process resource snapshot.
- `GET /models` — configured models and local availability/capabilities.
- `GET /prompt-config` — current General/Custom/Raw prompt information.
- `PUT /prompt-config` — save the Custom preset locally.
- `DELETE /prompt-config` — reset Custom to General repository prompts.
- `GET /chat` — local browser chat UI.
- `POST /chat` — non-streaming conversational generation.
- `POST /chat/stream` — NDJSON streaming conversational generation.
- `POST /embed` — embeddings through `nomic-embed-text`.

Default model: `qwen3:4b`.

## Storage

Model binaries, local data, virtual environments and secrets are excluded from Git.

Gemini support will be added later under `gemini/`.
