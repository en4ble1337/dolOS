from pydantic import BaseModel, Field

from skills.registry import SkillRegistry, skill


def test_registry_singleton() -> None:
    """Test that the global registry exists and can be retrieved."""
    registry = SkillRegistry()
    assert registry is not None


def test_basic_skill_registration() -> None:
    """Test registering a simple skill with no arguments."""
    registry = SkillRegistry()

    @skill(
        name="get_current_time",
        description="Returns the current local time.",
        registry=registry,
    )
    def get_current_time() -> str:
        return "12:00:00"

    # Check that it's in the registry
    assert "get_current_time" in registry.get_all_skill_names()

    # Check execution
    func = registry.get_skill("get_current_time")
    assert func() == "12:00:00"

    # Check schema generation
    schema = registry.get_schema("get_current_time")
    assert schema["name"] == "get_current_time"
    assert schema["description"] == "Returns the current local time."
    assert "parameters" in schema
    assert schema["parameters"]["type"] == "object"
    assert schema["parameters"]["properties"] == {}


def test_skill_with_primitive_arguments() -> None:
    """Test registering a skill that takes basic primitive arguments."""
    registry = SkillRegistry()

    @skill(
        name="calculate_sum",
        description="Adds two integers together.",
        registry=registry,
    )
    def calculate_sum(a: int, b: int) -> int:
        return a + b

    schema = registry.get_schema("calculate_sum")

    assert schema["name"] == "calculate_sum"
    props = schema["parameters"]["properties"]

    assert "a" in props
    assert props["a"]["type"] == "integer"
    assert "b" in props
    assert props["b"]["type"] == "integer"

    # Check required fields
    assert "required" in schema["parameters"]
    assert set(schema["parameters"]["required"]) == {"a", "b"}


class WeatherRequest(BaseModel):
    location: str = Field(description="The city and state, e.g. San Francisco, CA")
    unit: str = Field(default="celsius", description="The unit of temperature")


def test_skill_with_pydantic_arguments() -> None:
    """Test registering a skill that takes a Pydantic model."""
    registry = SkillRegistry()

    @skill(
        name="get_weather",
        description="Get the current weather in a given location.",
        registry=registry,
    )
    def get_weather(request: WeatherRequest) -> str:
        return f"Sunny in {request.location}"

    schema = registry.get_schema("get_weather")

    assert schema["name"] == "get_weather"
    props = schema["parameters"]["properties"]

    assert "location" in props
    assert props["location"]["type"] == "string"
    assert "unit" in props
    assert props["unit"]["type"] == "string"
    assert props["unit"]["default"] == "celsius"

    assert "required" in schema["parameters"]
    assert "location" in schema["parameters"]["required"]
    assert "unit" not in schema["parameters"]["required"]
