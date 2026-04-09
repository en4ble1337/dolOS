# Dashboard Contract Fix Implementation Plan

**Directive:** N/A (no `directives/` directory exists in this repo)
**Date:** 2026-04-06
**Goal:** Repair the `dolOS` dashboard so the frontend consumes the backend's actual telemetry WebSocket payload shape.
**Architecture Notes:** Keep the FastAPI telemetry payload as the source of truth and normalize data in the frontend. Do not create a second backend-specific event envelope just to satisfy the current UI. Use a small pure helper in `ui/src/lib/telemetry.ts` so the contract can be tested without browser-only tooling.

---

### Task 1: Add Failing Frontend Contract Test

**Files:**
- Create/Modify: `ui/tests/lib/telemetry-contract.test.ts`
- Create/Modify: `ui/src/lib/telemetry.ts`

**Step 1:** Write failing test
- File: `ui/tests/lib/telemetry-contract.test.ts`
- Code: Add Node-based contract tests that import `ui/src/lib/telemetry.ts` as a namespace and assert:
  - `normalizeIncomingTelemetryMessage` exists
  - it accepts a flat backend event payload
  - it converts Unix-second timestamps to ISO strings
  - it derives a stable `event_id`
  - `buildTelemetryWebSocketUrl` exists and builds a URL from the current page origin
- Run: `node_modules\\.bin\\tsc.cmd --outDir .tmp-tests --module NodeNext --moduleResolution NodeNext --target ES2023 --jsx react-jsx --lib ES2023,DOM,DOM.Iterable --types node src/lib/telemetry.ts tests/lib/telemetry-contract.test.ts`
- Run: `node --test .tmp-tests/tests/lib/telemetry-contract.test.js`
- Expected: test compilation succeeds, test run fails with assertion failures because the exports/behavior do not exist yet.

**Step 2:** Implement minimum code
- File: `ui/src/lib/telemetry.ts`
- Code: Add pure helpers to:
  - build a relative WebSocket URL using the active page URL
  - normalize both flat and wrapped telemetry payloads
  - convert numeric timestamps from Unix seconds into ISO strings
  - derive a stable `event_id` when the backend does not send one
- Run: `node_modules\\.bin\\tsc.cmd --outDir .tmp-tests --module NodeNext --moduleResolution NodeNext --target ES2023 --jsx react-jsx --lib ES2023,DOM,DOM.Iterable --types node src/lib/telemetry.ts tests/lib/telemetry-contract.test.ts`
- Run: `node --test .tmp-tests/tests/lib/telemetry-contract.test.js`
- Expected: all contract tests pass.

### Task 2: Wire UI Components To The Normalized Model

**Files:**
- Create/Modify: `ui/src/lib/telemetry.ts`
- Create/Modify: `ui/src/App.tsx`
- Create/Modify: `ui/src/components/Waterfall.tsx`
- Create/Modify: `ui/src/components/HeartbeatGrid.tsx`

**Step 1:** Update the WebSocket hook
- File: `ui/src/lib/telemetry.ts`
- Code: Use the new normalization helper in `ws.onmessage`; drop the hardcoded `ws://localhost:8000` URL in favor of the URL builder; ignore malformed messages safely.
- Run: `npm run build`
- Expected: Vite/TypeScript build succeeds.

**Step 2:** Remove dependence on missing backend-only fields
- File: `ui/src/App.tsx`
- File: `ui/src/components/Waterfall.tsx`
- File: `ui/src/components/HeartbeatGrid.tsx`
- Code: Use normalized `event_id` everywhere instead of assuming the backend provides one.
- Run: `npm run build`
- Expected: Vite/TypeScript build succeeds.

### Task 3: Verification

**Files:**
- Create/Modify: `ui/src/lib/telemetry.ts`
- Create/Modify: `ui/src/App.tsx`
- Create/Modify: `ui/src/components/Waterfall.tsx`
- Create/Modify: `ui/src/components/HeartbeatGrid.tsx`
- Create/Modify: `ui/tests/lib/telemetry-contract.test.ts`

**Step 1:** Run targeted contract test
- Run: `node_modules\\.bin\\tsc.cmd --outDir .tmp-tests --module NodeNext --moduleResolution NodeNext --target ES2023 --jsx react-jsx --lib ES2023,DOM,DOM.Iterable --types node src/lib/telemetry.ts tests/lib/telemetry-contract.test.ts`
- Run: `node --test .tmp-tests/tests/lib/telemetry-contract.test.js`
- Expected: all tests pass.

**Step 2:** Run frontend build verification
- Run: `npm run build`
- Expected: build completes successfully with no TypeScript errors.
