"""Task Tracker — in-memory task registry for subagent coordination (Gap 6).

Provides a lightweight store for tracking subagent tasks with status
transitions (PENDING → RUNNING → DONE | FAILED).  All operations are
synchronous; thread/coroutine safety is not required for the current
single-process, asyncio-based dolOS architecture.

Usage
-----
    from core.task_tracker import TaskTracker, TaskStatus

    tracker = TaskTracker()
    task_id = tracker.task_create("read and summarise config.yaml")
    tracker.task_update(task_id, TaskStatus.RUNNING)
    tracker.task_update(task_id, TaskStatus.DONE, result="Summary: ...")
    for task in tracker.task_list():
        print(task.task_id, task.status, task.result)
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    """Lifecycle states for a tracked task."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Task:
    """A single tracked task entry.

    Attributes:
        task_id:     UUID string uniquely identifying this task.
        description: Human-readable task description.
        status:      Current lifecycle status.
        result:      Output of the task, set when status is DONE.
        error:       Error message, set when status is FAILED.
        metadata:    Arbitrary key-value metadata (e.g. ``{"source": "user"}``).
    """

    task_id: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class TaskTracker:
    """In-memory registry for tracking subagent task lifecycle.

    Tasks are keyed by UUID string.  All methods are O(1) except
    :meth:`task_list` which is O(n).
    """

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}

    def task_create(
        self,
        description: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Create a new task and return its ID.

        Args:
            description: Human-readable description of the task.
            metadata:    Optional arbitrary metadata dict.

        Returns:
            UUID string identifying the new task.
        """
        task_id = str(uuid.uuid4())
        self._tasks[task_id] = Task(
            task_id=task_id,
            description=description,
            metadata=metadata or {},
        )
        return task_id

    def task_update(
        self,
        task_id: str,
        status: TaskStatus,
        result: Any = None,
        error: str | None = None,
    ) -> None:
        """Update the status (and optionally result/error) of an existing task.

        Args:
            task_id: ID of the task to update.
            status:  New :class:`TaskStatus`.
            result:  Task output (use when transitioning to DONE).
            error:   Error description (use when transitioning to FAILED).

        Raises:
            KeyError: If *task_id* does not exist.
        """
        if task_id not in self._tasks:
            raise KeyError(f"Task '{task_id}' not found.")
        task = self._tasks[task_id]
        task.status = status
        task.result = result
        task.error = error

    def task_get(self, task_id: str) -> Task:
        """Retrieve a task by ID.

        Args:
            task_id: ID of the task to retrieve.

        Returns:
            The :class:`Task` instance.

        Raises:
            KeyError: If *task_id* does not exist.
        """
        if task_id not in self._tasks:
            raise KeyError(f"Task '{task_id}' not found.")
        return self._tasks[task_id]

    def task_list(self) -> list[Task]:
        """Return all tasks as an unordered list.

        Returns:
            List of all :class:`Task` instances (may be empty).
        """
        return list(self._tasks.values())
