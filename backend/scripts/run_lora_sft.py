#!/usr/bin/env python3
"""Run local LoRA/SFT training or emit a deterministic training plan fallback."""

from __future__ import annotations

import argparse
import json
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

from app.training.local_finetune import (
    build_dataset_rows,
    build_training_plan,
    load_training_context,
    read_jsonl,
    write_training_artifacts,
    write_training_status,
)


def _resolve_target_modules(model, configured_modules: list[str]) -> list[str]:
    names = [name for name, _ in model.named_modules()]
    available = [module for module in configured_modules if any(name.endswith(module) for name in names)]
    if available:
        return available
    fallbacks = [
        ["c_attn", "c_proj"],
        ["query_key_value", "dense"],
        ["q_proj", "k_proj", "v_proj", "o_proj"],
    ]
    for candidates in fallbacks:
        selected = [module for module in candidates if any(name.endswith(module) for name in names)]
        if selected:
            return selected
    linear_like = []
    for name, module in model.named_modules():
        if module.__class__.__name__.lower() == "linear":
            tail = name.split(".")[-1]
            if tail not in linear_like:
                linear_like.append(tail)
    return linear_like[:8] or configured_modules


def _should_export_merged_model() -> bool:
    raw = os.getenv("DOCMIND_TRAINING_EXPORT_MERGED_MODEL", "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return os.getenv("DOCMIND_TRAINING_DEV_TINY_MODEL_ENABLED", "false").lower() == "true"


def _prepare_generation_config(model, tokenizer) -> None:
    pad_token_id = tokenizer.pad_token_id
    if pad_token_id is None or pad_token_id < 0:
        pad_token_id = tokenizer.eos_token_id or tokenizer.bos_token_id or 0
    model.config.pad_token_id = pad_token_id
    generation_config = getattr(model, "generation_config", None)
    if generation_config is not None:
        generation_config.pad_token_id = pad_token_id
        if generation_config.eos_token_id is None:
            generation_config.eos_token_id = tokenizer.eos_token_id or 1
        if generation_config.bos_token_id is None:
            generation_config.bos_token_id = tokenizer.bos_token_id or 0


def _train_with_transformers(context, train_rows: list[dict], val_rows: list[dict], plan: dict) -> dict:
    write_training_status(
        context,
        stage="loading_runtime",
        message="正在加载训练依赖与基础模型",
        plan=plan,
        extra={"train_records": len(train_rows), "val_records": len(val_rows)},
    )
    import torch
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        DataCollatorForLanguageModeling,
        Trainer,
        TrainingArguments,
    )

    tokenizer = AutoTokenizer.from_pretrained(context.hf_base_model, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    torch_dtype = torch.float16 if torch.cuda.is_available() else torch.bfloat16
    model = AutoModelForCausalLM.from_pretrained(
        context.hf_base_model,
        trust_remote_code=True,
        torch_dtype=torch_dtype,
        low_cpu_mem_usage=True,
        device_map="auto" if torch.cuda.is_available() else None,
    )
    model.config.use_cache = False
    write_training_status(
        context,
        stage="preparing_dataset",
        message="基础模型已加载，正在构建训练数据集",
        plan=plan,
        extra={"device": "cuda" if torch.cuda.is_available() else "cpu"},
    )

    lora_conf = plan["lora"]
    target_modules = _resolve_target_modules(model, list(lora_conf["target_modules"]))
    plan["lora"]["resolved_target_modules"] = target_modules
    peft_config = LoraConfig(
        r=int(lora_conf["r"]),
        lora_alpha=int(lora_conf["alpha"]),
        lora_dropout=float(lora_conf["dropout"]),
        target_modules=target_modules,
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, peft_config)
    if hasattr(model, "enable_input_require_grads"):
        model.enable_input_require_grads()
    model.gradient_checkpointing_enable()

    default_max_length = "64" if os.getenv("DOCMIND_TRAINING_DEV_TINY_MODEL_ENABLED", "false").lower() == "true" else "1024"
    max_length = int(os.getenv("DOCMIND_TRAINING_MAX_LENGTH", default_max_length))

    def tokenize(batch):
        encoded = tokenizer(
            batch["text"],
            truncation=True,
            max_length=max_length,
            padding="max_length",
        )
        encoded["labels"] = encoded["input_ids"].copy()
        return encoded

    train_dataset = Dataset.from_list(train_rows).map(
        tokenize,
        batched=True,
        remove_columns=["text", "doc_id", "tenant_id"],
    )
    eval_dataset = Dataset.from_list(val_rows or train_rows[:1]).map(
        tokenize,
        batched=True,
        remove_columns=["text", "doc_id", "tenant_id"],
    )

    trainer_conf = plan["trainer"]
    output_dir = context.artifact_dir / "trainer_state"
    args = TrainingArguments(
        output_dir=str(output_dir),
        overwrite_output_dir=True,
        num_train_epochs=float(trainer_conf["epochs"]),
        learning_rate=float(trainer_conf["learning_rate"]),
        max_steps=int(trainer_conf["max_steps"]),
        per_device_train_batch_size=int(trainer_conf["micro_batch_size"]),
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=int(trainer_conf["gradient_accumulation_steps"]),
        evaluation_strategy="steps" if len(eval_dataset) > 0 else "no",
        eval_steps=max(int(os.getenv("DOCMIND_TRAINING_EVAL_STEPS", "5")), 1),
        save_steps=max(int(os.getenv("DOCMIND_TRAINING_SAVE_STEPS", "5")), 1),
        save_total_limit=1,
        logging_steps=max(int(os.getenv("DOCMIND_TRAINING_LOGGING_STEPS", "1")), 1),
        gradient_checkpointing=True,
        report_to=[],
        remove_unused_columns=False,
    )

    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset if len(eval_dataset) > 0 else None,
        data_collator=DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False),
    )
    write_training_status(
        context,
        stage="training",
        message="训练已启动，正在执行 Trainer.train()",
        plan=plan,
        extra={"train_dataset_size": len(train_rows), "val_dataset_size": len(val_rows)},
    )
    trainer.train()

    adapter_dir = context.artifact_dir / "adapter"
    model.save_pretrained(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))
    write_training_status(
        context,
        stage="saving_artifacts",
        message="训练已完成，正在保存适配器产物",
        plan=plan,
        extra={"adapter_dir": str(adapter_dir)},
    )

    merged_model_dir = None
    if _should_export_merged_model():
        write_training_status(
            context,
            stage="saving_artifacts",
            message="训练已完成，正在导出可发布的完整模型产物",
            plan=plan,
            extra={"adapter_dir": str(adapter_dir), "export_mode": "merged_full_model"},
        )
        merged_model_dir = context.artifact_dir / "merged_model"
        merged_model = model.merge_and_unload()
        _prepare_generation_config(merged_model, tokenizer)
        merged_model.save_pretrained(str(merged_model_dir), safe_serialization=True, max_shard_size="2GB")
        tokenizer.save_pretrained(str(merged_model_dir))

    publish_ready = os.getenv("DOCMIND_TRAINING_PUBLISH_ENABLED", "false").lower() == "true"
    notes = "已完成本地 LoRA/SFT 训练。如需发布到 Ollama 或 vLLM，请按 Modelfile 或部署脚本继续发布。"
    return write_training_artifacts(
        context,
        plan=plan,
        executed=True,
        adapter_dir=str(adapter_dir),
        merged_model_dir=str(merged_model_dir) if merged_model_dir else None,
        notes=notes,
        publish_ready=publish_ready,
        extra_metadata={
            "device": "cuda" if torch.cuda.is_available() else "cpu",
            "train_dataset_size": len(train_rows),
            "val_dataset_size": len(val_rows),
            "publish_strategy": "full_model_import" if merged_model_dir else "adapter",
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="DocMind local LoRA/SFT training runner")
    parser.add_argument("--request-json", required=True)
    parser.add_argument("--allow-plan-fallback", action="store_true")
    args = parser.parse_args()

    context = load_training_context(args.request_json)
    train_records = read_jsonl(context.train_path)
    val_records = read_jsonl(context.val_path)
    train_rows = build_dataset_rows(train_records)
    val_rows = build_dataset_rows(val_records)
    plan = build_training_plan(context, train_rows, val_rows)
    trainer_conf = plan.get("trainer") or {}
    max_train_samples = int(trainer_conf.get("max_train_samples") or 0)
    max_val_samples = int(trainer_conf.get("max_val_samples") or 0)
    if max_train_samples > 0:
        train_rows = train_rows[:max_train_samples]
    if max_val_samples > 0:
        val_rows = val_rows[:max_val_samples]
    plan["train_records"] = len(train_rows)
    plan["val_records"] = len(val_rows)
    write_training_status(
        context,
        stage="prepared",
        message="训练计划已生成，准备执行 LoRA/SFT",
        plan=plan,
        extra={"train_records": len(train_rows), "val_records": len(val_rows)},
    )

    if not train_rows:
        raise RuntimeError("训练集为空，无法执行 LoRA/SFT")

    try:
        result = _train_with_transformers(context, train_rows, val_rows, plan)
    except Exception as exc:  # noqa: BLE001
        write_training_status(
            context,
            stage="failed" if not args.allow_plan_fallback else "fallback",
            message=f"训练执行异常: {type(exc).__name__}: {exc}",
            plan=plan,
        )
        if not args.allow_plan_fallback:
            raise
        result = write_training_artifacts(
            context,
            plan=plan,
            executed=False,
            adapter_dir=None,
            merged_model_dir=None,
            notes=f"未执行真实训练，已输出训练计划。原因: {type(exc).__name__}: {exc}",
            publish_ready=False,
            extra_metadata={
                "fallback_reason": f"{type(exc).__name__}: {exc}",
                "train_dataset_size": len(train_rows),
                "val_dataset_size": len(val_rows),
            },
        )
    else:
        write_training_status(
            context,
            stage="completed",
            message="训练执行完成，已生成训练结果",
            plan=plan,
            extra={
                "artifact_dir": result.get("artifact_dir"),
                "adapter_dir": result.get("adapter_dir"),
                "merged_model_dir": result.get("merged_model_dir"),
            },
        )

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
