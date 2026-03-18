import asyncio
import logging
import signal
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from api.routes.chat import chat_router
from api.routes.health import router as health_router
from api.routes.memory import router as memory_router
from api.routes.observability import router as obs_router
from api.routes.observability import set_collector
from api.routes.skills import router as skills_router
from api.routes.telemetry import router as telemetry_router
from channels.terminal import TerminalChannel
from channels.telegram_channel import TelegramChannel
from channels.discord_channel import DiscordChannel
from core.agent import Agent
from core.alerting import AlertNotifier
from core.config import Settings
from core.heartbeat import HeartbeatSystem
from core.llm import LLMGateway
from core.telemetry import EventBus, EventCollector
from memory.lesson_extractor import LessonExtractor
from memory.memory_manager import MemoryManager
from memory.semantic_extractor import SemanticExtractor
from memory.summarizer import ConversationSummarizer
from memory.vector_store import VectorStore
from heartbeat.integrations.reflection_task import ReflectionTask
from heartbeat.integrations.system_health import SystemHealthProbe
from heartbeat.integrations.deadman_switch import DeadManSwitch
import skills.local.filesystem  # noqa: F401 — registers read_file, write_file
import skills.local.system  # noqa: F401 — registers run_command, run_code
import skills.local.meta  # noqa: F401 — registers create_skill
import skills.local.generated  # noqa: F401 — auto-loads agent-generated skills
from skills.executor import SkillExecutor
from skills.registry import _default_registry as registry

# Settings must be loaded first so log_level is available for basicConfig
settings = Settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("main")

# Instantiate Core Components
event_bus = EventBus()
collector = EventCollector(event_bus, "agent.db")
llm = LLMGateway(settings=settings, event_bus=event_bus)
logger.info("Initializing Memory Manager & Downloading Embedding Models (this may take ~1 minute on first run)...")
vector_store = VectorStore(location=settings.data_dir)
memory = MemoryManager(vector_store=vector_store, event_bus=event_bus)
executor = SkillExecutor(registry=registry, event_bus=event_bus)
semantic_extractor = SemanticExtractor(
    llm=llm,
    memory=memory,
    event_bus=event_bus,
    similarity_threshold=settings.semantic_similarity_threshold,
) if settings.semantic_extraction_enabled else None
summarizer = ConversationSummarizer(
    llm=llm,
    memory=memory,
    event_bus=event_bus,
    turn_threshold=settings.summarization_turn_threshold,
) if settings.summarization_enabled else None
lesson_extractor = LessonExtractor(
    llm=llm,
    memory=memory,
    event_bus=event_bus,
) if settings.lesson_extraction_enabled else None
agent = Agent(
    llm=llm,
    memory=memory,
    event_bus=event_bus,
    semantic_extractor=semantic_extractor,
    summarizer=summarizer,
    lesson_extractor=lesson_extractor,
)
heartbeat = HeartbeatSystem(event_bus=event_bus)
alert_notifier = AlertNotifier(settings)
system_health_probe = SystemHealthProbe(event_bus=event_bus)
dead_man_switch = DeadManSwitch(
    event_bus=event_bus,
    on_restart=heartbeat.restart,
    alert_notifier=alert_notifier,
    max_restart_attempts=3,
)
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
    heartbeat.register_default_tasks(
        system_health_probe=system_health_probe,
        dead_man_switch=dead_man_switch,
    )
    reflection_task = ReflectionTask(
        llm=llm,
        event_bus=event_bus,
        consolidation_threshold=settings.lesson_consolidation_threshold,
    )
    heartbeat.register_integration(reflection_task)
    heartbeat.start()

    # Inject dependencies into FastAPI request state
    app.state.agent = agent
    app.state.event_bus = event_bus
    app.state.collector = collector
    app.state.memory = memory
    app.state.skill_executor = executor
    app.state.llm = llm
    app.state.heartbeat = heartbeat
    app.state.dead_man_switch = dead_man_switch

    yield

    logger.info("Shutting down Agent Backend...")
    heartbeat.shutdown()
    if hasattr(app.state, "telemetry_task"):
        app.state.telemetry_task.cancel()
    await collector.close()


# FastAPI application (for dashboard, HTTP channels, webhooks)
app = FastAPI(lifespan=lifespan, title="dolOS API")
app.include_router(chat_router, prefix="/api")
app.include_router(health_router, prefix="/api")
app.include_router(memory_router, prefix="/api")
app.include_router(obs_router, prefix="/api")
app.include_router(skills_router, prefix="/api")
app.include_router(telemetry_router, prefix="/api")


def _cancel_background_tasks(background_tasks: list, server_task: asyncio.Task) -> None:
    for t in background_tasks:
        if t is not server_task:
            t.cancel()


async def main() -> None:
    """Main entry point representing the agent process boot up."""
    logger.info("Booting dolOS...")

    config = uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="warning")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    background_tasks = [server_task]

    # Start Telegram if configured
    if settings.telegram_bot_token:
        telegram_channel = TelegramChannel(agent, event_bus, settings.telegram_bot_token.get_secret_value())
        background_tasks.append(asyncio.create_task(telegram_channel.start()))

    # Start Discord if configured
    if settings.discord_bot_token:
        discord_channel = DiscordChannel(agent, event_bus, settings.discord_bot_token.get_secret_value())
        background_tasks.append(asyncio.create_task(discord_channel.start()))

    if sys.stdin.isatty():
        # Interactive mode: terminal channel controls shutdown
        await asyncio.sleep(2.0)
        try:
            await terminal.start()
        except (KeyboardInterrupt, EOFError):
            pass
        finally:
            logger.info("Terminal session exited. Shutting down...")
            server.should_exit = True
            _cancel_background_tasks(background_tasks, server_task)
            try:
                await asyncio.wait([server_task], timeout=5.0)
            except Exception:
                pass
    else:
        # Headless mode (systemd / CI): wait for SIGTERM or server crash
        logger.info("Running in headless mode. Send SIGTERM to stop.")
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()

        def _handle_sigterm() -> None:
            logger.info("SIGTERM received. Shutting down...")
            stop_event.set()

        loop.add_signal_handler(signal.SIGTERM, _handle_sigterm)

        done, _ = await asyncio.wait(
            [server_task, asyncio.create_task(stop_event.wait())],
            return_when=asyncio.FIRST_COMPLETED,
        )

        server.should_exit = True
        _cancel_background_tasks(background_tasks, server_task)
        try:
            await asyncio.wait([server_task], timeout=5.0)
        except Exception:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
