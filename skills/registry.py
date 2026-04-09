import inspect
import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Return cosine similarity in [0, 1] between two vectors. Returns 0 on zero vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


@dataclass
class SkillRegistration:
    """Metadata record for a registered skill.

    Stored in ``SkillRegistry`` alongside the callable so consumers can
    inspect skills without executing them.  The fields are designed to
    support Phase 3 features (permission layer, parallel execution) without
    requiring registry changes later.
    """

    name: str
    description: str
    func: Callable[..., Any]
    input_schema: dict[str, Any] | None = None

    # Gap 2 â€” typed tool contract metadata
    is_read_only: bool = True
    """True if the skill does not mutate external state (safe to run in parallel)."""

    concurrency_safe: bool = True
    """True if the skill can be called concurrently without race conditions."""

    description_fn: Callable[[], str] | None = None
    """Optional callable that returns a dynamic description at runtime.
    When set, callers may prefer this over the static ``description`` string.
    """

    # Phase D â€” semantic routing
    description_embedding: list[float] | None = None
    """Embedding vector for the description, set at registration or on set_embedder() backfill."""


class SkillRegistry:
    """A registry for managing and generating JSON schemas for tools."""

    # Blend weights for semantic + keyword routing score.
    _SEMANTIC_WEIGHT: float = 0.7
    _KEYWORD_WEIGHT: float = 0.3

    def __init__(self) -> None:
        self._registrations: dict[str, SkillRegistration] = {}
        self._schemas: dict[str, dict[str, Any]] = {}
        self._embedder: Any = None  # set via set_embedder(); optional

    def set_embedder(self, embedder: Any) -> None:
        """Inject the shared embedding service and backfill all registered skills.

        Built-in skills are imported before the embedder is available in main.py.
        Calling this method after memory init immediately embeds every skill whose
        ``description_embedding`` is still None, so semantic routing works for all
        skills â€” not just those registered after this call.

        Args:
            embedder: Any object with an ``encode(text: str) -> list[float]`` method.
        """
        self._embedder = embedder
        for reg in self._registrations.values():
            if reg.description_embedding is None:
                try:
                    reg.description_embedding = embedder.encode(reg.description)
                except Exception:
                    pass  # leave as None; keyword fallback covers this skill

    def register(
        self,
        name: str,
        description: str,
        func: Callable[..., Any],
        input_schema: dict[str, Any] | None = None,
        is_read_only: bool = True,
        concurrency_safe: bool = True,
        description_fn: Callable[[], str] | None = None,
    ) -> None:
        """Register a function as a skill and generate its OpenAI JSON schema."""
        embedding: list[float] | None = None
        if self._embedder is not None:
            try:
                embedding = self._embedder.encode(description)
            except Exception:
                pass

        reg = SkillRegistration(
            name=name,
            description=description,
            func=func,
            input_schema=input_schema,
            is_read_only=is_read_only,
            concurrency_safe=concurrency_safe,
            description_fn=description_fn,
            description_embedding=embedding,
        )
        self._registrations[name] = reg

        if input_schema:
            self._schemas[name] = {
                "name": name,
                "description": description,
                "parameters": input_schema,
            }
        else:
            self._schemas[name] = self._generate_schema(name, description, func)

    def get_skill(self, name: str) -> Callable[..., Any]:
        """Retrieve a registered skill function by name."""
        if name not in self._registrations:
            raise KeyError(f"Skill '{name}' not found in registry.")
        return self._registrations[name].func

    def get_registration(self, name: str) -> SkillRegistration:
        """Retrieve the full SkillRegistration record for a skill."""
        if name not in self._registrations:
            raise KeyError(f"Skill '{name}' not found in registry.")
        return self._registrations[name]

    def get_schema(self, name: str) -> dict[str, Any]:
        """Retrieve the OpenAI-compatible JSON schema for a registered skill."""
        if name not in self._schemas:
            raise KeyError(f"Skill '{name}' not found in registry.")
        return self._schemas[name]

    def get_all_skill_names(self) -> list[str]:
        """Return a list of all registered skill names."""
        return list(self._registrations.keys())

    def get_all_schemas(self) -> list[dict[str, Any]]:
        """Return a list of all registered valid JSON schemas."""
        return list(self._schemas.values())

    def get_relevant_schemas(self, query: str, max_tools: int = 10) -> list[dict[str, Any]]:
        """Return the most query-relevant schemas, capped at *max_tools*.

        When the registry has â‰¤ 10 skills all schemas are returned unchanged
        (routing overhead isn't worthwhile at that scale).  For larger registries
        each skill is scored and the top *max_tools* are returned.

        Scoring (when embedder is available):
            blended = 0.7 * cosine_similarity(query_embedding, skill_embedding)
                    + 0.3 * keyword_overlap_fraction

        Fallback (no embedder or all embeddings are None):
            keyword overlap count only (original behaviour).

        Emits a ``[TOOL_ROUTING]`` debug log entry with counts.
        """
        import logging
        _log = logging.getLogger(__name__)

        all_schemas = self.get_all_schemas()
        total = len(all_schemas)

        routing_threshold = 10
        if total <= routing_threshold:
            _log.debug("[TOOL_ROUTING] registry=%d â‰¤ threshold=%d, routing skipped", total, routing_threshold)
            return all_schemas

        query_tokens = set(query.lower().split())
        n_query_tokens = max(len(query_tokens), 1)

        # Attempt semantic scoring if embedder is available
        query_embedding: list[float] | None = None
        if self._embedder is not None:
            try:
                query_embedding = self._embedder.encode(query)
            except Exception:
                query_embedding = None

        use_semantic = query_embedding is not None

        def _score(schema: dict[str, Any]) -> float:
            name = schema.get("name", "")
            reg = self._registrations.get(name)

            # Keyword fraction: overlap / query token count â†’ [0, 1]
            name_tokens = set(name.lower().replace("_", " ").split())
            desc_tokens = set(schema.get("description", "").lower().split())
            overlap = len(query_tokens & (name_tokens | desc_tokens))
            keyword_frac = min(overlap / n_query_tokens, 1.0)

            if (
                not use_semantic
                or query_embedding is None
                or reg is None
                or reg.description_embedding is None
            ):
                return keyword_frac

            semantic = _cosine_similarity(query_embedding, reg.description_embedding)
            return self._SEMANTIC_WEIGHT * semantic + self._KEYWORD_WEIGHT * keyword_frac

        scored = sorted(all_schemas, key=_score, reverse=True)
        result = scored[:max_tools]

        _log.debug(
            "[TOOL_ROUTING] registry=%d query=%r mode=%s selected=%d/%d",
            total, query[:60], "semantic+keyword" if use_semantic else "keyword",
            len(result), total,
        )
        return result

    def _generate_schema(
        self, name: str, description: str, func: Callable[..., Any]
    ) -> dict[str, Any]:
        """Generate an OpenAI-compatible function schema from a Python callable."""
        sig = inspect.signature(func)

        schema: dict[str, Any] = {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {},
            },
        }

        required: list[str] = []

        for param_name, param in sig.parameters.items():
            # If the parameter is a Pydantic model
            if isinstance(param.annotation, type) and issubclass(param.annotation, BaseModel):
                # Pydantic v2
                model_schema = param.annotation.model_json_schema()
                schema["parameters"]["properties"][param_name] = model_schema
                # A custom Pydantic object is typically required as a whole
                if param.default is inspect.Parameter.empty:
                    required.append(param_name)

                # We could flatten the properties if we wanted it to feel more natural,
                # but nested objects are valid in JSON schema. Pydantic actually handles
                # flat arguments better if we extract them, but for this basic implementation
                # we'll just map the primitive arguments natively and let Pydantic models
                # be passed as entire nested objects if desired, OR we can extract Pydantic
                # fields directly into the top-level properties.

                # Actually, standard tool usage typically flattens parameters. Let's flatten
                # if it's the ONLY argument and it's a Pydantic model?
                # For simplicity, if a parameter is a pydantic model, we'll extract its properties
                # into the main schema properties.

                pydantic_props = model_schema.get("properties", {})
                pydantic_req = model_schema.get("required", [])

                # Instead of putting the model as a nested object, let's just
                # extract its properties into the top level parameters
                for k, v in pydantic_props.items():
                    schema["parameters"]["properties"][k] = v
                required.extend(pydantic_req)

                # Delete the top-level nested parameter we initially started
                del schema["parameters"]["properties"][param_name]
                if param_name in required:
                    required.remove(param_name)

                continue

            # Standard primitive types
            param_schema: dict[str, Any] = {}

            # Very basic type mapping
            type_mapping = {
                int: "integer",
                float: "number",
                str: "string",
                bool: "boolean",
                list: "array",
                dict: "object",
            }

            annotated_type = param.annotation
            if getattr(annotated_type, "__origin__", None):
                # Handle typing.List, typing.Dict, etc.
                annotated_type = annotated_type.__origin__

            param_schema["type"] = type_mapping.get(annotated_type, "string")

            if param.default is not inspect.Parameter.empty:
                param_schema["default"] = param.default
            else:
                required.append(param_name)

            schema["parameters"]["properties"][param_name] = param_schema

        if required:
            schema["parameters"]["required"] = required

        return schema


# Global default registry
_default_registry = SkillRegistry()


def skill(
    name: str | None = None,
    description: str | None = None,
    registry: SkillRegistry | None = None,
    read_only: bool = True,
    concurrency_safe: bool = True,
    description_fn: Callable[[], str] | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator to register a function as a skill.

    Args:
        name: Name of the skill. Defaults to the function's name.
        description: Description of the skill. Defaults to the function's docstring.
        registry: The SkillRegistry to add the skill to. Defaults to the global registry.
        read_only: True if the skill does not mutate external state. Default True.
        concurrency_safe: True if the skill is safe to call concurrently. Default True.
        description_fn: Optional callable returning a dynamic description at runtime.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        nonlocal name, description
        skill_name = name or func.__name__
        skill_desc = description or inspect.getdoc(func) or "No description provided."

        target_registry = registry or _default_registry
        target_registry.register(
            skill_name,
            skill_desc,
            func,
            is_read_only=read_only,
            concurrency_safe=concurrency_safe,
            description_fn=description_fn,
        )
        return func

    return decorator

