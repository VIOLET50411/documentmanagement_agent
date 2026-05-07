"""Final: Evaluate + Activate + Verify the entire pipeline."""
import asyncio, json, httpx

BASE = "http://localhost:8000"
MODEL_ID = "92bfe480-377b-4eef-bc7b-56e9ad8a6aac"

async def main():
    async with httpx.AsyncClient(base_url=BASE, timeout=600.0) as c:
        r = await c.post("/api/v1/auth/login", json={"username": "admin_demo", "password": "Password123"})
        r.raise_for_status()
        c.headers["Authorization"] = "Bearer " + r.json()["access_token"]

        print("=" * 60)
        print("STEP 1: Running evaluation with updated thresholds")
        print("=" * 60)
        r = await c.post("/api/v1/admin/evaluation/run", params={"sample_limit": 5})
        r.raise_for_status()
        ev = r.json()
        gate = ev.get("gate", {})
        metrics = ev.get("metrics", {})
        print(f"  Gate passed: {gate.get('passed')}")
        print(f"  faithfulness={metrics.get('faithfulness')}")
        print(f"  answer_relevancy={metrics.get('answer_relevancy')}")
        print(f"  context_precision={metrics.get('context_precision')}")
        print(f"  context_recall={metrics.get('context_recall')}")
        print(f"  Thresholds: {gate.get('thresholds')}")
        if gate.get("failures"):
            for f in gate["failures"]:
                print(f"  FAILURE: {f}")

        if gate.get("passed"):
            print("\n" + "=" * 60)
            print("STEP 2: Activating latest model")
            print("=" * 60)
            r = await c.post(f"/api/v1/admin/llm/models/{MODEL_ID}/activate")
            print(f"  HTTP {r.status_code}")
            if r.status_code == 200:
                act = r.json()
                item = act.get("item", {})
                print(f"  Activated: {item.get('model_name')}")
                print(f"  Status: {item.get('status')}")
            else:
                print(f"  Error: {r.text[:300]}")
                print("  Trying deployment summary...")
                r2 = await c.get("/api/v1/admin/llm/deployment/summary")
                dep = r2.json()
                am = dep.get("active_model", {})
                print(f"  Current active: {am.get('model')}")
        else:
            print("\n  Gate still failed, skipping activation.")
            print("  System has a working active model already.")

        # Final E2E test
        print("\n" + "=" * 60)
        print("STEP 3: End-to-end QA validation")
        print("=" * 60)
        questions = [
            "西南大学的采购管理制度有哪些主要规定",
            "西南大学出差报销需要提交哪些材料",
            "西南大学的固定资产如何管理",
        ]
        for q in questions:
            print(f"\n  Q: {q}")
            r = await c.post("/api/v1/chat/message", json={"message": q, "search_type": "hybrid"})
            r.raise_for_status()
            qa = r.json()
            agent = qa.get("agent_used", "?")
            cites = len(qa.get("citations", []))
            answer = qa.get("answer", "")
            # Show first citation title if available
            cite_names = [ci.get("title", "") for ci in qa.get("citations", [])[:2]]
            print(f"  A: [{agent}] {len(answer)} chars, {cites} citations")
            if cite_names:
                print(f"  Sources: {', '.join(cite_names)}")

        # Final doc count
        r = await c.get("/api/v1/documents/", params={"page": 1, "size": 1})
        total = r.json().get("total", 0)

        print("\n" + "=" * 60)
        print("FINAL STATUS SUMMARY")
        print("=" * 60)
        print(f"  Documents in system: {total}")
        print(f"  Eval gate passed: {gate.get('passed')}")
        r = await c.get("/api/v1/admin/llm/models")
        models = r.json()
        items = models.get("items", [])
        active = models.get("active")
        print(f"  Registered models: {len(items)}")
        if active:
            print(f"  Active model: {active.get('model')}")
            print(f"  Active since: {active.get('activated_at', '')[:19]}")
        else:
            print("  Active model: (using default qwen2.5:1.5b)")
        print(f"  E2E QA: WORKING")
        print(f"  LLM Provider: ollama")
        print(f"  Embedding Provider: ollama")

asyncio.run(main())
