"""Golden dataset generation fallback."""

from __future__ import annotations


class GoldenDatasetGenerator:
    """Generate heuristic QA pairs from business documents without LLM access."""

    async def generate(self, documents: list, count: int = 500) -> list:
        pairs = []
        for document in documents:
            title = document.get("title") or document.get("doc_title") or "未命名文档"
            snippets = document.get("snippets") or document.get("chunks") or []
            for index, snippet in enumerate(snippets[:3]):
                text = (snippet.get("content") or snippet.get("snippet") or "").strip()
                if not text:
                    continue
                pairs.append(
                    {
                        "question": f"{title} 的第 {index + 1} 段主要说明了什么？",
                        "answer": text[:200],
                        "contexts": [text],
                        "context_doc_ids": [document.get("doc_id") or document.get("id")],
                        "difficulty": "basic",
                    }
                )
                if len(pairs) >= count:
                    return pairs
        return pairs
