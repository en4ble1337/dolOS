# Source Control Cleanup Implementation Plan

**Directive:** ad hoc user request
**Date:** 2026-03-27
**Goal:** Remove local Claude tool state from version control, normalize intentional deployment/doc files, and leave the repository in a clean committed state.
**Architecture Notes:** `.claude/` contains local permission state and ephemeral worktree gitlinks, which should not be versioned. The remaining modified files are deployment-facing (`main.py`, `docker-compose.yml`, `Dockerfile`) and repository docs, so cleanup should preserve them rather than discard them.

---

### Task 1: Capture the current git hygiene problems

**Files:**
- Read: `.gitignore`
- Read: `.claude/settings.json`
- Read: `.claude/settings.local.json`

**Step 1:** Inspect the current git status
- Run: `git status --short`
- Expected: tracked local `.claude` state plus pending deployment/docs files.

**Step 2:** Confirm `.claude` content is local-only
- Run: `Get-Content .claude/settings.json`
- Run: `Get-Content .claude/settings.local.json`
- Expected: machine-specific permission and worktree content, not portable project source.

---

### Task 2: Stop tracking local Claude state

**Files:**
- Modify: `.gitignore`

**Step 1:** Add ignore rules for local Claude state
- File: `.gitignore`
- Action: Ignore `.claude/`.
- Expected: future local Claude artifacts are not surfaced in `git status`.

**Step 2:** Remove tracked `.claude` entries from the git index only
- Run: `git rm -r --cached -- .claude`
- Expected: files are removed from version control but remain on disk.

---

### Task 3: Normalize remaining intentional repo files

**Files:**
- Modify: `docs/integrations.md`
- Stage: `docker-compose.yml`
- Stage: `main.py`
- Stage: `Dockerfile`
- Stage: `TEST_PLAN.md`
- Stage: `docs/manual_test_checklist.md`

**Step 1:** Convert placeholder integration notes into a minimal real doc
- File: `docs/integrations.md`
- Action: Replace bare URLs with a short references document.
- Expected: file is worth tracking.

**Step 2:** Stage the deployment and docs files that represent intentional project work
- Run: `git add .gitignore docker-compose.yml main.py Dockerfile TEST_PLAN.md docs/manual_test_checklist.md docs/integrations.md`
- Expected: only intentional repo content is staged.

---

### Task 4: Verify and commit

**Files:**
- Read: `tests/test_main_headless.py`

**Step 1:** Run targeted runtime verification
- Run: `pytest tests/test_main_headless.py -v`
- Expected: all tests pass.

**Step 2:** Inspect staged files
- Run: `git diff --cached --name-only`
- Expected: no `.claude` paths remain staged except their removals.

**Step 3:** Commit cleanup
- Run: `git commit -m "chore: clean up source control state"`
- Expected: commit succeeds and `git status --short` is clean.
