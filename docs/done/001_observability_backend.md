# Directive 001: Observability Backend

## Objective

Build the observability backend (Phase A) described in `docs/features-assessment.md` including the EventBus, Event types, and SQLite persistence.

## Dependencies

- None. (This is a foundation layer).

## Acceptance Criteria

- [x] `core/telemetry.py` is created.
- [x] `EventType` enum is defined with all events mentioned in features doc.
- [x] `Event` dataclass is defined and supports standard event payloads + trace IDs.
- [x] `EventBus` class is implemented using `asyncio.Queue` (with both async and sync emission).
- [x] `EventCollector` is implemented to consume the queue and write to an `aiosqlite` database (`events`, `metrics`, `traces` tables).
- [x] Tests exist for all the telemetry and event bus logic.
- [x] SQLite tables are created transparently when the Collector starts.

## Development Methodology

All work follows the processes defined in AGENTS.md:
- **Implementation Planning** before coding
- **TDD Iron Law** during coding
- **Review Gates** after each task
- **Verification Before Completion** before marking done

## Status: [ ] Incomplete / [ ] Complete

## Notes

- Remember to add `aiosqlite` to the requirements/pyproject.toml if not already there, as it's the only new dependency.
