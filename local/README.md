# local

Local model layer for `aib`.

## Model storage

After the repository is cloned to `J:\dv\aib`, Ollama model data is stored in:

```text
J:\dv\aib\local\models
```

The `models/` directory is created automatically and is ignored by Git.

## Initial models

- `qwen3:4b` — fast/default text model.
- `qwen3:8b` — higher-quality text model.
- `gemma3:4b` — text + image-capable model.
- `nomic-embed-text` — embeddings.

The authoritative list used by the setup script is `models.txt`.

## Commands

Initial setup:

```powershell
powershell -ExecutionPolicy Bypass -File .\local\setup.ps1
```

Start Ollama if needed and run the `aib` API:

```powershell
powershell -ExecutionPolicy Bypass -File .\local\start.ps1
```

Show installed models and local storage usage:

```powershell
powershell -ExecutionPolicy Bypass -File .\local\status.ps1
```
