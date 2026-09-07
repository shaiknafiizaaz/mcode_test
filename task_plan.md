# Rule integrity and offline completion plan

## Goal
Implement requirements 35–42 in the existing application.

## Phases
- [x] Inspect existing architecture and baseline tests (90 passed).
- [ ] Move contextual mappings into authoritative JSON; validate schema and precedence at startup.
- [ ] Fix contextual value extraction, priority ties, and phone association; add regressions.
- [ ] Exercise offline APIs, persistence, mock practice, acceptance BOL, and actual server startup.
- [ ] Generate audit_report.json from measured results and report completion gate.

## Next Step
Migrate existing rule metadata into JSON and add validation.

## Design
Retain parser, deterministic pipeline, UI and SQLite storage. Store reference patterns, service directions, timing rules, roles and display ordering in the authoritative dataset. Python interprets these declarative rules. Use explicit numeric priority and preserve equal-strength conflicts. Keep MM, payment and description engines separate. Test network-denied core behavior with an isolated database; probe optional Ollama separately for the audit.
