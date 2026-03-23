# ADR-020: Build-Context Aware Header Extraction

**Date:** 2026-03-23
**Status:** Proposed
**Decision maker:** Nikolay Petrov

---

## Context

### The header parse drift problem

abicheck's Layer 2 (header AST via CastXML) is only as correct as the compile
environment used to parse headers. Today, users manually specify `--compiler-options`,
`--includes`, and `--defines` via CLI flags. The dumper passes these through to
CastXML as a single global set of flags.

This creates the single largest source of false positives and false negatives in
production deployments:

- **False positives**: CastXML sees type definitions that differ from what the
  compiler actually compiled (wrong `-D` flags, missing feature toggles, different
  `-std=` mode)
- **False negatives**: ABI-relevant changes hidden behind `#ifdef` blocks that
  CastXML doesn't enter because it lacks the correct preprocessor defines
- **Configuration variants**: A library built with `-DFOO_ENABLE_SSL=1` has a
  different ABI surface than the same library built without it — same headers,
  different exported types

### Current CLI interface

```bash
abicheck dump libfoo.so \
    -H include/ \
    --compiler-options "-std=c++17 -DFOO_ENABLE_SSL=1" \
    --includes "/usr/include/openssl"
```

This works for simple cases but breaks at scale:
- Multi-TU libraries have per-file flags (different `-D`, `-I`, `-std=` per source file)
- Build systems already know all flags — re-specifying them is error-prone
- Feature-flagged builds require users to know which defines were active
- Cross-compilation targets (sysroot, target triple) are easy to get wrong

### The compilation database standard

The Clang/LLVM ecosystem defines `compile_commands.json` (JSON Compilation Database)
as the standard interchange format for build metadata. CMake, Meson, Ninja, Bear,
and other build systems generate it. Format:

```json
[
  {
    "directory": "/build",
    "file": "src/foo.cpp",
    "arguments": ["c++", "-std=c++17", "-DFOO_ENABLE_SSL=1", "-I/usr/include/openssl", "-Iinclude", "-c", "src/foo.cpp"]
  },
  {
    "file": "src/bar.c",
    "command": "cc -std=c11 -Iinclude -c src/bar.c",
    "directory": "/build"
  }
]
```

Each entry captures the **exact** compiler invocation for one translation unit.

### What other tools do

- **Android VNDK header-abi-dumper**: Runs per-TU with the exact compiler flags from
  the build system. The build system invokes the dumper — it doesn't ingest a database.
- **clang-tidy / clangd**: Consume `compile_commands.json` natively to match analysis
  to build context.
- **libabigail / ABICC**: Do not consume compilation databases. Users supply headers
  and include paths manually.

### Options considered

| Option | Description | Trade-off |
|--------|-------------|-----------|
| A: Manual flags only (status quo) | User specifies all flags | Error-prone at scale; header parse drift |
| **B: compile_commands.json ingestion** | Parse database, derive flags per public header | Deterministic; matches real build; standard format |
| C: Build system plugins | CMake/Meson plugins invoke abicheck during build | Tight coupling; only works during build; not post-hoc |
| D: Compiler wrapper interception | LD_PRELOAD/wrapper records flags | Fragile; security concerns; doesn't work for all build systems |

---

## Decision

### 1. Accept `compile_commands.json` as a first-class input

New CLI flags:

```bash
# Point to build directory containing compile_commands.json
abicheck dump libfoo.so -H include/ -p /path/to/builddir

# Or point to the file directly
abicheck dump libfoo.so -H include/ --compile-db /path/to/compile_commands.json

# Combined with explicit overrides (overrides take precedence)
abicheck dump libfoo.so -H include/ -p builddir --compiler-options "-DEXTRA=1"
```

`-p <builddir>` mirrors clang-tidy's convention. When specified, abicheck looks
for `<builddir>/compile_commands.json`.

### 2. Flag derivation pipeline

```text
compile_commands.json
  │
  ├── Parse all entries
  │
  ├── Filter to library's TUs (match by source file paths)
  │     Strategy: intersect compile_commands entries with source files
  │     that produce symbols found in the binary (via build artifacts or heuristics)
  │
  ├── Extract per-TU flags:
  │     -D / -U defines
  │     -I / -isystem include paths
  │     -std= language standard
  │     --target= / -target triple
  │     --sysroot=
  │     -fvisibility=
  │     -fabi-version=
  │     -f[no-]exceptions, -f[no-]rtti
  │     -fpack-struct=, -fms-extensions
  │
  ├── Compute unified flag set for header parsing:
  │     Option A: Union of all TU flags (broadest coverage, may over-include)
  │     Option B: Intersection (most conservative, may under-include)
  │     Decision: Union with conflict detection
  │     - Defines: union all -D flags; warn on conflicting values for same macro
  │     - Includes: union all -I paths (order: most-common-first)
  │     - Language standard: use the highest -std= value (warn if mixed C/C++)
  │     - Target/sysroot: must be consistent across TUs (error if conflicting)
  │
  └── Feed unified flags to CastXML
```

### 3. Public header scope resolution

Not all types in headers are part of the public ABI. The compilation database
enables a "public header scope" filter:

```text
Public ABI surface = types reachable from:
  1. Headers in the -H / --headers directories (user-specified public headers)
  2. Exported symbols in the binary (L0 metadata)

Exclude:
  - Types only defined in private/internal headers
  - Types not reachable from any exported function signature or variable
```

This mirrors Android's header-abi-dumper approach: only types reachable from
exported include roots count as public ABI.

Implementation:

```python
@dataclass
class BuildContext:
    """Compilation context derived from compile_commands.json."""
    defines: dict[str, str | None]   # -D macro=value pairs (None = defined without value)
    undefines: set[str]              # -U macros
    include_paths: list[Path]        # -I paths (ordered)
    system_includes: list[Path]      # -isystem paths
    language_standard: str | None    # -std=c++17, -std=c11, etc.
    target_triple: str | None        # --target=x86_64-linux-gnu
    sysroot: Path | None             # --sysroot=
    extra_flags: list[str]           # Remaining flags passed through to CastXML
    source_file: str                 # compile_commands.json path (for diagnostics)

    # Conflict tracking
    define_conflicts: dict[str, list[str]]  # macro → [value1, value2, ...]
    standard_variants: list[str]            # all -std= values seen

def build_context_from_compile_db(
    compile_db_path: Path,
    source_filter: Callable[[str], bool] | None = None,
) -> BuildContext:
    """Parse compile_commands.json and derive unified build context."""
```

### 4. CastXML integration

CastXML supports configuring its internal Clang preprocessor to match an external
compiler. The build context feeds into CastXML invocation:

```python
def _build_castxml_args(context: BuildContext, header: Path) -> list[str]:
    args = ["castxml", "--castxml-output=1"]

    # Language standard
    if context.language_standard:
        args.extend(["--castxml-cc-gnu", f"({context.language_standard})"])

    # Target
    if context.target_triple:
        args.extend([f"--target={context.target_triple}"])

    # Defines
    for macro, value in context.defines.items():
        if value is not None:
            args.append(f"-D{macro}={value}")
        else:
            args.append(f"-D{macro}")

    # Includes
    for inc in context.include_paths:
        args.extend(["-I", str(inc)])
    for inc in context.system_includes:
        args.extend(["-isystem", str(inc)])

    # Extra flags passthrough
    args.extend(context.extra_flags)

    args.append(str(header))
    return args
```

### 5. Deterministic caching

Build-context awareness enables content-addressed caching of CastXML results:

```python
def _cache_key(header_path: Path, context: BuildContext) -> str:
    """Content-addressed cache key for deterministic header parsing."""
    h = hashlib.sha256()
    h.update(header_path.read_bytes())
    h.update(json.dumps(context.defines, sort_keys=True).encode())
    h.update(json.dumps([str(p) for p in context.include_paths]).encode())
    h.update((context.language_standard or "").encode())
    h.update((context.target_triple or "").encode())
    return h.hexdigest()[:16]
```

Cache location: `<builddir>/.abicheck_cache/` or `--cache-dir`.

Cache invalidation: any change to header content or build flags produces a new key.
This eliminates redundant CastXML invocations in CI when only a subset of headers
changed.

### 6. Conflict handling

When TUs disagree on flags, abicheck must handle it explicitly:

| Conflict type | Resolution | Diagnostic |
|---------------|------------|------------|
| Different `-D` values for same macro | Use the value from the TU that defines it last (alphabetical source file order) | Warning: "macro FOO defined as 1 in src/a.cpp and 2 in src/b.cpp; using 2" |
| Mixed `-std=` | Use highest standard | Warning: "mixed standards c++14, c++17; using c++17" |
| Different targets | Error — cannot unify | Error: "conflicting target triples; use --compiler-options to override" |
| Different sysroots | Error | Error: "conflicting sysroots" |

### 7. Fallback behavior

```text
compile_commands.json available?
├── YES → Derive BuildContext → use for CastXML
│         User --compiler-options override specific flags
│         Warn on conflicts
│
└── NO  → -p specified?
          ├── YES → Error: "compile_commands.json not found in {builddir}"
          └── NO  → Current behavior (manual flags only)
```

No silent fallback when `-p` is explicitly given — fail loud.

---

## Consequences

### Positive
- Eliminates header parse drift — the most common source of ABI tool inaccuracy
- Standard format understood by all major build systems (CMake, Meson, Ninja, Bear)
- Enables deterministic caching keyed by (header content + flags)
- Public header scope resolution reduces false positives from internal types
- Convention (`-p`) familiar to clang-tidy/clangd users

### Negative
- `compile_commands.json` only captures TU flags — not link-time or install-time transforms
- Union-of-flags strategy may over-include in some edge cases
- Requires build system to generate `compile_commands.json` (not always default)
- Cache management adds complexity (disk cleanup, invalidation edge cases)
- Per-TU flag extraction parsing must handle both `arguments` array and `command` string formats

---

## Implementation Plan

| Phase | Scope | Effort |
|-------|-------|--------|
| 1 | `BuildContext` model + `compile_commands.json` parser | 2-3 days |
| 2 | Flag extraction (defines, includes, std, target, sysroot) | 2-3 days |
| 3 | Conflict detection and resolution logic | 1-2 days |
| 4 | CastXML integration — feed `BuildContext` into dumper pipeline | 2-3 days |
| 5 | CLI: `-p`, `--compile-db`, interaction with existing `--compiler-options` | 1-2 days |
| 6 | Deterministic cache (content-addressed, cache-dir) | 2-3 days |
| 7 | Public header scope resolver (types reachable from exported headers) | 3-5 days |
| 8 | Tests: multi-TU, mixed flags, conflict cases, cache hit/miss | 2-3 days |
