import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from api.routes.chat import chat_router
from api.routes.observability import router as obs_router
from api.routes.observability import set_collector
from channels.terminal import TerminalChannel
from core.agent import Agent
from core.config import Settings
from core.heartbeat import HeartbeatSystem
from core.llm import LLMGateway
from core.telemetry import EventBus, EventCollector
from memory.memory_manager import MemoryManager
from skills.executor import SkillExecutor
from skills.registry import SkillRegistry

# Set up simple logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("main")

# Instantiate Core Components
event_bus = EventBus()
collector = EventCollector(event_bus, "agent.db")
settings = Settings()
llm = LLMGateway(settings=settings, event_bus=event_bus)
logger.info("Initializing Memory Manager & Downloading Embedding Models (this may take ~1 minute on first run)...")
memory = MemoryManager(event_bus=event_bus)
registry = SkillRegistry()
executor = SkillExecutor(registry=registry, event_bus=event_bus)
agent = Agent(
    llm=llm,
    memory=memory,
    event_bus=event_bus
)
heartbeat = HeartbeatSystem(event_bus=event_bus)
terminal = TerminalChannel(agent, event_bus)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing Agent Backend...")
    
    # Start Event Collector
    await collector.initialize()
    set_collector(collector)
    await collector.start_background_tasks()
    
    # Event Collector Loop
    async def process_telemetry() -> None:
        while True:
            try:
                await collector.process_one()
            except Exception as e:
                logger.error(f"Telemetry collector error: {e}")

    app.state.telemetry_task = asyncio.create_task(process_telemetry())
    
    # Start Heartbeat
    logger.info("Starting up Proactive Heartbeat System...")
    heartbeat.register_default_tasks(memory_manager=memory, llm_gateway=llm)
    heartbeat.start()
    
    # Inject dependencies into FastAPI request state
    app.state.agent = agent
    app.state.event_bus = event_bus

    yield
    
    logger.info("Shutting down Agent Backend...")
    heartbeat.shutdown()
    if hasattr(app.state, "telemetry_task"):
        app.state.telemetry_task.cancel()
    await collector.close()

# FastAPI application (for dashboard, HTTP channels, webhooks)
app = FastAPI(lifespan=lifespan, title="My Local Agent API")
app.include_router(chat_router, prefix="/api")
app.include_router(obs_router, prefix="/api")

async def main() -> None:
    """Main entry point representing the agent process boot up."""
    logger.info("Booting My Local Agent...")
    
    # Start the fast api server as a background task
    config = uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="warning")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    
    # Wait for the API to boot before starting the terminal
    await asyncio.sleep(2.0)
    
    # Start terminal UI - this will block until the user types exit
    try:
        await terminal.start()
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        logger.info("Terminal session exited. System shutting down...")
        server.should_exit = True
        await asyncio.wait([server_task])

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
