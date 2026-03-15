# Systematic Debugging Guide

## Purpose

When something breaks, resist the urge to guess-and-fix. Follow the 4-phase process to find and fix the actual root cause, not just the symptom.

## Phase 1: Root Cause Investigation

Before changing any code:

1. **Read the error carefully.** The full error message, stack trace, and any logs. Not a glance — a careful read.
2. **Reproduce consistently.** If you can't reproduce it on demand, you don't understand it yet.
3. **Check recent changes.** What was the last change before this broke? Start there.
4. **Trace backward.** Start at the symptom (the error). Ask: "What called this with the bad value?" Trace up the call stack until you find where the bad data originated.
5. **Log at boundaries.** In multi-component systems, add logging at every component boundary (API entry, service call, DB query) to isolate which layer introduced the problem.

## Phase 2: Pattern Analysis

1. **Find working examples.** Is there similar code in the codebase that works? Read it completely — don't skim.
2. **Compare differences.** What's different between the working code and the broken code?
3. **Check documentation.** Does the library/framework documentation say something you missed?

## Phase 3: Hypothesis and Testing

1. **Form ONE hypothesis.** "I think [symptom] happens because [cause]."
2. **Test with the smallest possible change.** One variable at a time.
3. **If wrong:** Form a NEW hypothesis. Do NOT stack multiple changes — revert and try again.
4. **If right:** Proceed to Phase 4.

**Do not guess.** Do not try random fixes. Do not change multiple things at once.

## Phase 4: Implementation

1. **Write a failing test** that reproduces the bug.
2. **Fix with a single, targeted change.**
3. **Run ALL tests** (not just the new one) to confirm no regressions.
4. **Add defense-in-depth validation** to prevent this class of bug from recurring:
   - Entry point validation (reject bad input early)
   - Business logic assertions (verify assumptions explicitly)
   - Clear error messages that point to the cause

## The 3-Strikes Rule

If 3 consecutive fix attempts fail: **STOP.**

Before attempting a 4th fix, answer these questions:
- "Is this architecture fundamentally sound, or am I fighting the design?"
- "Am I fixing the root cause or a downstream symptom?"
- "Should I discuss this with the team before continuing?"

If you can't confidently answer all three, escalate to a human.

## Common Debugging Anti-Patterns

| Anti-Pattern | What To Do Instead |
|-------------|-------------------|
| Guessing and trying random fixes | Form a hypothesis, test one variable at a time |
| Changing multiple things at once | Revert all, change one thing, verify |
| Fixing the symptom not the cause | Trace backward to the source of bad data |
| "It works on my machine" | Check environment differences systematically |
| Adding try/catch to suppress errors | Fix the cause; errors exist for a reason |
| Reading the error too quickly | Read it word by word, including the full stack trace |
