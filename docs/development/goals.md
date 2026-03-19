# Project Goals

## Primary goal

**abicheck** aims to be the best-in-class ABI compatibility checker for C/C++ shared libraries — accurate, fast, and easy to integrate into CI pipelines.

## Design principles

1. **Three-layer analysis** — ELF symbol table + Clang AST (via castxml) + DWARF cross-check.
   No single layer catches everything; combining all three minimises false negatives.

2. **Zero configuration by default** — `abicheck compare old.so new.so` should do the right
   thing out of the box. Policies, suppressions, and format options are available when needed.

3. **CI-first** — clear exit codes, machine-readable output (JSON, SARIF), and a GitHub Action
   make it trivial to gate merges on ABI stability.

4. **ABICC drop-in compatibility** — projects using `abi-compliance-checker` can switch with a
   one-line change; flag parity and descriptor support are maintained.

5. **Cross-platform** — Linux (ELF), macOS (Mach-O), and Windows (PE/COFF) are all first-class
   targets.

## Status summary

| Goal | Status |
|------|--------|
| G1: ABICC drop-in | Done — 113 ChangeKinds, compat CLI, suppression files, XML reports |
| G2: Known gaps | DWARF layout, toolchain flags, AST-DWARF dedup done; evidence tiers TODO |
| G3: libabigail tests | Done — ~54 parity test functions + 63 example cases |
| G4: Agent-friendly | Done — JSON, SARIF, exit codes, snapshots, MCP server, GitHub Action |
| G5: Break encyclopedia | Done — 63 example cases with docs + coverage matrix |
| G6: Distribution & docs | Done — PyPI, conda-forge, MkDocs + GitHub Pages |

For detailed goal descriptions, milestones, and progress notes, see
[GOALS.md](https://github.com/napetrov/abicheck/blob/main/GOALS.md) in the
repository root.

## Non-goals

- Runtime instrumentation or dynamic analysis — abicheck is a static offline tool.
- Source-level refactoring suggestions — it reports *what* broke, not how to fix your code.
- Support for languages other than C/C++ (Rust, Go, etc.) — out of scope for now.
