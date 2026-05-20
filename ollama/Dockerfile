FROM ollama/ollama

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV OLLAMA_MODEL=gemma4:31b-it-q4_K_M

ENTRYPOINT ["/entrypoint.sh"]
