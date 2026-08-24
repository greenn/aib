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
- conversational history for the current browser tab;
- new-chat reset;
- response wall time;
- model load time;
- generation time;
- tokens per second;
- current system RAM usage.

## API

Initial endpoints:

- `GET /health` — service status, memory and Ollama connectivity.
- `GET /models` — configured models and their local availability.
- `GET /chat` — local browser chat UI.
- `POST /chat` — conversational text generation through a selected local model.
- `POST /embed` — embeddings through `nomic-embed-text`.

Default model: `qwen3:4b`.

## Storage

Model binaries, local data, virtual environments and secrets are excluded from Git.

Gemini support will be added later under `gemini/`.
