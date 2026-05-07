"""Test garbled output fix."""
import asyncio, json, httpx

async def test():
    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=120.0) as c:
        r = await c.post("/api/v1/auth/login", json={"username": "admin_demo", "password": "Password123"})
        r.raise_for_status()
        c.headers["Authorization"] = "Bearer " + r.json()["access_token"]

        questions = [
            "请总结当前差旅制度的审批链路，并说明各角色职责。",
            "西南大学固定资产报废流程是什么",
            "企业采购超过五万元需要哪些审批",
        ]
        for q in questions:
            print(f"\nQ: {q}")
            r = await c.post("/api/v1/chat/message", json={"message": q, "search_type": "hybrid"})
            r.raise_for_status()
            qa = r.json()
            agent = qa.get("agent_used", "?")
            answer = qa.get("answer", "")
            cites = len(qa.get("citations", []))
            
            # Check quality
            cleaned = answer.replace(" ", "").replace("\n", "").replace("\r", "")
            total = len(cleaned)
            chinese_chars = sum(1 for ch in cleaned if "\u4e00" <= ch <= "\u9fff")
            ratio = chinese_chars / total if total > 0 else 0
            is_garbled = ratio < 0.15

            print(f"Agent: {agent}")
            print(f"Citations: {cites}")
            print(f"Answer length: {len(answer)} chars")
            print(f"Chinese ratio: {ratio:.2%}")
            if is_garbled:
                print("WARNING: Output appears garbled!")
                print(f"Preview: {answer[:200]}")
            else:
                print(f"OK - Preview: {answer[:300]}")

asyncio.run(test())
