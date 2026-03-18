# 012 Reinforcement Learning & Lessons Learned

Implement a "Lessons Learned" mechanism enabling the agent to identify mistakes, capture behavioral corrections, and store them in `data/LESSONS.md`. This file should be injected into the system prompt to prevent recurring errors.

## Acceptance Criteria
- [ ] Implement `LessonExtractor` to identify mistakes/lessons from conversation turns.
- [ ] Update `Agent` to run lesson extraction as a background task.
- [ ] Create `data/LESSONS.md` and ensure it is dynamically injected into the system prompt.
- [ ] Implement a `ReflectionTask` in the heartbeat system to summarize and consolidate lessons.
- [ ] Verify that lessons are correctly applied in subsequent sessions.

## Methodology
- **TDD Iron Law:** NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST.
- Use the background task pattern for extraction to avoid latency in chat.
