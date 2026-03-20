# Architecture Review

**Date:** 2026-03-20
**Overall Verdict:** GOOD — well-designed with targeted refactoring opportunities

## ADR Compliance: STRONG

All 14 accepted ADRs are satisfied. No critical deviations. The 19-ADR
documentation set is exemplary.

## Key Strengths

- **Canonical AbiSnapshot model** — single interchange format across all
  pipeline stages
- **Fail-safe verdict system** — unclassified ChangeKinds default to BREAKING
  (ADR-009)
- **Strong security posture** — defusedxml, path traversal checks, safe YAML,
  no eval/exec
- **Comprehensive testing** — 125 test modules, 63 example cases, 4-tier test
  architecture
- **Clean cross-platform design** — independent ELF/PE/Mach-O modules, no
  forced abstraction

## Issues Found (by priority)

| Priority | Issue | Impact |
|----------|-------|--------|
| Critical | Missing service layer — cli.py (27 deps) and mcp_server.py (15 deps) duplicate orchestration logic | Maintainability, embeddability |
| High | checker.py monolith (3,830 LOC) — mixes detection, filtering, classification | Testability, merge conflicts |
| High | Inconsistent error handling — 87 raw ValueError/RuntimeError across 21 files despite custom exception hierarchy | Debuggability |
| Medium | Unused Detector protocol in detectors.py — checker.py uses _DetectorSpec instead | Dead code |
| Medium | cli.py sprawl (1,970 LOC, 10+ subcommands) | Maintainability |
| Low | Circular import checker → suppression (guarded by TYPE_CHECKING) | Design smell |
| Low | No formal ADR for MCP server (already tracked in gap analysis) | Documentation |

## Refactoring Plan

See [refactoring-spec.md](refactoring-spec.md) for the 4-phase implementation plan.

### Implementation Status

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Break circular dependency & clean up types | ✅ Complete |
| 2 | Split checker.py into focused modules | 🔄 In progress |
| 3 | Extract service layer | Planned |
| 4 | Standardize error handling | ✅ Complete |
