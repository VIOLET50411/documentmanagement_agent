#!/usr/bin/env python3
"""Warm the HuggingFace cache for the configured training base model."""

from __future__ import annotations

import os
import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
APP_ROOT = CURRENT_DIR.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", os.getenv("DOCMIND_HF_DOWNLOAD_TIMEOUT", "120"))
os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", os.getenv("DOCMIND_HF_ETAG_TIMEOUT", "120"))
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

from transformers import AutoModelForCausalLM, AutoTokenizer

from app.training.local_finetune import resolve_hf_base_model


def main() -> None:
    base_model = os.getenv("DOCMIND_TRAINING_BASE_MODEL", "tinyllama").strip()
    hf_base_model = resolve_hf_base_model(base_model)
    print(f"warming tokenizer: {hf_base_model}", flush=True)
    AutoTokenizer.from_pretrained(hf_base_model, trust_remote_code=True)
    print(f"warming model: {hf_base_model}", flush=True)
    AutoModelForCausalLM.from_pretrained(hf_base_model, trust_remote_code=True, low_cpu_mem_usage=True)
    print("warmup-complete", flush=True)


if __name__ == "__main__":
    main()
