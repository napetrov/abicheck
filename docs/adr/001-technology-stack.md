# ADR-001: Technology Stack — Python + pyelftools + castxml

**Date:** 2026-03-07  
**Status:** Accepted  
**Decision maker:** Nikolay Petrov

---

## Context

abicheck needs to analyze C/C++ ABI compatibility. Two reference tools exist:
- **abi-compliance-checker (ABICC)** — no longer maintained
- **libabigail / abidiff** — no longer maintained

We need a stack that gives long-term sustainability with minimal maintenance burden.

## Options Considered

| Option | Description | Risk |
|--------|-------------|------|
| A: Wrap abidiff/ABICC | Parse their output, normalize to our model | HIGH: unmaintained, format changes |
| **B: Python + pyelftools + castxml** | Pure Python orchestration over maintained libs | **LOW: all deps actively maintained** |
| C: LLVM tooling | clang AST + llvm-readelf | MEDIUM: heavy dependency (~500MB) |

## Decision

**Option B: Python + pyelftools + castxml + binutils readelf**

### Stack

```
abicheck (Python)
├── ELF metadata      → binutils readelf  (GNU, ~30yr stable, part of every distro)
├── DWARF / type info → pyelftools         (pure Python, actively maintained, used in Ghidra/angr)
├── C++ header AST    → castxml            (C++ → XML, maintained by Kitware)
└── Diff + verdict    → our Python code    (thin, testable, no C extension)
```

### Dependencies

| Library | Role | Why maintained |
|---------|------|---------------|
| `pyelftools` | ELF/DWARF parsing | Active PyPI project, 7k+ stars, used by major security tools |
| `castxml` | C++ header → XML AST | Maintained by Kitware (VTK team) |
| `readelf` (binutils) | ELF dynamic/symbol metadata | Part of GNU binutils, essentially infrastructure |
| `defusedxml` | Safe XML parsing | Security hardening for castxml output |

### What we do NOT depend on

- ~~abidiff / libabigail~~ (unmaintained)
- ~~ABICC~~ (unmaintained)
- ~~LLVM tooling~~ (too heavy for a dependency)

## Consequences

### Positive
- No dependency on unmaintained C++ tools
- Full Python — easy to test, debug, extend, run in CI
- `pyelftools` gives us DWARF parsing for free (no reimplementing DWARF spec)
- `castxml` is the industry standard for C++ header parsing
- Zero C/C++ code to maintain in our repo

### Negative
- We own the diff logic (but that's the core value anyway)
- DWARF parsing via pyelftools is slower than native C (acceptable for CI usage)

### abidiff / ABICC role going forward
- Kept as **optional validation backend** for testing only (`--validate-with-abidiff`)
- NOT a runtime dependency
- Used for regression testing: if our verdict differs from abidiff, investigate why

## Implementation Plan

| Sprint | Layer | Technology |
|--------|-------|-----------|
| Sprint 1 (done) | castxml-based type/function diff | castxml + our XML parser |
| Sprint 2 (done) | ELF-only metadata | readelf (binutils) |
| Sprint 3 | DWARF-aware layout/type diff | **pyelftools** |
| Sprint 4 | Header/API surface diff | castxml + clang Python bindings |
