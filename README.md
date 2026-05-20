# Ollama Access Control Proxy

A reverse proxy that adds API key authentication in front of a self-hosted Ollama instance. Ollama is never exposed directly — all traffic goes through the proxy.

```
Client → proxy:21434 (API key check) → ollama:11434
```

Built and tested on an **NVIDIA RTX 4090 (24 GB)**.

## Requirements

- Docker + Docker Compose
- NVIDIA GPU with the NVIDIA Container Toolkit installed

---

## Models

| Role | Default model | Env var |
|---|---|---|
| Main (chat / generation) | `gemma4:31b-it-q4_K_M` | `OLLAMA_MODEL` |
| Autocomplete | `qwen2.5-coder:1.5b` | `AUTOCOMPLETE_MODEL` |

Both models are pulled automatically on first start. Subsequent restarts skip the download if the model weights are already present in the volume.

---

## Setup

### 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
ADMIN_KEY=change-me-to-a-strong-secret        # proxy API key management
DASHBOARD_PASSWORD=change-me-to-a-strong-secret  # OE dashboard login
OLLAMA_MODEL=gemma4:31b-it-q4_K_M             # main chat model
AUTOCOMPLETE_MODEL=qwen2.5-coder:1.5b         # autocomplete model
```

### 2. Change models

Set `OLLAMA_MODEL` or `AUTOCOMPLETE_MODEL` in your `.env` to any model on [ollama.com/library](https://ollama.com/library). Both variables are optional — the defaults above are used if omitted.

To switch models, update `.env` and restart:

```bash
docker compose restart ollama
```

### 3. Start the stack

```bash
docker compose up -d --build
```

The first start will take a while — it needs to pull both model weights. Check progress with:

```bash
docker compose logs -f ollama
```

---

## Managing API Keys

All key management requires your `ADMIN_KEY` from `.env`.

### Create a key

```bash
curl -X POST "http://localhost:21434/admin/keys?name=my-app" \
  -H "Authorization: Bearer <ADMIN_KEY>"
```

Response:

```json
{ "key": "ollama-a3f9c2d1...", "name": "my-app" }
```

### List all keys

```bash
curl http://localhost:21434/admin/keys \
  -H "Authorization: Bearer <ADMIN_KEY>"
```

### Revoke a key

```bash
curl -X DELETE "http://localhost:21434/admin/keys/ollama-a3f9c2d1..." \
  -H "Authorization: Bearer <ADMIN_KEY>"
```

---

## Using the API

Pass your API key as a Bearer token on every request.

### List available models

```bash
curl http://localhost:21434/api/tags \
  -H "Authorization: Bearer ollama-a3f9c2d1..."
```

### Generate (streaming)

```bash
curl http://localhost:21434/api/generate \
  -H "Authorization: Bearer ollama-a3f9c2d1..." \
  -d '{
    "model": "gemma4:31b-it-q4_K_M",
    "prompt": "Why is the sky blue?"
  }'
```

### Chat

```bash
curl http://localhost:21434/api/chat \
  -H "Authorization: Bearer ollama-a3f9c2d1..." \
  -d '{
    "model": "gemma4:31b-it-q4_K_M",
    "messages": [{ "role": "user", "content": "Hello!" }]
  }'
```

### Autocomplete (OpenAI-compatible)

`POST /v1/completions` always routes to `AUTOCOMPLETE_MODEL`. Supports fill-in-the-middle (FIM) via the `suffix` field.

```bash
curl http://localhost:21434/v1/completions \
  -H "Authorization: Bearer ollama-a3f9c2d1..." \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "def fibonacci(n):",
    "suffix": "\n    return result",
    "max_tokens": 128,
    "temperature": 0.2,
    "stream": false
  }'
```

Response:

```json
{
  "id": "cmpl-...",
  "object": "text_completion",
  "created": 1234567890,
  "model": "qwen2.5-coder:1.5b",
  "choices": [{ "text": "...", "index": 0, "finish_reason": "stop" }]
}
```

#### Continue.dev configuration

```json
{
  "tabAutocompleteModel": {
    "title": "qwen2.5-coder",
    "provider": "openai",
    "model": "qwen2.5-coder:1.5b",
    "apiBase": "http://your-host:21434",
    "apiKey": "ollama-<your-key>"
  }
}
```

---

---

## OE Dashboard

A password-protected operational dashboard served at `http://your-host:21435`.

### Features

| Section | Details |
|---|---|
| GPU utilization | Real-time utilization %, VRAM used/total, temperature, power draw |
| System RAM | Used / total with percentage bar |
| Token usage | Per-model prompt + completion token counts, last-7-days bar chart |
| Model list | All installed models with size, delete button |
| Pull model | Download any model from ollama.com/library |
| Configure model | Create a derived model with custom `num_ctx`, `num_gpu`, `temperature` via Modelfile |

Stats auto-refresh every 5 seconds. Token usage is tracked automatically for all `/api/generate`, `/api/chat`, and `/v1/completions` requests through the proxy.

### Login

Open `http://your-host:21435` in a browser and enter the `DASHBOARD_PASSWORD` from your `.env`.

---

## Project Structure

```
ollama/
├── .env.example            # environment variable template
├── docker-compose.yml
├── ollama/
│   ├── Dockerfile          # extends ollama/ollama, auto-pulls models on boot
│   └── entrypoint.sh       # pulls OLLAMA_MODEL + AUTOCOMPLETE_MODEL
├── proxy/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── main.py             # FastAPI proxy: API key auth, /v1/completions, token tracking
└── dashboard/
    ├── Dockerfile
    ├── requirements.txt
    ├── main.py             # FastAPI: GPU/RAM stats, usage API, model management, session auth
    └── index.html          # single-page dashboard UI
```

---

## Stopping the stack

```bash
docker compose down
```

Model weights are stored in the `ollama` Docker volume and survive restarts. To wipe everything including the model weights:

```bash
docker compose down -v
```
