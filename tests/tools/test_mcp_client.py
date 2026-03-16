import pytest
from unittest.mock import AsyncMock, MagicMock

from mcp import StdioServerParameters
from tools.mcp_client import MCPClientWrapper
from core.telemetry import EventBus, EventType
from skills.registry import SkillRegistry

@pytest.fixture
def event_bus():
    return EventBus()

@pytest.fixture
def registry():
    return SkillRegistry()

@pytest.fixture
def server_params():
    return StdioServerParameters(command="dummy", args=[])

@pytest.mark.asyncio
async def test_mcp_client_connect_and_bind(event_bus, registry, server_params):
    client = MCPClientWrapper(server_params, event_bus, registry)

    # Mock the underlying MCP session
    mock_session = AsyncMock()
    
    mock_tool = MagicMock()
    mock_tool.name = "mcp_dummy_tool"
    mock_tool.description = "A dummy tool"
    mock_tool.inputSchema = {"type": "object", "properties": {"arg1": {"type": "string"}}}
    
    mock_list_tools_result = MagicMock()
    mock_list_tools_result.tools = [mock_tool]
    
    mock_session.list_tools.return_value = mock_list_tools_result
    
    client.session = mock_session
    
    await client.bind_tools()
    
    assert "mcp_dummy_tool" in registry.get_all_skill_names()
    schema = registry.get_schema("mcp_dummy_tool")
    assert schema["name"] == "mcp_dummy_tool"
    assert "arg1" in schema["parameters"]["properties"]

@pytest.mark.asyncio
async def test_mcp_client_call_tool(event_bus, registry, server_params):
    client = MCPClientWrapper(server_params, event_bus, registry)
    
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.content = [MagicMock(text="success output")]
    mock_session.call_tool.return_value = mock_result
    
    client.session = mock_session
    
    result = await client.call_tool("mcp_dummy_tool", {"arg1": "val"})
    assert result == ["success output"]
    
    mock_session.call_tool.assert_called_once_with("mcp_dummy_tool", arguments={"arg1": "val"})
    
    # Check telemetry
    # We should have TOOL_INVOKE and TOOL_COMPLETE
    assert event_bus._queue.qsize() == 2
    invoke_event = await event_bus._queue.get()
    assert invoke_event.event_type == EventType.TOOL_INVOKE
    assert invoke_event.payload["tool_name"] == "mcp_dummy_tool"
    
    complete_event = await event_bus._queue.get()
    assert complete_event.event_type == EventType.TOOL_COMPLETE
    assert complete_event.payload["tool_name"] == "mcp_dummy_tool"
