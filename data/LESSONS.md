# Agent Lessons Learned

<!-- This file is auto-managed. Do not edit manually. -->

## [2026-03-18] Tool use is required for shell commands
**Context:** Agent has run_command, read_file, write_file, run_code tools available via native function calling.
**Lesson:** ALWAYS call run_command to execute shell commands — never tell the user to run them. NEVER write fake or simulated command output like "[Executing command: ...]" in text. Call the tool, get the real output, return it.

---
