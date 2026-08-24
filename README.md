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

The setup script:

1. checks that Ollama and Python are installed;
2. configures `OLLAMA_MODELS` to `J:\dv\aib\local\models` for the current user;
3. starts the Ollama CLI server with that model-storage path;
4. creates a Python virtual environment and installs API dependencies;
5. checks/downloads the initial local models.

Start `aib`:

```powershell
powershell -ExecutionPolicy Bypass -File .\local\start.ps1
```

The startup script prefers port `8181`. If Windows has reserved or blocked it, `aib` automatically selects another bindable local port and prints the actual URL.

Typical output:

```text
aib API: http://127.0.0.1:8181
API docs: http://127.0.0.1:8181/docs
```

Use the URLs printed by `start.ps1`.

## Local chat UI

Open `/chat` on the same host and port printed by `start.ps1`:

```text
http://127.0.0.1:<port>/chat
```

The UI provides:

- installed chat-model selector;
- Thinking On/Off for models that support reasoning;
- streaming output while the model generates;
- Stop button for the active request;
- conversational history for the current browser tab;
- separate scrollable Reasoning panel;
- fixed composer footer that does not overlap chat messages;
- live elapsed time, CPU load, system RAM and model RAM;
- final elapsed/model/load/prompt/generation times;
- prompt/output token counts and tokens per second;
- cumulative model CPU work in core-seconds;
- system RAM before/after the answer and peak model-process RAM;
- editable System prompt and Runtime context template under the `Prompts` button.

`qwen3:4b` uses Thinking Off by default for faster ordinary chat. Thinking can be enabled manually for tasks where extra reasoning is useful.

## Pre-prompts

`aib` has two built-in instruction layers before the user conversation:

1. **System prompt** — general assistant behavior and identity rules.
2. **Runtime context** — authoritative facts supplied by the host, such as the selected model, local Ollama runtime and model-storage path.

Repository defaults are stored in:

```text
api/default_prompts.json
```

When edited and saved through the UI, local overrides are stored in:

```text
local/prompt-config.json
```

The local override file is ignored by Git.

Runtime-template variables:

```text
{model}
{ollama_url}
{models_path}
{aib_version}
```

External API requests automatically receive the saved defaults. A caller can change them per request:

```json
{
  "prompt": "Who are you?",
  "model": "qwen3:4b",
  "use_system_prompt": true,
  "use_runtime_prompt": true,
  "system_prompt": null,
  "runtime_prompt": null
}
```

`null` means use the saved local default. Supplying a string overrides that layer for one request. Setting either `use_*` flag to `false` disables that layer for the request. The optional legacy `system` field adds request-specific system instructions after the aib layers.

## API

Initial endpoints:

- `GET /health` — service status, memory and Ollama connectivity.
- `GET /resources` — live local CPU/RAM/model-process resource snapshot.
- `GET /models` — configured models and their local availability/capabilities.
- `GET /prompt-config` — current/default prompt configuration and runtime variables.
- `PUT /prompt-config` — save local System/Runtime defaults.
- `DELETE /prompt-config` — reset local overrides to repository defaults.
- `GET /chat` — local browser chat UI.
- `POST /chat` — non-streaming conversational generation.
- `POST /chat/stream` — NDJSON streaming conversational generation.
- `POST /embed` — embeddings through `nomic-embed-text`.

Default model: `qwen3:4b`.

## Storage

Model binaries, local data, virtual environments and secrets are excluded from Git.

Gemini support will be added later under `gemini/`.
