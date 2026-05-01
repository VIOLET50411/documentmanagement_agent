#!/bin/sh
set -eu

if [ "${LLM_TRAINING_PUBLISH_ENABLED:-false}" = "true" ] && ! command -v ollama >/dev/null 2>&1; then
  if [ -f /app/bin/ollama ]; then
    chmod +x /app/bin/ollama || true
    cp /app/bin/ollama /usr/local/bin/ollama
    chmod +x /usr/local/bin/ollama || true
  else
    echo "[bootstrap] Warning: ollama CLI is unavailable; training publish may fail." >&2
  fi
fi

exec "$@"
