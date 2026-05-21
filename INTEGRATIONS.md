# LLM Gateway — Integration Guide

Connect external tools and frameworks to the Ollama gateway running on your host.

## Endpoint reference

| Use | Method + URL | Notes |
|---|---|---|
| Chat | `POST :21434/v1/chat/completions` | OpenAI-compatible |
| Chat (Ollama native) | `POST :21434/api/chat` | Ollama format |
| Generate | `POST :21434/api/generate` | Ollama format |
| Autocomplete (FIM) | `POST :21434/v1/completions` | Always uses `AUTOCOMPLETE_MODEL` |
| List models | `GET  :21434/v1/models` | OpenAI-compatible |

All requests require `Authorization: Bearer <api-key>`. Get a key from the proxy admin:

```bash
curl -X POST "http://your-host:21434/admin/keys?name=my-tool" \
  -H "Authorization: Bearer <ADMIN_KEY>"
# → { "key": "ollama-a3f9c2d1...", "name": "my-tool" }
```

Replace `your-host` with your server IP/hostname, or `localhost` if running locally.

---

## Pi coding agent — [pi.dev](https://pi.dev)

Pi is a terminal-based coding agent (similar to Claude Code) that supports any OpenAI-compatible endpoint.

### Install

```bash
npm install -g @mariozechner/pi-coding-agent
```

### Configure — config file

Create `~/.pi/models.json` and add a custom provider entry:

```json
{
  "providers": [
    {
      "type": "openai",
      "baseUrl": "http://your-host:21434/v1",
      "apiKey": "ollama-<your-key>",
      "models": ["gemma4:31b-it-q4_K_M"]
    }
  ],
  "defaultModel": "gemma4:31b-it-q4_K_M"
}
```

### Configure — environment variables

```bash
export OPENAI_BASE_URL=http://your-host:21434/v1
export OPENAI_API_KEY=ollama-<your-key>
pi --model gemma4:31b-it-q4_K_M
```

> Ollama models do not use the OpenAI developer role. If pi sends a `developer` system message and the model ignores it, set `"compat": { "supportsDeveloperRole": false }` in your provider config.

See the [pi custom provider docs](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/custom-provider.md) for the full config reference.

---

## VS Code — Continue.dev

Continue provides an inline chat panel and tab autocomplete inside VS Code (and JetBrains).

### Install

Install the [Continue extension](https://marketplace.visualstudio.com/items?itemName=Continue.continue) from the VS Code marketplace.

### Configure

Edit `~/.continue/config.json`:

```json
{
  "models": [
    {
      "title": "Gemma 4 31B",
      "provider": "openai",
      "model": "gemma4:31b-it-q4_K_M",
      "apiBase": "http://your-host:21434",
      "apiKey": "ollama-<your-key>"
    }
  ],
  "tabAutocompleteModel": {
    "title": "qwen2.5-coder 1.5B",
    "provider": "openai",
    "model": "qwen2.5-coder:1.5b",
    "apiBase": "http://your-host:21434",
    "apiKey": "ollama-<your-key>"
  }
}
```

The `tabAutocompleteModel` block sends requests to `/v1/completions`, which the proxy always routes to `AUTOCOMPLETE_MODEL` — so the `model` field here is display-only.

---

## Python — OpenAI SDK

The OpenAI Python SDK accepts a custom `base_url`, making it directly compatible with the gateway.

### Chat

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://your-host:21434/v1",
    api_key="ollama-<your-key>",
)

response = client.chat.completions.create(
    model="gemma4:31b-it-q4_K_M",
    messages=[{"role": "user", "content": "Explain RLHF in one paragraph."}],
)
print(response.choices[0].message.content)
```

### Streaming chat

```python
with client.chat.completions.stream(
    model="gemma4:31b-it-q4_K_M",
    messages=[{"role": "user", "content": "Write a haiku about GPUs."}],
) as stream:
    for text in stream.text_stream:
        print(text, end="", flush=True)
```

### Autocomplete (FIM)

```python
response = client.completions.create(
    model="qwen2.5-coder:1.5b",   # proxy ignores this; always uses AUTOCOMPLETE_MODEL
    prompt="def fibonacci(n):",
    suffix="\n    return result",
    max_tokens=128,
    temperature=0.2,
)
print(response.choices[0].text)
```

---

## Python — LangChain

```python
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

llm = ChatOpenAI(
    base_url="http://your-host:21434/v1",
    api_key="ollama-<your-key>",
    model="gemma4:31b-it-q4_K_M",
    temperature=0.7,
)

messages = [
    SystemMessage(content="You are a helpful coding assistant."),
    HumanMessage(content="What is the difference between a process and a thread?"),
]
response = llm.invoke(messages)
print(response.content)
```

### Streaming

```python
for chunk in llm.stream(messages):
    print(chunk.content, end="", flush=True)
```

### Building a chain

```python
from langchain_core.prompts import ChatPromptTemplate

prompt = ChatPromptTemplate.from_messages([
    ("system", "Answer concisely in {language}."),
    ("user", "{question}"),
])
chain = prompt | llm

result = chain.invoke({"language": "English", "question": "What is a transformer?"})
print(result.content)
```

---

## Python — LlamaIndex

```python
from llama_index.llms.openai_like import OpenAILike
from llama_index.core.llms import ChatMessage

llm = OpenAILike(
    model="gemma4:31b-it-q4_K_M",
    api_base="http://your-host:21434/v1",
    api_key="ollama-<your-key>",
    is_chat_model=True,
    context_window=32768,
)

response = llm.chat([
    ChatMessage(role="user", content="Summarise the attention mechanism.")
])
print(response.message.content)
```

### As a RAG query engine

```python
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader
from llama_index.core import Settings

Settings.llm = llm

documents = SimpleDirectoryReader("./docs").load_data()
index = VectorStoreIndex.from_documents(documents)
engine = index.as_query_engine()

response = engine.query("What does the codebase do?")
print(response)
```

---

## Quick reference

| Tool | Base URL | API key field |
|---|---|---|
| Pi coding agent | `http://your-host:21434/v1` | `apiKey` in config / `OPENAI_API_KEY` env |
| Continue.dev | `http://your-host:21434` | `apiKey` in config.json |
| OpenAI SDK | `http://your-host:21434/v1` | `api_key` kwarg |
| LangChain | `http://your-host:21434/v1` | `api_key` kwarg |
| LlamaIndex | `http://your-host:21434/v1` | `api_key` kwarg |
