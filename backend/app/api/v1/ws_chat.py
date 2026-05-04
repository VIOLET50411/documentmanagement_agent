"""WebSocket chat endpoint for mobile clients.

WeChat Mini Programs and some mobile WebView environments do not support SSE
reliably. This endpoint provides the same chat stream over WebSocket.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.middleware.auth import decode_token
from app.dependencies import get_redis, get_session_factory
from app.models.db.session import ChatMessage, ChatSession
from app.models.db.user import User
from app.services.security_audit_service import SecurityAuditService

router = APIRouter()


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """WebSocket-based streaming chat for mobile clients.

    Protocol:
    1. Client -> {"type":"auth","token":"<jwt>"}
    2. Server -> {"type":"auth_ok","user_id":"...","tenant_id":"..."}
    3. Client -> {"type":"message","content":"...","thread_id":"...","search_type":"hybrid"}
    4. Server -> multiple `status` events
    5. Server -> multiple `token` events
    6. Server -> final `done` event
    """
    await websocket.accept()
    current_user: User | None = None
    session_factory = get_session_factory()

    try:
        auth_msg = await asyncio.wait_for(websocket.receive_json(), timeout=10.0)
        if auth_msg.get("type") != "auth" or not auth_msg.get("token"):
            await websocket.send_json({"type": "error", "msg": "请先发送认证消息：{type: 'auth', token: '<jwt>'}"})
            await websocket.close(code=4001)
            return

        try:
            payload = decode_token(auth_msg["token"])
            user_id = payload.get("sub")
            if not user_id:
                raise ValueError("Invalid token")
        except (JWTError, TypeError, ValueError):
            await websocket.send_json({"type": "error", "msg": "认证失败，请重新登录"})
            await websocket.close(code=4003)
            return

        async with session_factory() as db:
            user = await db.scalar(select(User).where(User.id == user_id))
            if not user:
                await websocket.send_json({"type": "error", "msg": "用户不存在"})
                await websocket.close(code=4004)
                return
            current_user = user
            await websocket.send_json({"type": "auth_ok", "user_id": user.id, "tenant_id": user.tenant_id})

        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            if msg_type != "message":
                await websocket.send_json({"type": "error", "msg": f"未知消息类型：{msg_type}"})
                continue

            content = (data.get("content") or "").strip()
            if not content:
                await websocket.send_json({"type": "error", "msg": "消息内容不能为空"})
                continue

            async with session_factory() as db:
                await _handle_chat_message(
                    websocket=websocket,
                    db=db,
                    current_user=current_user,
                    content=content,
                    thread_id=data.get("thread_id"),
                    search_type=data.get("search_type", "hybrid"),
                )

    except WebSocketDisconnect:
        return
    except asyncio.TimeoutError:
        try:
            await websocket.send_json({"type": "error", "msg": "连接超时"})
            await websocket.close(code=4008)
        except RuntimeError:
            return
    except RuntimeError:
        try:
            await websocket.send_json({"type": "error", "msg": "服务端内部错误"})
            await websocket.close(code=4500)
        except RuntimeError:
            return


async def _handle_chat_message(
    *,
    websocket: WebSocket,
    db: AsyncSession,
    current_user: User,
    content: str,
    thread_id: str | None,
    search_type: str,
):
    """Process a single chat message and stream results via WebSocket."""
    from app.agent.runtime import AgentRuntime, RuntimeRequest
    from app.retrieval.semantic_cache import SemanticCache
    from app.security.input_guard import InputGuard
    from app.security.output_guard import OutputGuard
    from app.security.pii_masker import PIIMasker

    redis_client = get_redis()
    audit = SecurityAuditService(redis_client, db)

    session = None
    if thread_id:
        session = await db.scalar(
            select(ChatSession).where(ChatSession.id == thread_id, ChatSession.user_id == current_user.id)
        )
    if session is None:
        session = ChatSession(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            tenant_id=current_user.tenant_id,
            title=(content[:40].strip() or "新对话"),
        )
        db.add(session)
        await db.flush()

    user_message = ChatMessage(session_id=session.id, role="user", content=content)
    db.add(user_message)
    await db.flush()

    assistant_message = ChatMessage(session_id=session.id, role="assistant", content="", agent_used="ws_runtime")
    db.add(assistant_message)
    await db.flush()

    try:
        cache = SemanticCache(redis_client)
        cached = await cache.get(content, user_id=current_user.id)
        if cached:
            await websocket.send_json({"type": "status", "status": "thinking", "msg": "命中缓存，正在返回结果..."})
            await websocket.send_json(
                {
                    "type": "done",
                    "answer": cached["answer"],
                    "citations": cached.get("citations", []),
                    "message_id": assistant_message.id,
                    "thread_id": session.id,
                }
            )
            assistant_message.content = cached["answer"]
            assistant_message.agent_used = "cache"
            assistant_message.updated_at = datetime.now(timezone.utc)
            await db.commit()
            return

        guard_result = await InputGuard().check(content)
        await _audit_guard_decision(
            audit,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            trace_id=None,
            guard_name="input",
            target="ws.chat.query",
            message=content,
            guard_result=guard_result,
        )
        if not guard_result["safe"]:
            assistant_message.content = guard_result["reason"]
            assistant_message.agent_used = "input_guard"
            assistant_message.updated_at = datetime.now(timezone.utc)
            await websocket.send_json({"type": "error", "msg": guard_result["reason"]})
            await websocket.send_json(
                {
                    "type": "done",
                    "answer": guard_result["reason"],
                    "citations": [],
                    "message_id": assistant_message.id,
                    "thread_id": session.id,
                }
            )
            await db.commit()
            return

        masker = PIIMasker()
        masked_query, pii_mapping = masker.mask(content)

        history_rows = await db.execute(
            select(ChatMessage).where(ChatMessage.session_id == session.id).order_by(ChatMessage.created_at.asc())
        )
        history = [
            {"role": item.role, "content": item.content}
            for item in history_rows.scalars().all()
            if item.id != assistant_message.id
        ]

        runtime = AgentRuntime(redis_client)
        runtime_request = RuntimeRequest(
            query=masked_query,
            thread_id=session.id,
            search_type=search_type,
            user_context={
                "user_id": current_user.id,
                "tenant_id": current_user.tenant_id,
                "role": current_user.role,
            },
            history=history,
        )

        final_answer = ""
        citations = []
        trace_id: str | None = None
        async for event in runtime.run(runtime_request, db=db, current_user=current_user):
            status = event.get("status", "")
            if status == "done":
                trace_id = event.get("trace_id")
                final_answer = event.get("answer", "")
                citations = event.get("citations", [])
                break
            await websocket.send_json({"type": "status", "status": status, "msg": event.get("msg", "")})

        restored_answer = masker.restore(final_answer, pii_mapping)
        guarded = await OutputGuard().check(restored_answer)
        await _audit_guard_decision(
            audit,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            trace_id=trace_id,
            guard_name="output",
            target="ws.chat.answer",
            message=restored_answer,
            guard_result=guarded,
        )
        if not guarded["safe"]:
            restored_answer = "输出内容命中安全规则，系统已拦截。"
            citations = []

        for char in restored_answer:
            await websocket.send_json({"type": "token", "content": char})

        assistant_message.content = restored_answer
        assistant_message.citations_json = json.dumps(citations, ensure_ascii=False)
        assistant_message.updated_at = datetime.now(timezone.utc)
        await cache.put(content, restored_answer, citations, user_id=current_user.id)

        await websocket.send_json(
            {
                "type": "done",
                "answer": restored_answer,
                "citations": citations,
                "message_id": assistant_message.id,
                "thread_id": session.id,
            }
        )
        await db.commit()

    except (asyncio.TimeoutError, RuntimeError, TypeError, ValueError) as exc:
        await audit.log_event(
            current_user.tenant_id,
            "ws_runtime_exception",
            "medium",
            "WebSocket 运行时处理失败，已返回统一错误提示。",
            user_id=current_user.id,
            target="ws.chat",
            result="error",
            metadata={"error_type": exc.__class__.__name__, "detail": str(exc)[:200]},
        )
        await websocket.send_json({"type": "error", "msg": "运行时处理失败，请稍后重试。"})
        await db.rollback()


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
    message_text = reason or f"{summary}{'通过' if result == 'ok' else '进入降级模式' if result == 'warning' else '已拦截'}。"
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
