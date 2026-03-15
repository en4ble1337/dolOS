import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from core.agent import Agent
from core.telemetry import Event, EventBus, EventType, reset_trace_id, set_trace_id

chat_router = APIRouter()


class ChatRequest(BaseModel):
    session_id: str
    message: str


class ChatResponse(BaseModel):
    content: str


def get_agent(request: Request) -> Agent:
    """Retrieve the injected Agent instance from the app state."""
    agent = getattr(request.app.state, "agent", None)
    if not agent:
        raise HTTPException(status_code=500, detail="Agent not configured")
    return agent


def get_event_bus(request: Request) -> EventBus:
    """Retrieve the injected EventBus instance from the app state."""
    bus = getattr(request.app.state, "event_bus", None)
    if not bus:
        raise HTTPException(status_code=500, detail="EventBus not configured")
    return bus


@chat_router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    data: ChatRequest,
    agent: Agent = Depends(get_agent),
    event_bus: EventBus = Depends(get_event_bus),
) -> ChatResponse:
    """Process a chat message via HTTP REST."""

    trace_id = uuid.uuid4().hex
    token = set_trace_id(trace_id)

    try:
        await event_bus.emit(
            Event(
                event_type=EventType.MESSAGE_RECEIVED,
                component="channel.api",
                trace_id=trace_id,
                payload={"session_id": data.session_id, "length": len(data.message)},
            )
        )

        reply = await agent.process_message(
            session_id=data.session_id,
            message=data.message,
        )

        await event_bus.emit(
            Event(
                event_type=EventType.MESSAGE_SENT,
                component="channel.api",
                trace_id=trace_id,
                payload={"session_id": data.session_id, "length": len(reply)},
            )
        )

        return ChatResponse(content=reply)

    finally:
        reset_trace_id(token)
