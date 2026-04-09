import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel


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

    # Gap 2 — typed tool contract metadata
    is_read_only: bool = True
    """True if the skill does not mutate external state (safe to run in parallel)."""

    concurrency_safe: bool = True
    """True if the skill can be called concurrently without race conditions."""

    description_fn: Callable[[], str] | None = None
    """Optional callable that returns a dynamic description at runtime.
    When set, callers may prefer this over the static ``description`` string.
    """


class SkillRegistry:
    """A registry for managing and generating JSON schemas for tools."""

    def __init__(self) -> None:
        self._registrations: dict[str, SkillRegistration] = {}
        self._schemas: dict[str, dict[str, Any]] = {}

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
        reg = SkillRegistration(
            name=name,
            description=description,
            func=func,
            input_schema=input_schema,
            is_read_only=is_read_only,
            concurrency_safe=concurrency_safe,
            description_fn=description_fn,
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

        When the registry has ≤ 10 skills all schemas are returned unchanged
        (routing overhead isn't worthwhile at that scale).  For larger registries
        each skill is scored by keyword overlap between *query* and the skill
        name + description, then the top *max_tools* are returned.

        Emits a ``[TOOL_ROUTING]`` debug log entry with counts.
        """
        import logging
        _log = logging.getLogger(__name__)

        all_schemas = self.get_all_schemas()
        total = len(all_schemas)

        _ROUTING_THRESHOLD = 10
        if total <= _ROUTING_THRESHOLD:
            _log.debug("[TOOL_ROUTING] registry=%d ≤ threshold=%d, routing skipped", total, _ROUTING_THRESHOLD)
            return all_schemas

        query_tokens = set(query.lower().split())

        def _score(schema: dict[str, Any]) -> int:
            name = schema.get("name", "").lower().replace("_", " ")
            desc = schema.get("description", "").lower()
            combined = set(name.split()) | set(desc.split())
            return len(query_tokens & combined)

        scored = sorted(all_schemas, key=_score, reverse=True)
        result = scored[:max_tools]
        _log.debug(
            "[TOOL_ROUTING] registry=%d query=%r selected=%d/%d",
            total, query[:60], len(result), total,
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
