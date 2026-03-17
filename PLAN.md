# Implementation Plan: Full-Stack ABI Compatibility Validation

> **Status: Implemented** — All steps below are complete. See
> [ADR-008](docs/development/adr/008-full-stack-dependency-validation.md) for
> the accepted architecture decision record.

## Overview

Extend abicheck from single-binary comparison to **full-stack (transitive dependency) validation** on Linux ELF. This adds the ability to resolve the complete runtime dependency graph, extract imports/exports across all DSOs, simulate symbol binding, and produce a stack-level ABI compatibility verdict.

## Architecture

New modules compose around existing infrastructure:

```text
CLI (stack-check command)
  │
  ├─ Resolver (new: resolver.py)
  │    → Walks DT_NEEDED transitively
  │    → Expands $ORIGIN / RPATH / RUNPATH
  │    → Builds resolved dependency DAG
  │
  ├─ Import Extractor (extend: elf_metadata.py)
  │    → Extract UND symbols from .dynsym (imports)
  │    → Extract per-symbol version requirements
  │
  ├─ Binder (new: binder.py)
  │    → Match each import to a provider DSO
  │    → Account for symbol versioning, visibility, binding strength
  │    → Classify: RESOLVED_OK, MISSING, VERSION_MISMATCH, INTERPOSED
  │
  ├─ Stack Checker (new: stack_checker.py)
  │    → For changed DSOs, run existing per-library ABI diff (reuse checker.py)
  │    → Intersect ABI changes with actual import bindings for impact
  │    → Produce stack-level verdict + risk scoring
  │
  └─ Stack Reporter (extend: reporter.py + new: stack_report.py)
       → JSON/Markdown output with dependency graph, bindings, verdicts
```

## Implementation Steps

### Step 1: Extend elf_metadata.py — Import Symbol Extraction

**What:** Add extraction of undefined (imported) dynamic symbols alongside existing exports.

**Changes to `elf_metadata.py`:**
- Add `ElfImport` dataclass: `(name, version, is_weak, binding)`
- Add `imports` field to `ElfMetadata`: `list[ElfImport]`
- Modify `_parse_dynsym()` to collect `SHN_UNDEF` symbols (currently skipped) into `imports`
- Add per-symbol version extraction from `.gnu.version` section (correlate version index → verneed entry)

**Why needed:** Currently only exports are extracted. To simulate binding, we need to know what each DSO *requires*.

### Step 2: New module — resolver.py (Dependency Resolution)

**What:** Resolve the transitive closure of DT_NEEDED dependencies using loader-accurate search order.

**Public API:**
```python
@dataclass
class ResolvedDSO:
    path: Path                    # Resolved filesystem path
    soname: str                   # DT_SONAME (or basename)
    needed: list[str]             # DT_NEEDED entries
    rpath: str                    # DT_RPATH
    runpath: str                  # DT_RUNPATH
    resolution_reason: str        # Why resolved here (rpath/runpath/cache/default)
    depth: int                    # Distance from root binary

@dataclass
class DependencyGraph:
    root: str                     # Root binary path
    nodes: dict[str, ResolvedDSO] # soname/path → resolved info
    edges: list[tuple[str, str]]  # (consumer, provider) edges
    unresolved: list[tuple[str, str]]  # (consumer, missing_soname)

def resolve_dependencies(
    binary: Path,
    search_paths: list[Path] | None = None,
    sysroot: Path | None = None,
    ld_library_path: str = "",
    use_ld_so_cache: bool = False,
) -> DependencyGraph:
```

**Key implementation details:**
- Parse DT_NEEDED/DT_RPATH/DT_RUNPATH from each ELF using existing `parse_elf_metadata()`
- Implement loader search order: DT_RPATH (if no DT_RUNPATH) → LD_LIBRARY_PATH → DT_RUNPATH (direct deps only) → default dirs (`/lib`, `/usr/lib`, etc.)
- Expand `$ORIGIN` token relative to the DSO's own directory
- Expand `$LIB` and `$PLATFORM` tokens (best-effort defaults)
- DT_RUNPATH applies only to direct DT_NEEDED — critical correctness rule
- Track resolution reason per DSO for diagnostics
- Optional sysroot prefix for cross/container analysis
- Cycle detection for malformed dependency chains

### Step 3: New module — binder.py (Symbol Binding Simulation)

**What:** Simulate the dynamic linker's symbol resolution across the resolved graph.

**Public API:**
```python
class BindingStatus(str, Enum):
    RESOLVED_OK = "resolved_ok"
    MISSING = "missing"
    VERSION_MISMATCH = "version_mismatch"
    WEAK_UNRESOLVED = "weak_unresolved"     # Weak ref, no provider (OK at runtime)
    VISIBILITY_BLOCKED = "visibility_blocked"
    INTERPOSED = "interposed"               # Resolved but via interposition

@dataclass
class SymbolBinding:
    consumer: str            # DSO that imports the symbol
    symbol: str              # Symbol name
    version: str             # Required version (or "")
    provider: str | None     # DSO that provides it (None if missing)
    status: BindingStatus
    explanation: str          # Human-readable reason

def compute_bindings(
    graph: DependencyGraph,
    metadata: dict[str, ElfMetadata],  # per-resolved-path metadata
    preload: list[str] | None = None,
) -> list[SymbolBinding]:
```

**Key implementation details:**
- For each DSO in breadth-first order from root, collect imports
- For each import, search providers in loader order (preload → breadth-first loaded order)
- Match symbol name + version (handle `@@` default version vs `@` non-default)
- Check visibility (STV_HIDDEN symbols can't satisfy external refs)
- Track interposition (symbol found in earlier DSO than the "natural" provider)
- Weak undefined symbols that don't resolve → WEAK_UNRESOLVED (not an error)

### Step 4: New module — stack_checker.py (Stack-Level ABI Check)

**What:** Compare two resolved stacks (baseline vs candidate) and produce a stack-level verdict.

**Public API:**
```python
class StackVerdict(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"

@dataclass
class StackChange:
    library: str               # Which DSO changed
    change_type: str           # "added", "removed", "version_changed", "abi_changed"
    abi_diff: DiffResult | None  # Per-library ABI diff (reuses existing checker)
    impacted_imports: list[SymbolBinding]  # Which bindings are affected

@dataclass
class StackCheckResult:
    root_binary: str
    baseline_env: str
    candidate_env: str
    loadability: StackVerdict       # Will it load?
    abi_risk: StackVerdict          # Are there harmful ABI changes?
    baseline_graph: DependencyGraph
    candidate_graph: DependencyGraph
    bindings_baseline: list[SymbolBinding]
    bindings_candidate: list[SymbolBinding]
    missing_symbols: list[SymbolBinding]   # Symbols that fail to resolve
    stack_changes: list[StackChange]       # Per-library changes
    risk_score: str                         # "high", "medium", "low"

def check_stack(
    binary: Path,
    baseline_root: Path,
    candidate_root: Path,
    ld_library_path: str = "",
    search_paths: list[Path] | None = None,
) -> StackCheckResult:
```

**Key implementation details:**
- Resolve dependency graphs for both baseline and candidate environments
- Compute bindings in both environments
- Detect loadability failures (missing symbols/DSOs in candidate)
- Identify changed DSOs (by SONAME + build-id or content hash)
- For changed DSOs: run existing `compare()` from checker.py (reuse all 80+ detectors)
- Intersect ABI changes with actual bindings to determine impact
- Compute risk score: HIGH (load failure or harmful change on used symbol), MEDIUM (harmful change on unused path), LOW (compatible changes only)

### Step 5: New CLI command — `abicheck stack-check`

**What:** Add a new CLI subcommand for full-stack validation.

```bash
abicheck stack-check <binary> \
    --baseline <rootfs_path> \
    --candidate <rootfs_path> \
    [--ld-library-path <paths>] \
    [--search-path <dir>] \
    [--format json|markdown] \
    [--output <file>]
```

Also add a simpler single-environment mode:
```bash
abicheck deps <binary> \
    [--search-path <dir>] \
    [--sysroot <path>] \
    [--format json|markdown]
```

The `deps` command resolves and displays the dependency graph + binding status for a single binary in a single environment (useful for debugging/inspection).

### Step 6: Stack Report Output (stack_report.py + extend reporter.py)

**What:** JSON and Markdown output formats for stack-level results.

**JSON output** follows the schema from the research doc:
- `root_binary`, `arch`, `baseline`/`candidate` env descriptions
- `nodes[]` — resolved dependency graph
- `bindings[]` — per-symbol resolution status
- `abi_diffs[]` — per-changed-library ABI diff summaries
- `verdict` — `{ loadability, abi_risk }`

**Markdown output:**
- Summary table (root binary, verdicts, risk score)
- Dependency tree (ASCII art or nested list)
- Binding failures section (missing/mismatched symbols)
- ABI changes section (per changed library, with impacted interfaces)
- Remediation suggestions

### Step 7: Tests

**New test files:**
- `tests/test_resolver.py` — dependency resolution with mock filesystem
  - RPATH vs RUNPATH propagation differences
  - $ORIGIN expansion
  - Missing dependency detection
  - Cycle detection
  - Sysroot prefix handling
- `tests/test_binder.py` — symbol binding simulation
  - Basic resolution (import → export matching)
  - Symbol version matching (@@default vs @specific)
  - Weak symbol handling
  - Visibility blocking (STV_HIDDEN)
  - Interposition detection
- `tests/test_stack_checker.py` — end-to-end stack check
  - Two-environment comparison
  - Changed DSO detection
  - Impact intersection (ABI change × binding usage)
  - Risk scoring
- `tests/test_stack_cli.py` — CLI integration tests for `stack-check` and `deps` commands

## What's NOT in scope (documented limitations)

- `dlopen()` plugins (not in DT_NEEDED — requires runtime tracing or manifest)
- `ld.so.cache` parsing (would need binary cache format parser; use search paths instead)
- LD_PRELOAD/LD_AUDIT interposition (tracked as risk flag, not fully simulated)
- Container-aware resolution (user provides sysroot; we don't parse OCI images)
- Reverse engineering fallback (Ghidra/radare2 for stripped binaries)

## File inventory (new/modified)

| File | Status | Description |
|------|--------|-------------|
| `abicheck/elf_metadata.py` | Modified | Add import extraction + per-symbol version correlation |
| `abicheck/resolver.py` | New | Transitive dependency resolution with loader semantics |
| `abicheck/binder.py` | New | Symbol binding simulation across resolved graph |
| `abicheck/stack_checker.py` | New | Stack-level comparison and verdict computation |
| `abicheck/stack_report.py` | New | Stack report formatting (JSON + Markdown) |
| `abicheck/cli.py` | Modified | Add `stack-check` and `deps` commands |
| `tests/test_resolver.py` | New | Resolver unit tests |
| `tests/test_binder.py` | New | Binder unit tests |
| `tests/test_stack_checker.py` | New | Stack checker integration tests |
| `tests/test_stack_cli.py` | New | CLI integration tests |
