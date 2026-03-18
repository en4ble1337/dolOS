"""System health probe heartbeat integration.

Checks local system status including disk space, memory usage, and CPU load.
Uses ``psutil`` when available for richer metrics; falls back to
``shutil.disk_usage`` and ``os`` stdlib for basic disk info.
"""

from __future__ import annotations

import logging
import os
import shutil
from typing import Any

from core.telemetry import EventBus

from heartbeat.integrations.base import HeartbeatIntegration

logger = logging.getLogger(__name__)

# Attempt to import psutil; gracefully degrade if unavailable.
try:
    import psutil  # type: ignore[import-untyped]

    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

# Default thresholds (percentages)
_DEFAULT_DISK_WARN_PCT = 90.0
_DEFAULT_MEMORY_WARN_PCT = 90.0
_DEFAULT_CPU_WARN_PCT = 90.0


class SystemHealthProbe(HeartbeatIntegration):
    """Probes local system resources and reports utilisation metrics.

    When ``psutil`` is installed the probe reports disk, memory, and CPU
    usage.  Without ``psutil`` only disk usage is reported (via the stdlib).

    Attributes:
        disk_path: Filesystem path to check for disk usage (default ``/``).
        disk_warn_pct: Emit a warning when disk usage exceeds this %.
        memory_warn_pct: Emit a warning when memory usage exceeds this %.
        cpu_warn_pct: Emit a warning when CPU usage exceeds this %.
    """

    name: str = "system_health"

    def __init__(
        self,
        event_bus: EventBus,
        disk_path: str = "/",
        disk_warn_pct: float = _DEFAULT_DISK_WARN_PCT,
        memory_warn_pct: float = _DEFAULT_MEMORY_WARN_PCT,
        cpu_warn_pct: float = _DEFAULT_CPU_WARN_PCT,
    ) -> None:
        super().__init__(event_bus)
        self.disk_path = disk_path
        self.disk_warn_pct = disk_warn_pct
        self.memory_warn_pct = memory_warn_pct
        self.cpu_warn_pct = cpu_warn_pct

    async def check(self) -> dict[str, Any]:
        """Run the system health check and return a status payload."""
        result: dict[str, Any] = {
            "psutil_available": _HAS_PSUTIL,
            "warnings": [],
        }

        # -- Disk --------------------------------------------------------
        disk = self._check_disk()
        result["disk"] = disk
        if disk["used_pct"] >= self.disk_warn_pct:
            msg = f"Disk usage at {disk['used_pct']:.1f}% (threshold {self.disk_warn_pct}%)"
            result["warnings"].append(msg)
            logger.warning(msg)

        # -- Memory (psutil only) ----------------------------------------
        if _HAS_PSUTIL:
            mem = self._check_memory()
            result["memory"] = mem
            if mem["used_pct"] >= self.memory_warn_pct:
                msg = f"Memory usage at {mem['used_pct']:.1f}% (threshold {self.memory_warn_pct}%)"
                result["warnings"].append(msg)
                logger.warning(msg)

        # -- CPU (psutil only) -------------------------------------------
        if _HAS_PSUTIL:
            cpu = self._check_cpu()
            result["cpu"] = cpu
            if cpu["usage_pct"] >= self.cpu_warn_pct:
                msg = f"CPU usage at {cpu['usage_pct']:.1f}% (threshold {self.cpu_warn_pct}%)"
                result["warnings"].append(msg)
                logger.warning(msg)

        # -- Load average (Unix, best-effort) ----------------------------
        load = self._check_load_average()
        if load is not None:
            result["load_avg"] = load

        result["status"] = "warning" if result["warnings"] else "healthy"
        return result

    # -- Private helpers -------------------------------------------------

    def _check_disk(self) -> dict[str, Any]:
        """Return disk usage for ``self.disk_path``."""
        usage = shutil.disk_usage(self.disk_path)
        used_pct = (usage.used / usage.total) * 100 if usage.total > 0 else 0.0
        return {
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "used_pct": round(used_pct, 2),
        }

    @staticmethod
    def _check_memory() -> dict[str, Any]:
        """Return virtual memory stats via psutil."""
        vm = psutil.virtual_memory()
        return {
            "total_bytes": vm.total,
            "available_bytes": vm.available,
            "used_pct": round(vm.percent, 2),
        }

    @staticmethod
    def _check_cpu() -> dict[str, Any]:
        """Return CPU usage percentage via psutil (non-blocking, 0-sec interval)."""
        usage = psutil.cpu_percent(interval=0)
        return {
            "usage_pct": round(usage, 2),
            "core_count": psutil.cpu_count(logical=True),
        }

    @staticmethod
    def _check_load_average() -> dict[str, float] | None:
        """Return 1/5/15-minute load averages if the OS supports it."""
        if not hasattr(os, "getloadavg"):
            return None
        try:
            load1, load5, load15 = os.getloadavg()
            return {"1min": round(load1, 2), "5min": round(load5, 2), "15min": round(load15, 2)}
        except OSError:
            return None
