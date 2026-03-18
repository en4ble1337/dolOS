import logging
import time
from typing import Any, Dict, List, Optional

from litellm import acompletion
from pydantic import BaseModel

from core.config import Settings
from core.telemetry import Event, EventBus, EventType

logger = logging.getLogger(__name__)


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
            model = self.settings.primary_model
            api_base = self.settings.ollama_api_base

            # Remap ollama/ prefix to OpenAI-compatible endpoint so LiteLLM correctly
            # parses native tool_calls. Ollama's /api/chat returns arguments as a dict
            # but LiteLLM's ollama provider doesn't parse that; the /v1 endpoint uses
            # the OpenAI wire format which LiteLLM handles correctly.
            is_ollama_remapped = False
            if model.startswith("ollama/") and api_base:
                model = "openai/" + model[len("ollama/"):]
                api_base = api_base.rstrip("/") + "/v1"
                is_ollama_remapped = True

            kwargs: Dict[str, Any] = {
                "model": model,
                "messages": messages,
                "tools": tools,
            }
            if api_base:
                kwargs["api_base"] = api_base
            if is_ollama_remapped:
                kwargs["api_key"] = "ollama"

            tool_names = [t["function"]["name"] for t in tools] if tools else []
            logger.info(f"[LLM_REQUEST] model={model} | tools_sent={bool(tools)} | tools={tool_names}")

            response = await acompletion(**kwargs)

            raw_tool_calls = getattr(response.choices[0].message, "tool_calls", None) if response.choices else None
            raw_content_preview = (response.choices[0].message.content or "")[:200] if response.choices else ""
            logger.info(f"[LLM_RESPONSE] raw_tool_calls={raw_tool_calls} | content={raw_content_preview!r}")

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
