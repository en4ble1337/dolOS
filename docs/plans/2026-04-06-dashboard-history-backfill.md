# Dashboard History Backfill Implementation Plan

**Directive:** N/A (no `directives/` directory exists in this repo)
**Date:** 2026-04-06
**Goal:** Load recent telemetry history into the dashboard before live WebSocket events arrive.
**Architecture Notes:** Keep this frontend-only. Reuse the same normalized `TelemetryEvent` shape for both REST and WebSocket data so all UI components continue to render from one event model. Add pure helpers in `ui/src/lib/telemetry.ts` for URL building, payload normalization, and de-duplicating merge behavior.

---

### Task 1: Add Failing Contract Checks For History Backfill

**Files:**
- Create/Modify: `ui/tests/lib/telemetry-contract.test.ts`
- Create/Modify: `ui/src/lib/telemetry.ts`

**Step 1:** Write failing test
- File: `ui/tests/lib/telemetry-contract.test.ts`
- Code: Add assertions that:
  - `buildTelemetryRecentEventsUrl` exists and builds `/api/events/recent?limit=...`
  - `normalizeTelemetryHistoryPayload` exists and converts a REST array into normalized events
  - `mergeTelemetryEvents` exists and deduplicates by `event_id` while keeping newest-first order
- Run: `node_modules\\.bin\\tsc.cmd --outDir .tmp-tests --noEmit false --module NodeNext --moduleResolution NodeNext --target ES2023 --jsx react-jsx --lib ES2023,DOM,DOM.Iterable --types node src/lib/telemetry.ts tests/lib/telemetry-contract.test.ts`
- Run: `node .tmp-tests/tests/lib/telemetry-contract.test.js`
- Expected: test run fails with assertion failures because the exports/behavior do not exist yet.

**Step 2:** Implement minimum code
- File: `ui/src/lib/telemetry.ts`
- Code: Add the three pure helpers and keep them independent of React/browser globals.
- Run: `node_modules\\.bin\\tsc.cmd --outDir .tmp-tests --noEmit false --module NodeNext --moduleResolution NodeNext --target ES2023 --jsx react-jsx --lib ES2023,DOM,DOM.Iterable --types node src/lib/telemetry.ts tests/lib/telemetry-contract.test.ts`
- Run: `node .tmp-tests/tests/lib/telemetry-contract.test.js`
- Expected: all contract checks pass.

### Task 2: Wire Initial REST Backfill Into The Telemetry Hook

**Files:**
- Create/Modify: `ui/src/lib/telemetry.ts`

**Step 1:** Load recent events on hook startup
- File: `ui/src/lib/telemetry.ts`
- Code: Fetch recent events from `/api/events/recent?limit=100` before or alongside the WebSocket connection, normalize them, and merge them into state.
- Run: `node_modules\\.bin\\tsc.cmd -b`
- Expected: TypeScript build passes.

**Step 2:** Merge live events safely
- File: `ui/src/lib/telemetry.ts`
- Code: Use the merge helper when live WebSocket messages arrive so history and live events deduplicate cleanly.
- Run: `node_modules\\.bin\\tsc.cmd -b`
- Expected: TypeScript build passes.

### Task 3: Verification

**Files:**
- Create/Modify: `ui/src/lib/telemetry.ts`
- Create/Modify: `ui/tests/lib/telemetry-contract.test.ts`

**Step 1:** Run contract checks
- Run: `node_modules\\.bin\\tsc.cmd --outDir .tmp-tests --noEmit false --module NodeNext --moduleResolution NodeNext --target ES2023 --jsx react-jsx --lib ES2023,DOM,DOM.Iterable --types node src/lib/telemetry.ts tests/lib/telemetry-contract.test.ts`
- Run: `node .tmp-tests/tests/lib/telemetry-contract.test.js`
- Expected: all checks pass.

**Step 2:** Run frontend build verification
- Run: `npm.cmd run build`
- Expected: production build succeeds.
