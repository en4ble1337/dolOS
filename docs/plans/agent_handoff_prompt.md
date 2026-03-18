# dolOS Project Context for Hand-off Prompt

You are an agent operating on the `dolOS` codebase. This architectural implementation is a local-first AI agent optimized for Ollama and local telemetry. I am handing this codebase off to you to continue development on Phase 2.

## Important Context & State
- **Phase 1 backend is 100% complete!** Scaffolded services, Memory (`Qdrant`/`SentenceTransformers`), LLM integration (`LiteLLM`/`Ollama`), Core Agent orchestrator, skills framework, and telemetry backend (`EventBus`, `EventCollector`) are fully tested and functional.
- The `AGENTS.md` file defines your core directives and absolute ground rules. **Read `AGENTS.md` before doing anything.**
- The project is fully test-driven via `pytest`. **We enforce a strict TDD Iron Law: No production code without a failing test first!**
- Your primary command center for the next tasks is located in `docs/`.

## Immediate Next Steps
The backend is ready to be hooked up to an Observability Dashboard and extended with Tools.

1. Read `README.md` and `AGENTS.md` to understand your role and constraints.
2. We have a fully functional backend API in `main.py` which exposes WebSocket telemetry via `api/routes/observability.py`.
3. Pick up either **Directive 010 (Observability Dashboard)** or **Directive 011 (Tools & MCP Integration)** depending on whether you want to start with React UI work or Agent Arm/Leg tooling work. Read the chosen directive file in the `docs/` folder.
4. Execute strictly according to `AGENTS.md`. Generate your Implementation Plan in `docs/plans/` before writing any tests/code.

Do not break the `main.py` loop structure or existing test suites! 
Good luck building the remaining framework!
