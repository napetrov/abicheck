# Design: Extend `compare` to accept `.so` files directly

## Problem

Today's flow requires two steps: `dump` then `compare`. Users with two `.so` versions
side-by-side cannot do a one-liner. The `compat` mode exists only for ABICC migration,
not as the general-purpose one-liner.

## Design Goals

1. **One-liner is the primary flow** — `compare` accepts `.so` files directly
2. **Dump-then-compare remains supported** — for snapshot caching / CI baselines
3. **Mixed mode** — compare a saved snapshot against a live `.so`
4. **`compat` stays as-is** — strictly for ABICC migration users

## Input detection strategy

Each positional argument (`OLD`, `NEW`) is auto-detected by file content:

| Input | Detection | Action |
|-------|-----------|--------|
| `*.json` file (contains `{`) | JSON snapshot | `load_snapshot()` as today |
| ELF binary (`.so`, `.so.N`, or ELF magic `\x7fELF`) | Shared library | auto-dump on the fly |
| ABICC Perl dump | `Data::Dumper` header | import via `import_abicc_perl_dump()` |

This means all three combinations work:
- `.so` vs `.so` (one-liner, primary)
- `.json` vs `.json` (existing dump workflow)
- `.json` vs `.so` (baseline snapshot vs current build)

## CLI changes to `compare`

### New options (from `dump` command, needed when inputs are `.so` files)

```
abicheck compare OLD NEW [options]

Positional arguments:
  OLD                    Old version: .so file OR .json snapshot
  NEW                    New version: .so file OR .json snapshot

Dump options (used when input is a .so file):
  -H, --header PATH     Public header file (repeat for multiple).
                         Applied to both sides unless --old-header/--new-header used.
  -I, --include PATH    Extra include directory for castxml.
                         Applied to both sides unless --old-include/--new-include used.
  --compiler TEXT        Compiler frontend for castxml (default: c++).

  --old-header PATH     Header for old side only (repeat for multiple).
  --new-header PATH     Header for new side only (repeat for multiple).
  --old-include PATH    Include dir for old side only.
  --new-include PATH    Include dir for new side only.
  --old-version TEXT    Version label for old side (default: "old").
  --new-version TEXT    Version label for new side (default: "new").

Existing compare options (unchanged):
  --format              json | markdown | sarif | html
  -o, --output          Output file
  --suppress            Suppression YAML
  --policy              strict_abi | sdk_vendor | plugin_abi
  --policy-file         Custom policy YAML
```

### Why per-side header options?

Common case: same headers for both versions — use `-H`.
When headers themselves changed between versions, use `--old-header` / `--new-header`.

### Validation rules

- If OLD or NEW is a `.so` file, at least one `-H` (or the matching `--old-header`/`--new-header`) is **required**
- If both inputs are `.json`, dump options (`-H`, `-I`, `--compiler`) are **ignored** (with a warning if provided)
- `--old-header` and `--new-header` override `-H` for their respective side
- `--old-include` and `--new-include` override `-I` for their respective side

## Usage examples

### Primary flow: one-liner `.so` vs `.so`

```bash
# Same headers for both versions
abicheck compare libfoo.so.1 libfoo.so.2 -H include/foo.h

# Different headers per version
abicheck compare libfoo.so.1 libfoo.so.2 \
  --old-header include/v1/foo.h \
  --new-header include/v2/foo.h

# With version labels and output
abicheck compare libfoo.so.1 libfoo.so.2 -H include/foo.h \
  --old-version 1.0 --new-version 2.0 \
  --format sarif -o abi.sarif

# Multiple headers
abicheck compare libfoo.so.1 libfoo.so.2 \
  -H include/foo.h -H include/bar.h -I include/
```

### Secondary flow: pre-dumped snapshots (unchanged)

```bash
abicheck compare libfoo-1.0.json libfoo-2.0.json
```

### Mixed flow: snapshot vs live build

```bash
# CI baseline snapshot vs current build output
abicheck compare baseline-1.0.json ./build/libfoo.so \
  -H include/foo.h --new-version 2.0-dev
```

### GitHub Actions (simplified)

```yaml
steps:
  - name: ABI check
    run: |
      abicheck compare libfoo_old.so libfoo_new.so \
        -H include/foo.h \
        --format sarif -o abi.sarif
```

vs today's 3-step flow (dump old, dump new, compare).

## Implementation plan

### Step 1: Add `_resolve_input()` helper

```python
def _is_elf(path: Path) -> bool:
    """Check if file starts with ELF magic bytes."""
    try:
        with open(path, "rb") as f:
            return f.read(4) == b"\x7fELF"
    except OSError:
        return False

def _resolve_input(
    path: Path,
    headers: list[Path],
    includes: list[Path],
    version: str,
    compiler: str,
) -> AbiSnapshot:
    """Auto-detect input type and return an AbiSnapshot.

    - JSON file → load_snapshot()
    - ELF binary → dump() on the fly
    - ABICC Perl dump → import_abicc_perl_dump()
    """
    if _is_elf(path):
        if not headers:
            raise click.UsageError(
                f"Input '{path}' is an ELF binary — "
                "at least one header (-H/--header) is required for ABI extraction."
            )
        return dump(
            so_path=path,
            headers=headers,
            extra_includes=includes,
            version=version,
            compiler=compiler,
        )

    # Try JSON first, fall back to ABICC Perl dump
    text = path.read_text(encoding="utf-8", errors="replace")
    if text.lstrip().startswith("{"):
        return load_snapshot(path)

    if looks_like_perl_dump(text):
        return import_abicc_perl_dump(path)

    raise click.UsageError(
        f"Cannot detect format of '{path}'. "
        "Expected: ELF binary (.so), JSON snapshot (.json), or ABICC Perl dump."
    )
```

### Step 2: Extend `compare_cmd` signature

Add the new click options. Resolve per-side headers:

```python
# Resolve headers for each side
old_headers = list(old_header) if old_header else list(headers)
new_headers = list(new_header) if new_header else list(headers)
old_includes = list(old_include) if old_include else list(includes)
new_includes = list(new_include) if new_include else list(includes)

old = _resolve_input(old_path, old_headers, old_includes, old_version, compiler)
new = _resolve_input(new_path, new_headers, new_includes, new_version, compiler)
```

### Step 3: Update help text and examples

Update the docstring and README to show the one-liner as the primary flow.

### Step 4: Tests

- Test: `.so` + `.so` with shared headers
- Test: `.so` + `.so` with per-side headers
- Test: `.json` + `.json` (backward compat, unchanged)
- Test: `.json` + `.so` (mixed mode)
- Test: `.so` without headers → clear error message
- Test: `.json` with `-H` → warning that dump options are ignored
- Test: ELF detection (magic bytes, not just extension)

## What does NOT change

- `dump` command — stays as-is for explicit snapshot creation
- `compat` command — stays as-is for ABICC migration only
- `compare` exit codes — unchanged (0, 2, 4)
- `compare` output formats — unchanged
- `compare` with two `.json` files — fully backward compatible

## Updated command hierarchy after this change

```
abicheck compare  ← PRIMARY: one-liner (.so/.json, auto-detect)
abicheck dump     ← SECONDARY: explicit snapshot creation for caching
abicheck compat   ← MIGRATION: ABICC drop-in (XML descriptors)
```
