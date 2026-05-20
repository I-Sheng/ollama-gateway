#!/bin/bash
set -e

# Start Ollama server in the background
ollama serve &
OLLAMA_PID=$!

# Wait until the server is ready
echo "Waiting for Ollama to start..."
until curl -sf http://localhost:11434/api/tags > /dev/null; do
  sleep 1
done
echo "Ollama is up."

pull_model() {
  local model="$1"
  if ! ollama list | grep -q "$model"; then
    echo "Pulling $model ..."
    ollama pull "$model"
    echo "$model ready."
  else
    echo "$model already present."
  fi
}

if [ -z "$OLLAMA_MODEL" ]; then
  echo "Error: OLLAMA_MODEL is not set" >&2; exit 1
fi
if [ -z "$AUTOCOMPLETE_MODEL" ]; then
  echo "Error: AUTOCOMPLETE_MODEL is not set" >&2; exit 1
fi

pull_model "$OLLAMA_MODEL"
pull_model "$AUTOCOMPLETE_MODEL"

# Hand off to the Ollama server process
wait $OLLAMA_PID
