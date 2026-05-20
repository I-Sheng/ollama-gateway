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

# Pull the model if not already present
MODEL="${OLLAMA_MODEL:-gemma4:31b-it-q4_K_M}"
if ! ollama list | grep -q "$MODEL"; then
  echo "Pulling $MODEL ..."
  ollama pull "$MODEL"
  echo "Model ready."
else
  echo "Model $MODEL already present."
fi

# Hand off to the Ollama server process
wait $OLLAMA_PID
