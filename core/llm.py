import time
from typing import Any, Dict, List, Optional

from litellm import acompletion
from pydantic import BaseModel

from core.config import Settings
from core.telemetry import Event, EventBus, EventType


class LLMResponse(BaseModel):
    content: Optional[str]
    tool_calls: Optional[List[Any]] = None


class LLMGateway:
    def __init__(self, event_bus: EventBus, settings: Settings):
        self.event_bus = event_bus
        self.settings = settings

    async def generate(
        self,
        messages: List[Dict[str, Any]],
        trace_id: str,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        start_time = time.time()

        await self.event_bus.emit(
            Event(
                event_type=EventType.LLM_CALL_START,
                component="agent.llm",
                trace_id=trace_id,
                payload={"model": self.settings.primary_model},
            )
        )

        try:
            kwargs: Dict[str, Any] = {
                "model": self.settings.primary_model,
                "messages": messages,
                "tools": tools,
            }
            if self.settings.primary_model.startswith("ollama/") and self.settings.ollama_api_base:
                kwargs["api_base"] = self.settings.ollama_api_base
                
            response = await acompletion(**kwargs)

            end_time = time.time()
            duration_ms = (end_time - start_time) * 1000

            await self.event_bus.emit(
                Event(
                    event_type=EventType.LLM_CALL_END,
                    component="agent.llm",
                    trace_id=trace_id,
                    payload={
                        "model": self.settings.primary_model,
                        "total_tokens": (
                            response.usage.total_tokens
                            if hasattr(response, "usage") and response.usage
                            else 0
                        ),
                    },
                    duration_ms=duration_ms,
                )
            )

            return LLMResponse(
                content=response.choices[0].message.content if response.choices else None,
                tool_calls=(
                    getattr(response.choices[0].message, "tool_calls", None)
                    if response.choices
                    else None
                ),
            )

        except Exception as e:
            if not self.settings.fallback_model:
                raise e

            await self.event_bus.emit(
                Event(
                    event_type=EventType.LLM_FALLBACK,
                    component="agent.llm",
                    trace_id=trace_id,
                    payload={
                        "failed_model": self.settings.primary_model,
                        "fallback_model": self.settings.fallback_model,
                        "error": str(e),
                    },
                )
            )

            response = await acompletion(
                model=self.settings.fallback_model, messages=messages, tools=tools
            )

            end_time = time.time()
            duration_ms = (end_time - start_time) * 1000

            await self.event_bus.emit(
                Event(
                    event_type=EventType.LLM_CALL_END,
                    component="agent.llm",
                    trace_id=trace_id,
                    payload={
                        "model": self.settings.fallback_model,
                        "total_tokens": (
                            response.usage.total_tokens
                            if hasattr(response, "usage") and response.usage
                            else 0
                        ),
                    },
                    duration_ms=duration_ms,
                )
            )

            return LLMResponse(
                content=response.choices[0].message.content if response.choices else None,
                tool_calls=(
                    getattr(response.choices[0].message, "tool_calls", None)
                    if response.choices
                    else None
                ),
            )
