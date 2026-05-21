# Ollama Gateway

A self-hosted LLM stack with API key authentication, autocomplete support, and an operational dashboard. Built and tested on an **NVIDIA RTX 4090 (24 GB)**.

```
Client ──► proxy:21434  (API key auth) ──► ollama:11434
Browser ──► dashboard:21435  (password auth) ──► ollama:11434
                                             └──► proxy_data (SQLite)
```

## Requirements

- Docker + Docker Compose
- NVIDIA GPU with the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) installed

---

## Services

| Service | Port | Description |
|---|---|---|
| `ollama` | — (internal) | Ollama inference server |
| `proxy` | `21434` | API key–authenticated reverse proxy |
| `dashboard` | `21435` | Password-protected OE dashboard |

---

## Models

| Role | Env var | Configured in `.env` |
|---|---|---|
| Main (chat / generation) | `OLLAMA_MODEL` | `gemma4:31b-it-q4_K_M` |
| Autocomplete | `AUTOCOMPLETE_MODEL` | `qwen2.5-coder:1.5b` |

Both models are pulled automatically on first start. Both `OLLAMA_MODEL` and `AUTOCOMPLETE_MODEL` are **required** — the stack will not start without them.

---

## Setup

### 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env` — all four variables are required:

```env
ADMIN_KEY=change-me-to-a-strong-secret          # proxy API key management
DASHBOARD_PASSWORD=change-me-to-a-strong-secret  # OE dashboard login
OLLAMA_MODEL=gemma4:31b-it-q4_K_M               # main chat/generation model
AUTOCOMPLETE_MODEL=qwen2.5-coder:1.5b           # autocomplete model
```

### 2. Start the stack

```bash
docker compose up -d --build
```

The first start pulls both model weights, which may take a while. Monitor progress with:

```bash
docker compose logs -f ollama
```

### 3. Switch models

Update `OLLAMA_MODEL` or `AUTOCOMPLETE_MODEL` in `.env`, then restart the Ollama service:

```bash
docker compose restart ollama
```

Model weights are cached in the `ollama` Docker volume, so only new models are downloaded.

---

## Managing API Keys

All key management requires the `ADMIN_KEY` from `.env`.

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

Pass your API key as a `Bearer` token on every request. The proxy forwards all standard Ollama routes.

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

### Autocomplete — `POST /v1/completions`

Routes automatically to `AUTOCOMPLETE_MODEL`. Supports fill-in-the-middle (FIM) via the `suffix` field.

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

## OE Dashboard

A password-protected operational dashboard at `http://your-host:21435`.

### Login

Enter the `DASHBOARD_PASSWORD` from your `.env`.

### Features

| Section | Details |
|---|---|
| GPU utilization | Real-time utilization %, VRAM used/total, temperature, power draw — auto-refreshes every 5 s |
| System RAM | Used / total with percentage bar |
| Token usage | Per-model prompt + completion token counts with a last-7-days bar chart |
| Model list | All installed models with file size and a delete button |
| Pull model | Download any model from [ollama.com/library](https://ollama.com/library) |
| Configure model | Derive a new model with custom `num_ctx`, `num_gpu`, and `temperature` via Modelfile |

Token usage is recorded automatically for every `/api/generate`, `/api/chat`, and `/v1/completions` request that passes through the proxy.

---

## Project Structure

```
.
├── .env.example
├── docker-compose.yml
├── ollama/
│   ├── Dockerfile          # extends ollama/ollama, installs curl
│   └── entrypoint.sh       # pulls OLLAMA_MODEL + AUTOCOMPLETE_MODEL on boot
├── proxy/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── main.py             # API key auth, /v1/completions, token usage tracking
└── dashboard/
    ├── Dockerfile
    ├── requirements.txt
    ├── main.py             # GPU/RAM stats (pynvml/psutil), usage queries, model management
    └── index.html          # single-page dashboard UI
```

---

## Integrations

See **[INTEGRATIONS.md](./INTEGRATIONS.md)** for step-by-step guides on connecting external tools to the gateway:

- [Pi coding agent (pi.dev)](./INTEGRATIONS.md#pi-coding-agent--pidev) — terminal AI coding agent
- [VS Code — Continue.dev](./INTEGRATIONS.md#vs-code--continuedev) — inline chat + tab autocomplete
- [Python — OpenAI SDK](./INTEGRATIONS.md#python--openai-sdk)
- [Python — LangChain](./INTEGRATIONS.md#python--langchain)
- [Python — LlamaIndex](./INTEGRATIONS.md#python--llamaindex)

---

## Stopping the stack

```bash
docker compose down
```

To wipe everything including model weights and the key database:

```bash
docker compose down -v
```
