"""Chat API with SSE streaming and persistent session/message records."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.middleware.auth import get_current_user
from app.api.middleware.rate_limit import rate_limit_check
from app.config import settings
from app.dependencies import get_db, get_redis
from app.models.db.session import ChatMessage, ChatSession
from app.models.db.user import User
from app.models.schemas.chat import ChatRequest, ChatResponse
from app.services.llm_service import use_request_model_name
from app.utils.history_truncator import truncate_history
from app.services.security_audit_service import SecurityAuditService

router = APIRouter()


@router.post("/message", response_model=ChatResponse)
async def chat_message(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Non-streaming chat endpoint for clients that cannot use SSE/WebSocket reliably."""
    await rate_limit_check(None, f"chat:{current_user.id}", limit=60, window=60)
    redis_client = get_redis()

    session = await _get_or_create_session(db, current_user, request.thread_id, request.message)
    user_message = ChatMessage(session_id=session.id, role="user", content=request.message)
    db.add(user_message)
    await db.flush()

    assistant_message = ChatMessage(session_id=session.id, role="assistant", content="", agent_used="agent_runtime_v2_http")
    db.add(assistant_message)
    await db.flush()

    from app.agent.runtime import AgentRuntime, RuntimeRequest
    from app.retrieval.semantic_cache import SemanticCache
    from app.security.input_guard import InputGuard
    from app.security.output_guard import OutputGuard
    from app.security.pii_masker import PIIMasker
    audit = SecurityAuditService(redis_client, db)
    with use_request_model_name(request.selected_model):
        cache = SemanticCache(redis_client)
        cached = await cache.get(request.message, user_id=current_user.id)
        if cached:
            assistant_message.content = cached["answer"]
            assistant_message.citations_json = json.dumps(cached.get("citations", []), ensure_ascii=False)
            assistant_message.agent_used = "cache"
            return ChatResponse(
                message_id=assistant_message.id,
                answer=cached["answer"],
                citations=cached.get("citations", []),
                agent_used="cache",
                cached=True,
                thread_id=session.id,
            )

        guard_result = await InputGuard().check(request.message)
        await _audit_guard_decision(
            audit,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            trace_id=None,
            guard_name="input",
            target="chat.query",
            message=request.message,
            guard_result=guard_result,
        )
        if not guard_result["safe"]:
            assistant_message.content = guard_result["reason"]
            assistant_message.agent_used = "input_guard"
            return ChatResponse(
                message_id=assistant_message.id,
                answer=guard_result["reason"],
                citations=[],
                agent_used="input_guard",
                cached=False,
                thread_id=session.id,
            )

        masker = PIIMasker()
        masked_query, pii_mapping = masker.mask(request.message)
        history_rows = await db.execute(select(ChatMessage).where(ChatMessage.session_id == session.id).order_by(ChatMessage.created_at.asc()))
        history_messages = truncate_history([
            {"role": item.role, "content": item.content}
            for item in history_rows.scalars().all()
            if item.id != assistant_message.id
        ])

        runtime = AgentRuntime(redis_client)
        runtime_request = RuntimeRequest(
            query=masked_query,
            thread_id=session.id,
            search_type=request.search_type,
            user_context={"user_id": current_user.id, "tenant_id": current_user.tenant_id, "role": current_user.role},
            history=history_messages,
        )

        final_answer = ""
        citations: list[dict] = []
        final_agent = "agent_runtime_v2_http"
        async for event in runtime.run(runtime_request, db=db, current_user=current_user):
            if event.get("status") == "done":
                final_answer = event.get("answer", "")
                citations = event.get("citations", [])
                final_agent = event.get("agent_used") or final_agent
                break

        restored_answer = masker.restore(final_answer, pii_mapping)
        guarded_output = await OutputGuard().check(restored_answer)
        await _audit_guard_decision(
            audit,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            trace_id=None,
            guard_name="output",
            target="chat.answer",
            message=restored_answer,
            guard_result=guarded_output,
        )
        if not guarded_output["safe"]:
            if guarded_output.get("degraded") and guarded_output.get("mode") == "garbled_detection":
                from app.agent.nodes.generator import _build_rule_fallback
                restored_answer = _build_rule_fallback(request.message, citations)
                final_agent = "rule_fallback_garbled"
            else:
                restored_answer = "输出内容命中安全规则，系统已拦截�?
                citations = []
                final_agent = "output_guard"
        assistant_message.content = restored_answer
        assistant_message.citations_json = json.dumps(citations, ensure_ascii=False)
        assistant_message.agent_used = final_agent
        await cache.put(request.message, restored_answer, citations, user_id=current_user.id)

        return ChatResponse(
            message_id=assistant_message.id,
            answer=restored_answer,
            citations=citations,
            agent_used=final_agent,
            cached=False,
            thread_id=session.id,
        )


@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    http_request: Request,
    resume_trace_id: str | None = Query(default=None),
    last_sequence: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stream progressive chat events with replay support."""
    await rate_limit_check(None, f"chat:{current_user.id}", limit=60, window=60)
    redis_client = get_redis()
    parsed_trace_id, parsed_last_sequence = _parse_resume_from_last_event_id(http_request.headers.get("Last-Event-ID"))
    if not resume_trace_id and parsed_trace_id:
        resume_trace_id = parsed_trace_id
    if last_sequence <= 0 and parsed_last_sequence > 0:
        last_sequence = parsed_last_sequence

    if resume_trace_id:
        async def replay_generator():
            from app.agent.runtime import AgentRuntime, RuntimeRequest
            from app.security.input_guard import InputGuard
            from app.security.output_guard import OutputGuard
            from app.security.pii_masker import PIIMasker

            with use_request_model_name(request.selected_model):
                replayed = False
                replay_terminal = False
                highest_sequence = max(last_sequence, 0)
                audit = SecurityAuditService(redis_client, db)

                async def emit_resume(payload: dict) -> str:
                    nonlocal highest_sequence
                    highest_sequence += 1
                    event_payload = payload.copy()
                    event_payload.setdefault("event_id", str(uuid.uuid4()))
                    event_payload.setdefault("sequence_num", highest_sequence)
                    event_payload.setdefault("trace_id", resume_trace_id)
                    event_payload.setdefault("source", "chat_replay")
                    event_payload.setdefault("degraded", False)
                    event_payload.setdefault("fallback_reason", None)
                    await _persist_replay_event(redis_client, current_user.tenant_id, event_payload)
                    return _sse_event(event_payload)

                if redis_client is not None:
                    rows = await redis_client.lrange(f"runtime:replay:{resume_trace_id}", 0, -1)
                    for row in rows:
                        try:
                            payload = json.loads(row)
                        except json.JSONDecodeError:
                            continue
                        if payload.get("tenant_id") != current_user.tenant_id:
                            continue
                        if int(payload.get("sequence_num", 0) or 0) <= max(last_sequence, 0):
                            continue
                        replayed = True
                        highest_sequence = max(highest_sequence, int(payload.get("sequence_num", 0) or 0))
                        if payload.get("status") in {"done", "error"}:
                            replay_terminal = True
                        yield _sse_event(payload)
                if replayed and replay_terminal:
                    return
                if not replayed or not replay_terminal:
                    guard_result = await InputGuard().check(request.message)
                    await _audit_guard_decision(
                        audit,
                        tenant_id=current_user.tenant_id,
                        user_id=current_user.id,
                        trace_id=resume_trace_id,
                        guard_name="input",
                        target="chat.resume.query",
                        message=request.message,
                        guard_result=guard_result,
                    )
                    if not guard_result["safe"]:
                        yield await emit_resume({"status": "error", "msg": guard_result["reason"]})
                        yield await emit_resume({"status": "done", "answer": guard_result["reason"], "citations": [], "agent_used": "input_guard"})
                        return

                    masker = PIIMasker()
                    masked_query, pii_mapping = masker.mask(request.message)
                    history_rows = await db.execute(select(ChatMessage).where(ChatMessage.session_id == (request.thread_id or "")).order_by(ChatMessage.created_at.asc()))
                    history_messages = truncate_history([
                        {"role": item.role, "content": item.content}
                        for item in history_rows.scalars().all()
                    ])
                    runtime = AgentRuntime(redis_client)
                    runtime_request = RuntimeRequest(
                        query=masked_query,
                        thread_id=request.thread_id,
                        search_type=request.search_type,
                        user_context={"user_id": current_user.id, "tenant_id": current_user.tenant_id, "role": current_user.role},
                        history=history_messages,
                    )
                    resumed = False
                    async for payload in runtime.resume_from_checkpoint(runtime_request, trace_id=resume_trace_id, db=db, current_user=current_user):
                        resumed = True
                        payload["trace_id"] = resume_trace_id
                        if payload.get("status") == "done":
                            restored_answer = masker.restore(payload.get("answer", ""), pii_mapping)
                            guarded_output = await OutputGuard().check(restored_answer)
                            await _audit_guard_decision(
                                audit,
                                tenant_id=current_user.tenant_id,
                                user_id=current_user.id,
                                trace_id=resume_trace_id,
                                guard_name="output",
                                target="chat.resume.answer",
                                message=restored_answer,
                                guard_result=guarded_output,
                            )
                            if not guarded_output["safe"]:
                                payload["answer"] = "输出内容命中安全规则，系统已拦截�?
                                payload["citations"] = []
                                payload["agent_used"] = "output_guard"
                            else:
                                payload["answer"] = restored_answer
                        highest_sequence += 1
                        payload["sequence_num"] = highest_sequence
                        await _persist_replay_event(redis_client, current_user.tenant_id, payload)
                        yield _sse_event(payload)
                    if not resumed:
                        yield await emit_resume(
                            {
                                "status": "done",
                                "degraded": True,
                                "fallback_reason": "replay_window_miss",
                                "msg": "未找到可继续恢复的事件，请重新发起请求�?,
                            }
                        )

        return StreamingResponse(
            replay_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    session = await _get_or_create_session(db, current_user, request.thread_id, request.message)
    user_message = ChatMessage(session_id=session.id, role="user", content=request.message)
    db.add(user_message)
    await db.flush()

    assistant_message = ChatMessage(session_id=session.id, role="assistant", content="", agent_used="agent_runtime_v2")
    db.add(assistant_message)
    await db.flush()

    async def event_generator():
        from app.agent.runtime import AgentRuntime, RuntimeRequest
        from app.retrieval.semantic_cache import SemanticCache
        from app.security.input_guard import InputGuard
        from app.security.output_guard import OutputGuard
        from app.security.pii_masker import PIIMasker
        from app.security.watermark import Watermarker
        from app.services.dlp_forensics_service import DLPForensicsService
        with use_request_model_name(request.selected_model):
            answer_parts: list[str] = []
            citations: list[dict] = []
            started_at = time.perf_counter()
            first_event_emitted = False
            sequence_num = 0
            request_trace_id = str(uuid.uuid4())
            final_degraded = False
            final_fallback_reason: str | None = None
            watermarker = Watermarker()
            cache = SemanticCache(redis_client)
            audit = SecurityAuditService(redis_client, db)

            async def emit(data: dict) -> str:
                nonlocal first_event_emitted
                nonlocal sequence_num
                if not first_event_emitted:
                    first_event_emitted = True
                    latency_ms = int((time.perf_counter() - started_at) * 1000)
                    if redis_client is not None:
                        key = f"metrics:sse_first_event_ms:{current_user.tenant_id}"
                        await redis_client.lpush(key, str(latency_ms))
                        await redis_client.ltrim(key, 0, 999)
                        await redis_client.expire(key, 14 * 24 * 3600)
                sequence_num += 1
                payload = data.copy()
                payload.setdefault("event_id", str(uuid.uuid4()))
                payload.setdefault("sequence_num", sequence_num)
                payload.setdefault("trace_id", request_trace_id)
                payload.setdefault("source", "chat_api")
                payload.setdefault("degraded", False)
                payload.setdefault("fallback_reason", None)
                await _persist_replay_event(redis_client, current_user.tenant_id, payload)
                return _sse_event(payload)

            try:
                yield await emit({"status": "thinking", "msg": "正在接收并校验请�?.."})
                cached = await cache.get(request.message, user_id=current_user.id)
                if cached:
                    visible_answer = watermarker.strip(cached["answer"])
                    yield await emit({"status": "reading", "msg": "命中语义缓存，正在返回结�?.."})
                    yield await emit({"status": "streaming", "content": visible_answer, "citations": cached.get("citations", [])})
                    assistant_message.content = visible_answer
                    assistant_message.citations_json = json.dumps(cached.get("citations", []), ensure_ascii=False)
                    assistant_message.agent_used = "cache"
                    yield await emit({"status": "done", "citations": cached.get("citations", []), "message_id": assistant_message.id, "thread_id": session.id})
                    return

                guard_result = await InputGuard().check(request.message)
                await _audit_guard_decision(
                    audit,
                    tenant_id=current_user.tenant_id,
                    user_id=current_user.id,
                    trace_id=request_trace_id,
                    guard_name="input",
                    target="chat.query",
                    message=request.message,
                    guard_result=guard_result,
                )
                if not guard_result["safe"]:
                    assistant_message.content = guard_result["reason"]
                    assistant_message.agent_used = "input_guard"
                    yield await emit({"status": "error", "msg": guard_result["reason"]})
                    yield await emit({"status": "done", "citations": [], "message_id": assistant_message.id, "thread_id": session.id})
                    return

                masker = PIIMasker()
                masked_query, pii_mapping = masker.mask(request.message)
                history_rows = await db.execute(select(ChatMessage).where(ChatMessage.session_id == session.id).order_by(ChatMessage.created_at.asc()))
                history_messages = truncate_history([
                    {"role": item.role, "content": item.content}
                    for item in history_rows.scalars().all()
                    if item.id != assistant_message.id
                ])

                runtime = AgentRuntime(redis_client)
                runtime_request = RuntimeRequest(
                    query=masked_query,
                    thread_id=session.id,
                    search_type=request.search_type,
                    user_context={"user_id": current_user.id, "tenant_id": current_user.tenant_id, "role": current_user.role},
                    history=history_messages,
                )
                final_answer = ""
                final_agent = "agent_runtime_v2"
                async for event in runtime.run(runtime_request, db=db, current_user=current_user):
                    if event.get("status") == "done":
                        request_trace_id = event.get("trace_id", request_trace_id)
                        final_answer = event.get("answer", "")
                        citations = event.get("citations", [])
                        final_agent = event.get("agent_used") or final_agent
                        final_degraded = bool(event.get("degraded", False))
                        final_fallback_reason = event.get("fallback_reason")
                        break
                    yield await emit(event)

                restored_answer = masker.restore(final_answer, pii_mapping)
                guarded_output = await OutputGuard().check(restored_answer)
                await _audit_guard_decision(
                    audit,
                    tenant_id=current_user.tenant_id,
                    user_id=current_user.id,
                    trace_id=request_trace_id,
                    guard_name="output",
                    target="chat.answer",
                    message=restored_answer,
                    guard_result=guarded_output,
                )
                if not guarded_output["safe"]:
                    if guarded_output.get("degraded") and guarded_output.get("mode") == "garbled_detection":
                        from app.agent.nodes.generator import _build_rule_fallback
                        restored_answer = _build_rule_fallback(request.message, citations)
                        final_agent = "rule_fallback_garbled"
                    else:
                        restored_answer = "输出内容命中安全规则，系统已拦截�?
                        citations = []
                        final_agent = "output_guard"

                answer_to_store = restored_answer
                if current_user.role in {"ADMIN", "MANAGER"}:
                    watermark_timestamp = datetime.now(timezone.utc).isoformat()
                    fingerprint = watermarker.build_fingerprint(current_user.id, watermark_timestamp)
                    answer_to_store = watermarker.inject(restored_answer, current_user.id, timestamp=watermark_timestamp)
                    await DLPForensicsService(redis_client, db).record_issue(
                        tenant_id=current_user.tenant_id,
                        user_id=current_user.id,
                        thread_id=session.id,
                        message_id=assistant_message.id,
                        fingerprint=fingerprint,
                        timestamp=watermark_timestamp,
                    )

                for char in restored_answer:
                    answer_parts.append(char)
                    yield await emit({"status": "streaming", "token": char})

                visible_answer = "".join(answer_parts)
                assistant_message.content = answer_to_store
                assistant_message.citations_json = json.dumps(citations, ensure_ascii=False)
                assistant_message.agent_used = final_agent

                if not final_degraded:
                    await cache.put(
                        request.message,
                        visible_answer,
                        citations,
                        user_id=current_user.id,
                        degraded=False,
                        fallback_reason=final_fallback_reason,
                    )
                yield await emit({"status": "done", "citations": citations, "message_id": assistant_message.id, "thread_id": session.id})
            except asyncio.CancelledError:
                await _incr_runtime_counter(redis_client, current_user.tenant_id, "sse_disconnects")
                raise

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.get("/history")
async def get_chat_history(thread_id: str = Query(..., min_length=1), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Get conversation history for a thread."""
    session = await db.scalar(select(ChatSession).where(ChatSession.id == thread_id, ChatSession.user_id == current_user.id))
    if session is None:
        return {"thread_id": thread_id, "messages": []}

    rows = await db.execute(select(ChatMessage).where(ChatMessage.session_id == thread_id).order_by(ChatMessage.created_at.asc()))
    messages = rows.scalars().all()
    return {
        "thread_id": thread_id,
        "messages": [
            {
                "id": item.id,
                "role": item.role,
                "content": item.content,
                "citations": json.loads(item.citations_json) if item.citations_json else [],
                "created_at": item.created_at.isoformat(),
            }
            for item in messages
        ],
    }


@router.post("/feedback")
async def submit_feedback(message_id: str, rating: int = Query(..., ge=-1, le=1), correction: str | None = None, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.services.feedback_service import FeedbackService

    await FeedbackService(db).record(user_id=current_user.id, tenant_id=current_user.tenant_id, message_id=message_id, rating=rating, correction=correction)
    return {"status": "recorded"}


def _sse_event(data: dict) -> str:
    trace_id = str(data.get("trace_id") or "")
    sequence_num = int(data.get("sequence_num", 0) or 0)
    if trace_id and sequence_num > 0:
        return f"id: {trace_id}:{sequence_num}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
    event_id = str(data.get("event_id") or "")
    if event_id:
        return f"id: {event_id}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _persist_replay_event(redis_client, tenant_id: str, payload: dict) -> None:
    if redis_client is None:
        return
    trace_id = payload.get("trace_id")
    if not trace_id:
        return
    key = f"runtime:replay:{trace_id}"
    replay_payload = payload.copy()
    replay_payload["tenant_id"] = tenant_id
    await redis_client.rpush(key, json.dumps(replay_payload, ensure_ascii=False))
    await redis_client.expire(key, settings.runtime_event_replay_ttl_seconds)


async def _incr_runtime_counter(redis_client, tenant_id: str, name: str) -> None:
    if redis_client is None:
        return
    key = f"runtime:counters:{tenant_id}"
    await redis_client.hincrby(key, name, 1)
    await redis_client.expire(key, 14 * 24 * 3600)


async def _audit_guard_decision(
    audit: SecurityAuditService,
    *,
    tenant_id: str,
    user_id: str,
    trace_id: str | None,
    guard_name: str,
    target: str,
    message: str,
    guard_result: dict,
) -> None:
    result = "blocked" if not guard_result.get("safe", True) else ("warning" if guard_result.get("degraded") else "ok")
    severity = str(guard_result.get("severity") or ("high" if result == "blocked" else "low"))
    reason = str(guard_result.get("reason") or "")
    summary = {
        "input": "输入安全校验",
        "output": "输出安全校验",
    }.get(guard_name, "安全校验")
    message_text = reason or f"{summary}{'通过' if result == 'ok' else '进入降级模式' if result == 'warning' else '已拦�?}�?
    await audit.log_event(
        tenant_id,
        f"{guard_name}_guard_decision",
        severity,
        message_text,
        user_id=user_id,
        target=target,
        result=result,
        trace_id=trace_id,
        metadata={
            "guard": guard_name,
            "mode": guard_result.get("mode"),
            "decision_source": guard_result.get("decision_source"),
            "issues": guard_result.get("issues", []),
            "degraded": bool(guard_result.get("degraded", False)),
            "blocked": not bool(guard_result.get("safe", True)),
            "preview": (message or "")[:120],
        },
    )


def _parse_resume_from_last_event_id(value: str | None) -> tuple[str | None, int]:
    if not value:
        return None, 0
    parts = value.split(":", 1)
    if len(parts) != 2:
        return None, 0
    trace_id = parts[0].strip()
    try:
        sequence = int(parts[1].strip())
    except ValueError:
        return None, 0
    if not trace_id or sequence < 0:
        return None, 0
    return trace_id, sequence


async def _get_or_create_session(db: AsyncSession, current_user: User, thread_id: str | None, first_question: str):
    if thread_id:
        existing = await db.scalar(select(ChatSession).where(ChatSession.id == thread_id, ChatSession.user_id == current_user.id))
        if existing is not None:
            existing.updated_at = datetime.utcnow()
            return existing

    new_id = thread_id if thread_id else str(uuid.uuid4())
    session = ChatSession(id=new_id, user_id=current_user.id, tenant_id=current_user.tenant_id, title=(first_question[:40].strip() or "新对�?))
    db.add(session)
    await db.flush()
    return session

