# aib

Local backend for AI models.

`aib` provides one local HTTP API for applications that need access to local LLMs. The repository is intended to be cloned to `J:\dv\aib` on Windows. Large model files are stored locally and are never committed to GitHub.

## Structure

```text
aib/
├─ api/       HTTP API
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
3. restarts Ollama with that model-storage path;
4. creates a Python virtual environment and installs API dependencies;
5. downloads the initial local models.

If Ollama is not installed, the script prints the Windows install command and stops. Run it again after installing Ollama.

Start `aib`:

```powershell
powershell -ExecutionPolicy Bypass -File .\local\start.ps1
```

Check:

```text
http://127.0.0.1:8181/health
http://127.0.0.1:8181/models
http://127.0.0.1:8181/docs
```

## API

Initial endpoints:

- `GET /health` — service status and Ollama connectivity.
- `GET /models` — configured models and their local availability.
- `POST /chat` — text generation through a selected local model.
- `POST /embed` — embeddings through `nomic-embed-text`.

Default model: `qwen3:4b`.

## Storage

Model binaries, local data, virtual environments and secrets are excluded from Git.

Gemini support will be added later under `gemini/`.
