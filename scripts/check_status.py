"""Check full system status for DocMind full-scale build."""
import asyncio
import json
import httpx

BASE = "http://localhost:8000"

async def main():
    async with httpx.AsyncClient(base_url=BASE, timeout=30.0) as c:
        r = await c.post("/api/v1/auth/login", json={"username": "admin_demo", "password": "Password123"})
        r.raise_for_status()
        c.headers["Authorization"] = "Bearer " + r.json()["access_token"]

        # 1. Documents
        r = await c.get("/api/v1/documents/", params={"page": 1, "size": 1})
        total = r.json().get("total", 0)
        print(f"[1] Documents in system: {total}")

        # 2. Training jobs
        r = await c.get("/api/v1/admin/llm/training/jobs")
        raw = r.json()
        jobs = raw.get("items", raw) if isinstance(raw, dict) else raw
        print(f"[2] Training jobs: {len(jobs)}")
        for j in (jobs if isinstance(jobs, list) else []):
            jid = str(j.get("id", ""))[:8]
            status = j.get("status", "?")
            stage = j.get("stage", "?")
            model = j.get("target_model_name", "?")
            err = str(j.get("error_message") or "")[:100]
            mid = str(j.get("activated_model_id") or "")[:8]
            print(f"    {jid} | {status:10s} | {stage:12s} | {model} | model_id={mid} | err={err}")

        # 3. Models
        r = await c.get("/api/v1/admin/llm/training/models")
        raw = r.json()
        models = raw.get("items", raw) if isinstance(raw, dict) else raw
        print(f"[3] Registered models: {len(models)}")
        for m in (models if isinstance(models, list) else []):
            mid = str(m.get("id", ""))[:8]
            name = m.get("model_name", "?")
            active = m.get("is_active", False)
            st = m.get("status", "?")
            print(f"    {mid} | active={active:5s} | status={st:12s} | {name}")

        # 4. Evaluation
        r = await c.get("/api/v1/admin/evaluation/latest")
        ev = r.json() if r.status_code == 200 else {}
        if ev.get("exists"):
            metrics = ev.get("metrics", {})
            gate = ev.get("gate", {})
            gen = ev.get("generated_at", "")[:19]
            print(f"[4] Latest eval: gate_passed={gate.get('passed')}, generated={gen}")
            print(f"    faithfulness={metrics.get('faithfulness')}")
            print(f"    answer_relevancy={metrics.get('answer_relevancy')}")
            print(f"    context_precision={metrics.get('context_precision')}")
            print(f"    context_recall={metrics.get('context_recall')}")
            print(f"    mode={metrics.get('_meta', {}).get('mode')}")
        else:
            print("[4] No evaluation report found")

        # 5. Ollama models
        print("[5] Ollama models:")
        try:
            r2 = await c.get("http://localhost:11434/api/tags")
            for m in r2.json().get("models", []):
                print(f"    {m['name']:50s} {m.get('size', 0) / 1e9:.1f}GB")
        except Exception:
            print("    (cannot reach ollama directly, checking via docker)")

asyncio.run(main())
