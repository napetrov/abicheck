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
| D: Rust tooling (goblin, bindgen) | ELF in Rust, requires extension or subprocess | OUT OF SCOPE: defeats pure-Python goal |

Options C and D were rejected: LLVM is too heavy as a CI dependency; Rust tooling
requires a non-Python build chain and is primarily aimed at Rust FFI, not C/C++ ABI diffing.

## Decision

**Option B: Python + pyelftools + castxml**

### Stack

```
abicheck (Python)
├── ELF metadata + DWARF  → pyelftools   (pure Python ELF/DWARF parser)
├── C++ header AST        → castxml      (C++ → XML, maintained by Kitware)
└── Diff + verdict        → our Python   (thin, testable, no C extension)
```

`binutils readelf` is NOT used as a runtime dependency. It may be invoked
as an optional debugging/validation tool (`--debug-readelf`), but the production
parse path goes through pyelftools only (no subprocess, no text parsing).

### Dependencies

| Library | Role | Maintenance status |
|---------|------|-------------------|
| `pyelftools` | ELF/DWARF parsing | Active PyPI project, used by angr, pwntools, ROPgadget |
| `castxml` | C++ header → XML AST | Maintained by Kitware (VTK team) |
| `defusedxml` | Safe XML parsing | Security hardening for castxml output |

Note: An earlier version of this ADR incorrectly stated pyelftools is used by Ghidra.
Ghidra is Java-based and uses its own ELF parser. The correct reference projects are
**angr** and **pwntools** — both production binary-analysis frameworks that rely on pyelftools.

### What we do NOT depend on

- ~~abidiff / libabigail~~ (unmaintained)
- ~~ABICC~~ (unmaintained)
- ~~LLVM tooling~~ (too heavy)
- ~~readelf subprocess~~ (text parsing, fragile across versions/locales)

## Consequences

### Positive
- No dependency on unmaintained C++ tools
- Full Python — easy to test, debug, extend, run in CI
- `pyelftools` gives ELF/DWARF parsing for free (no reimplementing the spec)
- `castxml` is the industry standard for C++ header → AST
- Zero C/C++ code to maintain in our repo
- `elf_metadata.py` is an explicit abstraction boundary — backend is swappable

### Negative
- We own the diff logic (but that's the core value anyway)
- pyelftools DWARF parsing is slower than native C (~10–50× vs libabigail)
  — acceptable for CI usage, not for interactive sub-second latency
- pyelftools DWARF 5 support is partial (string offsets, location lists) — see Scope

## Scope Limitations (explicit)

The following ABI properties require compiler-level knowledge and are **out of scope
for Sprints 1–4**:

| Feature | Why hard | Mitigation |
|---------|----------|-----------|
| vtable layout | No DWARF standard; reconstructed from `_ZTV*` symbols + `.rodata` | Sprint 4+ |
| Calling convention changes | Requires ABI spec knowledge per arch/platform | Out of scope |
| Inline function ABI | Inlined functions leave no `DW_AT_external` in DWARF | Document as gap |
| EBO (empty base class elimination) | Layout change invisible in headers alone | Document as gap |
| C++ template specialization graphs | Requires demangling + type-graph resolution | Sprint 3 partial |

## C++ Name Demangling

Sprint 3 (DWARF-aware diff) will require demangling `_ZTV*`, `_ZTI*`, `_ZTS*` and
template instantiation names. Decision: use **`cxxfilt`** Python wrapper (wraps
`c++filt` from binutils) for now; evaluate `itanium_abi` pure-Python demangler
if subprocess overhead becomes a bottleneck.

## Platform Scope

- **Supported:** Linux ELF x86-64, aarch64
- **Not supported:** Windows PE/COFF, macOS Mach-O (explicit non-goal)
- **DWARF version:** DWARF 4 (GCC ≤10 default) fully supported; DWARF 5 (GCC 11+ default) partially supported via pyelftools ≥0.29

## pyelftools Maintenance Risk & Mitigation

pyelftools has a small core maintainer team (~3 active contributors as of 2026).

Mitigations:
1. **Abstraction boundary**: `elf_metadata.py` isolates the pyelftools API. Swapping
   the backend requires changes only in this one file.
2. **Fork strategy**: pyelftools is MIT licensed. If abandoned, we fork and maintain
   only the subset we use (`ELFFile`, `DynamicSection`, `SymbolTableSection`,
   `GNUVerDefSection`, `GNUVerNeedSection`).
3. **Fallback**: On `ELFError`, gracefully degrade to empty `ElfMetadata` with a warning.
4. **Upstream contributions**: File issues/PRs for DWARF 5 gaps as we hit them.

## abidiff / ABICC Role Going Forward

- Kept as **optional validation backend** for testing only (`--validate-with-abidiff`)
- NOT a runtime dependency
- Used for regression testing: if our verdict differs from abidiff, investigate why

## ABI Classification Decisions

### `NEEDED_ADDED` → COMPATIBLE
Adding a DT_NEEDED entry is a load-time concern, not a symbol/type ABI break.
libabigail/abidiff do not flag DT_NEEDED changes as ABI breaks. Consumers on
systems lacking the new dep will fail to load — this is a deployment concern,
reported as COMPATIBLE (with a warning in the output).

### `SYMBOL_BINDING_STRENGTHENED` (WEAK→GLOBAL) → COMPATIBLE
Strengthening a symbol from WEAK to GLOBAL is backward-compatible for most consumers.
Edge case: interposing libraries that relied on weak-override semantics will lose
the interposition. This unusual pattern is documented but the default verdict is COMPATIBLE.

### `SYMBOL_SIZE_CHANGED` — STT_OBJECT only
Symbol size changes are only ABI-relevant for data objects (`STT_OBJECT`, `STT_TLS`).
Function (`STT_FUNC`) symbol size = machine-code bytes, which changes with every
compile/optimization pass and is not an ABI contract. Flagging STT_FUNC size would
produce massive false positives.

## Implementation Plan

| Sprint | Layer | Technology |
|--------|-------|-----------|
| Sprint 1 (done) | castxml-based type/function diff | castxml + our XML parser |
| Sprint 2 (done) | ELF dynamic-section + symbol metadata | **pyelftools** |
| Sprint 3 | DWARF-aware struct layout / type diff | **pyelftools** DWARF + cxxfilt |
| Sprint 4 | Header API surface diff + vtable (partial) | castxml + clang Python bindings |
