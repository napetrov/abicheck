# Project Goals

This page is a summary. For the full goal descriptions, milestones, and
progress tracking, see
[GOALS.md](https://github.com/napetrov/abicheck/blob/main/GOALS.md) in the
repository root.

## Status summary

| Goal | Status |
|------|--------|
| G1: ABICC drop-in | Done — 114 ChangeKinds, compat CLI, suppression files, XML reports |
| G2: Known gaps | DWARF layout, toolchain flags, AST-DWARF dedup done; evidence tiers TODO |
| G3: libabigail tests | Done — ~54 parity test functions + 63 example cases |
| G4: Agent-friendly | Done — JSON, SARIF, exit codes, snapshots, MCP server, GitHub Action |
| G5: Break encyclopedia | Done — 63 example cases with docs + coverage matrix |
| G6: Distribution & docs | Done — PyPI, conda-forge, MkDocs + GitHub Pages |

## Non-goals

- Runtime instrumentation or dynamic analysis — abicheck is a static offline tool.
- Source-level refactoring suggestions — it reports *what* broke, not how to fix your code.
- Support for languages other than C/C++ (Rust, Go, etc.) — out of scope for now.
