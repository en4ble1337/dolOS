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
    input_tokens: int = 0
    output_tokens: int = 0


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
                "timeout": self.settings.llm_timeout,
            }
            if api_base:
                kwargs["api_base"] = api_base
            if is_ollama_remapped:
                kwargs["api_key"] = "ollama"
                # Disable qwen3 thinking mode to avoid long pauses.
                # Users can re-enable via OLLAMA_EXTRA_BODY or env config if desired.
                if "qwen3" in model.lower():
                    kwargs.setdefault("extra_body", {})
                    kwargs["extra_body"]["chat_template_kwargs"] = {"enable_thinking": False}

            tool_names = [t["function"]["name"] for t in tools] if tools else []
            logger.debug(f"[LLM_REQUEST] model={model} | tools_sent={bool(tools)} | tools={tool_names}")

            response = await acompletion(**kwargs)

            raw_tool_calls = getattr(response.choices[0].message, "tool_calls", None) if response.choices else None
            raw_content_preview = (response.choices[0].message.content or "")[:200] if response.choices else ""
            logger.debug(f"[LLM_RESPONSE] raw_tool_calls={raw_tool_calls} | content={raw_content_preview!r}")

            end_time = time.time()
            duration_ms = (end_time - start_time) * 1000

            input_tokens = 0
            output_tokens = 0
            if hasattr(response, "usage") and response.usage:
                input_tokens = getattr(response.usage, "prompt_tokens", 0) or 0
                output_tokens = getattr(response.usage, "completion_tokens", 0) or 0

            await self.event_bus.emit(
                Event(
                    event_type=EventType.LLM_CALL_END,
                    component="agent.llm",
                    trace_id=trace_id,
                    payload={
                        "model": self.settings.primary_model,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "total_tokens": input_tokens + output_tokens,
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
                input_tokens=input_tokens,
                output_tokens=output_tokens,
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

            fb_input_tokens = 0
            fb_output_tokens = 0
            if hasattr(response, "usage") and response.usage:
                fb_input_tokens = getattr(response.usage, "prompt_tokens", 0) or 0
                fb_output_tokens = getattr(response.usage, "completion_tokens", 0) or 0

            await self.event_bus.emit(
                Event(
                    event_type=EventType.LLM_CALL_END,
                    component="agent.llm",
                    trace_id=trace_id,
                    payload={
                        "model": self.settings.fallback_model,
                        "input_tokens": fb_input_tokens,
                        "output_tokens": fb_output_tokens,
                        "total_tokens": fb_input_tokens + fb_output_tokens,
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
                input_tokens=fb_input_tokens,
                output_tokens=fb_output_tokens,
            )
