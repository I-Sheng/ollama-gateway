# Ollama Access Control Proxy

A reverse proxy that adds API key authentication in front of a self-hosted Ollama instance. Ollama is never exposed directly — all traffic goes through the proxy.

```
Client → proxy:21434 (API key check) → ollama:11434
```

## Requirements

- Docker + Docker Compose
- NVIDIA GPU with the NVIDIA Container Toolkit installed

---

## Setup

### 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
ADMIN_KEY=change-me-to-a-strong-secret   # used to manage API keys
OLLAMA_MODEL=gemma4:31b-it-q4_K_M        # model to pull on startup
```

### 2. Change the model

Set `OLLAMA_MODEL` in your `.env` file to any model available on [ollama.com/library](https://ollama.com/library):

```env
OLLAMA_MODEL=llama3.2:latest
OLLAMA_MODEL=mistral:7b
OLLAMA_MODEL=gemma4:31b-it-q4_K_M
```

The model is pulled automatically the first time the container starts. Subsequent restarts skip the download if the model is already present in the volume.

To switch to a different model, update `OLLAMA_MODEL` in `.env` and restart:

```bash
docker compose restart ollama
```

### 3. Start the stack

```bash
docker compose up -d --build
```

The first start will take a while — it needs to pull the model weights. Check progress with:

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

Pass your API key as a Bearer token on every request. The proxy forwards all standard Ollama API routes.

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

---

## Project Structure

```
ollama/
├── .env.example            # environment variable template
├── docker-compose.yml
├── ollama/
│   ├── Dockerfile          # extends ollama/ollama, auto-pulls model on boot
│   └── entrypoint.sh
└── proxy/
    ├── Dockerfile
    ├── requirements.txt
    └── main.py             # FastAPI proxy with API key auth + admin endpoints
```

---

## Stopping the stack

```bash
docker compose down
```

Model weights are stored in the `ollama` Docker volume and survive restarts. To wipe everything including the model:

```bash
docker compose down -v
```
