import asyncio
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from core.telemetry import EventBus, Event, EventType
from skills.registry import SkillRegistry


class MCPClientWrapper:
    """A wrapper for interacting with MCP servers and mapping their tools to the SkillRegistry."""
    
    def __init__(self, server_params: StdioServerParameters, event_bus: EventBus, registry: SkillRegistry) -> None:
        self.server_params = server_params
        self.event_bus = event_bus
        self.registry = registry
        self.exit_stack = AsyncExitStack()
        self.session: ClientSession | None = None

    async def connect(self) -> None:
        """Connect to the MCP server via stdio and initialize the session."""
        stdio_transport = await self.exit_stack.enter_async_context(stdio_client(self.server_params))
        self.stdio, self.write = stdio_transport
        self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))
        await self.session.initialize()

    async def list_tools(self) -> Any:
        """List available tools from the MCP server."""
        if not self.session:
            raise RuntimeError("Not connected to MCP server")
        return await self.session.list_tools()

    async def call_tool(self, name: str, arguments: dict[str, Any], trace_id: str | None = None) -> Any:
        """Execute a tool on the MCP server, with telemetry emitted."""
        if not self.session:
            raise RuntimeError("Not connected to MCP server")

        await self.event_bus.emit(
            Event(
                event_type=EventType.TOOL_INVOKE,
                component="tools.mcp_client",
                trace_id=trace_id or "pending",
                payload={"tool_name": name, "arguments": arguments},
            )
        )

        try:
            result = await self.session.call_tool(name, arguments=arguments)
            # mcp results usually contain a list of content objects
            output = [c.text for c in result.content if hasattr(c, "text")]
            
            await self.event_bus.emit(
                Event(
                    event_type=EventType.TOOL_COMPLETE,
                    component="tools.mcp_client",
                    trace_id=trace_id or "pending",
                    payload={"tool_name": name, "result": str(output)[:500]},
                )
            )
            return output
        except Exception as e:
            await self.event_bus.emit(
                Event(
                    event_type=EventType.TOOL_ERROR,
                    component="tools.mcp_client",
                    trace_id=trace_id or "pending",
                    payload={"tool_name": name, "error": str(e)},
                    success=False,
                )
            )
            raise e

    async def bind_tools(self) -> None:
        """Discover tools from the MCP server and bind them into the provided SkillRegistry."""
        tools_result = await self.list_tools()
        for tool in tools_result.tools:
            # Create a closure to capture tool.name properly
            def make_tool_func(tool_name: str) -> Any:
                async def mcp_tool_wrapper(**kwargs: Any) -> Any:
                    return await self.call_tool(tool_name, kwargs)
                mcp_tool_wrapper.__name__ = tool_name
                mcp_tool_wrapper.__doc__ = tool.description
                return mcp_tool_wrapper

            func = make_tool_func(tool.name)
            
            self.registry.register(
                name=tool.name,
                description=tool.description or f"MCP Tool {tool.name}",
                func=func,
                input_schema=tool.inputSchema
            )

    async def close(self) -> None:
        """Close the MCP session and underlying transports."""
        await self.exit_stack.aclose()
