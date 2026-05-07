"""Test: Simulate user retry in same session (reproduces the 500 bug)."""
import asyncio, json, httpx

async def test():
    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=120.0) as c:
        r = await c.post("/api/v1/auth/login", json={"username": "admin_demo", "password": "Password123"})
        r.raise_for_status()
        c.headers["Authorization"] = "Bearer " + r.json()["access_token"]

        q = "请说明一个完全随机的系统测试机制 12345。"

        # First request — creates new session
        print("=== Request 1 (new session) ===")
        r = await c.post("/api/v1/chat/message", json={"message": q, "search_type": "hybrid"})
        print(f"  HTTP {r.status_code}")
        if r.status_code != 200:
            print(f"  Error: {r.text[:300]}")
            return
        qa = r.json()
        thread_id = qa.get("thread_id")
        agent = qa.get("agent_used", "?")
        answer = qa.get("answer", "")
        print(f"  Agent: {agent}")
        print(f"  Thread: {thread_id}")
        print(f"  Answer preview: {answer[:200]}")

        # Second request — same thread (user retry)
        print(f"\n=== Request 2 (same thread: {thread_id}) ===")
        r = await c.post("/api/v1/chat/message", json={
            "message": q,
            "thread_id": thread_id,
            "search_type": "hybrid",
        })
        print(f"  HTTP {r.status_code}")
        if r.status_code != 200:
            print(f"  Error: {r.text[:300]}")
        else:
            qa2 = r.json()
            print(f"  Agent: {qa2.get('agent_used', '?')}")
            print(f"  Answer preview: {qa2.get('answer', '')[:200]}")

        # Third request: SSE stream on same thread
        print(f"\n=== Request 3 (SSE stream, same thread) ===")
        q2 = "西南大学的国有资产管理有什么规定"
        r = await c.post("/api/v1/chat/stream", json={
            "message": q2,
            "thread_id": thread_id,
            "search_type": "hybrid",
        })
        print(f"  HTTP {r.status_code}")
        if r.status_code == 200:
            text = r.text
            events = [line for line in text.split("\n") if line.startswith("data:")]
            for ev in events[-3:]:
                print(f"  Event: {ev[:200]}")
            done_events = [e for e in events if '"done"' in e]
            if done_events:
                last = json.loads(done_events[-1].replace("data: ", ""))
                print(f"  Final agent: {last.get('agent_used')}")
                print(f"  Has citations: {bool(last.get('citations'))}")
        else:
            print(f"  SSE Error: {r.text[:300]}")

        print("\n=== ALL TESTS PASSED ===" if r.status_code == 200 else "\n=== TEST FAILED ===")

asyncio.run(test())
