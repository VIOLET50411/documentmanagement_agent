#!/usr/bin/env bash
set -euo pipefail

echo "[docmind] checking ollama cli..."
if ! command -v ollama >/dev/null 2>&1; then
  echo "[docmind] ollama is not installed or not in PATH"
  exit 1
fi

echo "[docmind] pulling chat model: qwen2.5:1.5b"
ollama pull qwen2.5:1.5b

echo "[docmind] pulling embedding model: nomic-embed-text"
ollama pull nomic-embed-text

echo "[docmind] done. installed models:"
ollama list
