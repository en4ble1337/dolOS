"""OpenAI-compatible chat completions endpoint (Gap H5).

Exposes POST /v1/chat/completions with the OpenAI wire format so that any
frontend speaking the OpenAI protocol (Open WebUI, LibreChat, etc.) can
connect without a custom adapter.

Design decisions:
- Session ID is taken from the ``user`` field; a random hex is generated when
  absent (stateless per-request).
- Only the last user message is forwarded to agent.process_message() — dolOS
  owns session memory, so replaying the full history would duplicate context.
- Streaming (SSE) is not included in this phase; it is a planned follow-up.
"""

import time
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

v1_router = APIRouter(prefix="/v1")


class ChatCompletionRequest(BaseModel):
    model: str = "dolOS"
    messages: list[dict]  # [{role, content}, ...]
    stream: bool = False
    user: str | None = None  # used as session_id when provided


@v1_router.post("/chat/completions")
async def chat_completions(data: ChatCompletionRequest, request: Request) -> dict:
    """Process a chat completion request in the OpenAI wire format."""
    if data.stream:
        raise HTTPException(
            status_code=501,
            detail="Streaming (SSE) is not yet implemented. Set stream=false.",
        )

    agent = getattr(request.app.state, "agent", None)
    if agent is None:
        raise HTTPException(status_code=500, detail="Agent not configured")

    session_id = data.user or uuid.uuid4().hex

    # Extract the last user message from the messages array.
    user_message = next(
        (m["content"] for m in reversed(data.messages) if m.get("role") == "user"),
        "",
    )

    reply: str = await agent.process_message(
        session_id=session_id,
        message=user_message,
    )

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": data.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": reply},
                "finish_reason": "stop",
            }
        ],
        "usage": None,
    }
