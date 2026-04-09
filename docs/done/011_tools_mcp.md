# Directive 011: Tools & MCP Integration

## Objective
Expand the agent's capabilities by implementing the actual tools defined in the `features.md` document, utilizing the `SkillRegistry` and `SkillExecutor` we already built. Crucially, integrate the Model Context Protocol (MCP) to access generic system-level resources.

## Context
We built a robust execution sandbox in Directive 008, and the backend orchestrator supports tool calling natively via Ollama/LiteLLM. Now the agent needs some actual arms and legs!

## Acceptance Criteria
- [x] Implement a **File System Skill** permitting safe reading/writing of localized directories for the agent to use.
- [x] Implement a **System Command Skill** (subprocess) carefully sandboxed.
- [x] Add the `mcp-core` library dependencies, and build a generic Python MCP Client wrapper under `tools/mcp_client.py`.
- [x] Bind standard MCP servers (like the official file system server or sqlite server) into our `SkillRegistry` dynamically, mapping MCP interfaces tightly to our `SkillExecutor` logic.
- [x] Emit robust `TOOL_INVOKE`, `TOOL_ERROR`, and `TOOL_COMPLETE` telemetry covering MCP queries.
- [x] Test the integration by having the LLM query a simulated filesystem via the agent terminal interface.

## Methodology
- **TDD Iron Law:** NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST.
- Write an implementation plan first (`docs/plans/...`).
