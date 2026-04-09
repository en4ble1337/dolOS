"""Tests for TaskTracker (Gap 6 Phase B).

TDD Red phase — these tests MUST FAIL before core/task_tracker.py exists.
"""
from __future__ import annotations

import pytest

from core.task_tracker import Task, TaskStatus, TaskTracker


# ---------------------------------------------------------------------------
# TaskTracker construction
# ---------------------------------------------------------------------------

class TestTaskTrackerInit:
    def test_instantiates(self):
        tracker = TaskTracker()
        assert tracker is not None

    def test_task_list_empty_initially(self):
        tracker = TaskTracker()
        assert tracker.task_list() == []


# ---------------------------------------------------------------------------
# task_create
# ---------------------------------------------------------------------------

class TestTaskCreate:
    def test_create_returns_non_empty_string_id(self):
        tracker = TaskTracker()
        task_id = tracker.task_create("do something")
        assert isinstance(task_id, str)
        assert len(task_id) > 0

    def test_create_returns_unique_ids(self):
        tracker = TaskTracker()
        id1 = tracker.task_create("task A")
        id2 = tracker.task_create("task B")
        assert id1 != id2

    def test_created_task_appears_in_list(self):
        tracker = TaskTracker()
        task_id = tracker.task_create("my task")
        tasks = tracker.task_list()
        assert len(tasks) == 1
        assert tasks[0].task_id == task_id

    def test_created_task_has_pending_status(self):
        tracker = TaskTracker()
        task_id = tracker.task_create("pending task")
        task = tracker.task_get(task_id)
        assert task.status == TaskStatus.PENDING

    def test_created_task_stores_description(self):
        tracker = TaskTracker()
        task_id = tracker.task_create("describe me")
        task = tracker.task_get(task_id)
        assert task.description == "describe me"

    def test_create_with_metadata(self):
        tracker = TaskTracker()
        task_id = tracker.task_create("with meta", metadata={"source": "test"})
        task = tracker.task_get(task_id)
        assert task.metadata == {"source": "test"}

    def test_create_without_metadata_defaults_empty(self):
        tracker = TaskTracker()
        task_id = tracker.task_create("no meta")
        task = tracker.task_get(task_id)
        assert task.metadata == {}


# ---------------------------------------------------------------------------
# task_update
# ---------------------------------------------------------------------------

class TestTaskUpdate:
    def test_update_status_to_running(self):
        tracker = TaskTracker()
        task_id = tracker.task_create("run me")
        tracker.task_update(task_id, TaskStatus.RUNNING)
        assert tracker.task_get(task_id).status == TaskStatus.RUNNING

    def test_update_status_to_done_with_result(self):
        tracker = TaskTracker()
        task_id = tracker.task_create("finish me")
        tracker.task_update(task_id, TaskStatus.DONE, result="all done")
        task = tracker.task_get(task_id)
        assert task.status == TaskStatus.DONE
        assert task.result == "all done"

    def test_update_status_to_failed_with_error(self):
        tracker = TaskTracker()
        task_id = tracker.task_create("fail me")
        tracker.task_update(task_id, TaskStatus.FAILED, error="something blew up")
        task = tracker.task_get(task_id)
        assert task.status == TaskStatus.FAILED
        assert task.error == "something blew up"

    def test_update_nonexistent_task_raises_key_error(self):
        tracker = TaskTracker()
        with pytest.raises(KeyError):
            tracker.task_update("no-such-id", TaskStatus.DONE)


# ---------------------------------------------------------------------------
# task_get
# ---------------------------------------------------------------------------

class TestTaskGet:
    def test_get_returns_correct_task(self):
        tracker = TaskTracker()
        task_id = tracker.task_create("get me")
        task = tracker.task_get(task_id)
        assert isinstance(task, Task)
        assert task.task_id == task_id

    def test_get_nonexistent_raises_key_error(self):
        tracker = TaskTracker()
        with pytest.raises(KeyError):
            tracker.task_get("non-existent-id")


# ---------------------------------------------------------------------------
# task_list
# ---------------------------------------------------------------------------

class TestTaskList:
    def test_list_returns_all_tasks(self):
        tracker = TaskTracker()
        tracker.task_create("task 1")
        tracker.task_create("task 2")
        tracker.task_create("task 3")
        assert len(tracker.task_list()) == 3

    def test_list_reflects_status_updates(self):
        tracker = TaskTracker()
        task_id = tracker.task_create("update me")
        tracker.task_update(task_id, TaskStatus.RUNNING)
        tasks = tracker.task_list()
        assert tasks[0].status == TaskStatus.RUNNING


# ---------------------------------------------------------------------------
# TaskStatus enum
# ---------------------------------------------------------------------------

class TestTaskStatus:
    def test_all_statuses_accessible(self):
        assert TaskStatus.PENDING == "pending"
        assert TaskStatus.RUNNING == "running"
        assert TaskStatus.DONE == "done"
        assert TaskStatus.FAILED == "failed"
