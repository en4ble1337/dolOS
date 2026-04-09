# 013 Dashboard Bundle Optimization

Address the Vite production build warning for the dashboard's main JavaScript bundle, which is currently larger than the default 500 kB warning threshold after minification. This is not a correctness issue, but it is a performance concern for initial load, parse time, and long-term UI growth.

## Acceptance Criteria
- [ ] Identify the heaviest dashboard dependencies and components contributing to the initial bundle.
- [ ] Split heavy panels or charting code into lazily loaded chunks where appropriate.
- [ ] Keep the first render focused on the core operator surface and defer non-critical UI code.
- [ ] Re-run the production frontend build and confirm bundle output is improved.
- [ ] Document any intentional remaining bundle-size tradeoffs.

## Methodology
- **TDD Iron Law:** NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST.
- Prefer component-level code splitting over cosmetic build-threshold changes.
- Do not silence the warning by only raising `chunkSizeWarningLimit`; reduce real initial payload unless there is a documented reason not to.
