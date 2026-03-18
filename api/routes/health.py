"""Health check routes for liveness and deep dependency checks."""

import time
from typing import Any

import aiosqlite
from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Basic liveness check response."""

    status: str
    timestamp: float


class ComponentStatus(BaseModel):
    """Health status for a single component."""

    name: str
    status: str
    latency_ms: float
    detail: str


class DeepHealthResponse(BaseModel):
    """Deep health check response with per-component status."""

    status: str
    timestamp: float
    components: list[ComponentStatus]


async def _check_sqlite(request: Request) -> ComponentStatus:
    """Test SQLite connectivity by running a simple query."""
    start = time.time()
    try:
        collector = getattr(request.app.state, "collector", None)
        if collector is None:
            return ComponentStatus(
                name="sqlite",
                status="warn",
                latency_ms=0.0,
                detail="EventCollector not configured",
            )
        if collector._db is None:
            return ComponentStatus(
                name="sqlite",
                status="unhealthy",
                latency_ms=0.0,
                detail="Database connection not initialized",
            )
        await collector._db.execute("SELECT 1")
        latency = (time.time() - start) * 1000
        return ComponentStatus(
            name="sqlite",
            status="healthy",
            latency_ms=round(latency, 2),
            detail="OK",
        )
    except Exception as e:
        latency = (time.time() - start) * 1000
        return ComponentStatus(
            name="sqlite",
            status="unhealthy",
            latency_ms=round(latency, 2),
            detail=str(e),
        )


async def _check_memory(request: Request) -> ComponentStatus:
    """Test memory store (Qdrant) connectivity."""
    start = time.time()
    try:
        memory = getattr(request.app.state, "memory", None)
        if memory is None:
            return ComponentStatus(
                name="memory",
                status="warn",
                latency_ms=0.0,
                detail="MemoryManager not configured",
            )
        # Check if the vector store client can list collections
        collections = memory.vector_store.client.get_collections()
        latency = (time.time() - start) * 1000
        return ComponentStatus(
            name="memory",
            status="healthy",
            latency_ms=round(latency, 2),
            detail=f"{len(collections.collections)} collection(s) available",
        )
    except Exception as e:
        latency = (time.time() - start) * 1000
        return ComponentStatus(
            name="memory",
            status="unhealthy",
            latency_ms=round(latency, 2),
            detail=str(e),
        )


async def _check_heartbeat(request: Request) -> ComponentStatus:
    """Check heartbeat scheduler and dead man's switch status."""
    heartbeat = getattr(request.app.state, "heartbeat", None)
    dead_man_switch = getattr(request.app.state, "dead_man_switch", None)

    if not heartbeat or not heartbeat.is_running():
        return ComponentStatus(
            name="heartbeat",
            status="unhealthy",
            latency_ms=0.0,
            detail="Scheduler not running",
        )

    if dead_man_switch:
        elapsed = dead_man_switch.last_ping_elapsed
        attempts = dead_man_switch.restart_attempts
        if attempts == 0:
            status = "healthy"
        elif attempts < dead_man_switch.max_restart_attempts:
            status = "degraded"
        else:
            status = "unhealthy"
        detail = f"Last ping {elapsed:.0f}s ago, {attempts} restart attempt(s)"
        return ComponentStatus(name="heartbeat", status=status, latency_ms=0.0, detail=detail)

    return ComponentStatus(
        name="heartbeat",
        status="healthy",
        latency_ms=0.0,
        detail="Running (no switch configured)",
    )


async def _check_llm(request: Request) -> ComponentStatus:
    """Test LLM availability by checking the gateway configuration."""
    start = time.time()
    try:
        llm = getattr(request.app.state, "llm", None)
        if llm is None:
            return ComponentStatus(
                name="llm",
                status="warn",
                latency_ms=0.0,
                detail="LLMGateway not configured",
            )
        # We don't make a real LLM call for health checks — just verify config
        model = llm.settings.primary_model
        latency = (time.time() - start) * 1000
        return ComponentStatus(
            name="llm",
            status="healthy",
            latency_ms=round(latency, 2),
            detail=f"Configured model: {model}",
        )
    except Exception as e:
        latency = (time.time() - start) * 1000
        return ComponentStatus(
            name="llm",
            status="unhealthy",
            latency_ms=round(latency, 2),
            detail=str(e),
        )


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Basic liveness check — always returns 200 if the server is running."""
    return HealthResponse(status="ok", timestamp=time.time())


@router.get("/health/deep", response_model=DeepHealthResponse)
async def deep_health_check(request: Request) -> DeepHealthResponse:
    """Deep health check that tests every dependency.

    Returns per-component status for SQLite, memory store, and LLM availability.
    Overall status is 'healthy' only if all components are healthy.
    """
    components = [
        await _check_sqlite(request),
        await _check_memory(request),
        await _check_llm(request),
        await _check_heartbeat(request),
    ]

    all_healthy = all(c.status == "healthy" for c in components)
    any_unhealthy = any(c.status == "unhealthy" for c in components)

    if all_healthy:
        overall = "healthy"
    elif any_unhealthy:
        overall = "unhealthy"
    else:
        overall = "degraded"

    return DeepHealthResponse(
        status=overall,
        timestamp=time.time(),
        components=components,
    )
