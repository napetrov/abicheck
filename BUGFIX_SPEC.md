# abicheck Bugfix Specification

**Version**: 0.2.0
**Date**: 2026-03-20
**Status**: Proposed

---

## Overview

This specification defines exact fixes for all 9 bugs discovered during comprehensive testing.
Each section identifies the root cause, the file(s) to modify, the precise code change, and
the testing strategy.

---

## Bug 1: `--show-only` JSON output — summary/changes inconsistency

### Root Cause

In `reporter.py:482-508`, the `to_json()` function applies `show_only` filtering to the
`changes` list but computes the `summary` from the **unfiltered** `DiffResult`:

```python
changes = list(result.changes)
if show_only:
    changes = apply_show_only(changes, show_only, policy=result.policy)

summary = build_summary(result)  # ← uses result.changes, not filtered `changes`
```

The summary dict (breaking count, risk_changes, total_changes) reflects the full result
while the `changes` array only shows filtered items. This is confusing for JSON consumers.

### Fix Location

**File**: `abicheck/reporter.py`, function `to_json()` (line ~486)
**File**: `abicheck/report_summary.py`, function `build_summary()` (line ~70)

### Fix Strategy

Add a `filtered_summary` key to JSON output when `show_only` is active, while preserving the
original `summary` for backward compatibility. This approach is preferred over modifying
`summary` because:
- Existing CI pipelines may depend on `summary` reflecting the full picture.
- The unfiltered summary is needed to compute exit codes correctly.

**Change in `reporter.py:to_json()`** (after line 508):

```python
summary = build_summary(result)
d["summary"] = { ... }  # existing code, unchanged

if show_only:
    # Add filtered summary so consumers can see counts matching the changes array
    d["filtered_summary"] = {
        "breaking": sum(1 for c in changes if c.kind in eff_breaking),
        "total_changes": len(changes),
    }
    d["show_only_applied"] = show_only
```

Alternatively (simpler approach): When `show_only` is active, always add a
`"show_only_applied": "<filter-value>"` key and a `"filtered_total"` count.
This makes it unambiguous that summary != len(changes).

### Testing

**File**: `tests/test_report_filtering.py` (extend existing) or new `tests/test_bug1_show_only_summary.py`

| Test | Description |
|------|-------------|
| `test_show_only_json_summary_matches_changes` | With `--show-only breaking`, verify `filtered_summary.total_changes == len(changes)` |
| `test_show_only_json_full_summary_unchanged` | Verify `summary` still reflects the full unfiltered result |
| `test_show_only_json_metadata_key_present` | Verify `show_only_applied` key exists when filter is active |
| `test_no_show_only_no_filtered_summary` | Verify `filtered_summary` key absent when no filter |

**Test type**: Unit test (construct DiffResult in-memory, call `to_json()` directly).

---

## Bug 2: `affected_pct` exceeds 100%

### Root Cause

In `report_summary.py:58-61`, the `affected_pct` calculation divides `breaking_count` by
`old_symbol_count` without capping at 100%. When multiple distinct breaking changes affect the
same function (e.g., `func_return_changed` + `func_params_changed` for one function), the
`breaking_count` (which counts *changes*, not *symbols*) can exceed `old_symbol_count`.

```python
if old_symbol_count and old_symbol_count > 0:
    affected_pct = breaking_count / old_symbol_count * 100  # ← can exceed 100
```

Note: `binary_compatibility_pct` on line 53 already uses `max(0.0, ...)` but `affected_pct`
does not cap at 100.

### Fix Location

**File**: `abicheck/report_summary.py`, function `compatibility_metrics()` (line 59)

### Fix

```python
if old_symbol_count and old_symbol_count > 0:
    affected_pct = min(100.0, breaking_count / old_symbol_count * 100)
else:
    affected_pct = 0.0
```

Single-line change: add `min(100.0, ...)` wrapper.

### Testing

**File**: `tests/test_policy_registry_and_summary.py` (extend existing) or `tests/test_report_summary.py`

| Test | Description |
|------|-------------|
| `test_affected_pct_capped_at_100` | Create changes list where breaking_count > old_symbol_count, verify <= 100.0 |
| `test_affected_pct_normal_case` | With 2 breaking / 4 symbols → 50.0 |
| `test_affected_pct_zero_symbols` | old_symbol_count=0 → affected_pct=0.0 |

**Test type**: Unit test on `compatibility_metrics()`.

---

## Bug 3: `-o` silently creates parent directories

### Root Cause

In `cli.py:105-111`, `_safe_write_output()` calls `output.parent.mkdir(parents=True, exist_ok=True)`,
which silently creates any missing parent directories. This is by design but undocumented, and
could mask path typos.

### Fix Location

**File**: `abicheck/cli.py`, function `_safe_write_output()` (line 108)

### Fix Strategy

This is a low-severity issue with two valid approaches:

**Option A (recommended)**: Add a `--no-mkdir` flag or log a warning when directories are created.

```python
def _safe_write_output(output: Path, text: str) -> None:
    try:
        parent = output.parent
        if not parent.exists():
            _logger.info("Creating output directory: %s", parent)
            parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise click.ClickException(f"Cannot write to {output}: {exc}") from exc
```

**Option B**: Document the auto-creation behavior in CLI help text for `-o`. No code change
needed, just add to the help string.

### Testing

**File**: `tests/test_cli_unit.py` (extend existing)

| Test | Description |
|------|-------------|
| `test_output_creates_parent_dirs_with_warning` | Verify directory creation and log message |
| `test_output_existing_dir_no_warning` | Verify no warning when directory exists |

**Test type**: Integration test using `click.testing.CliRunner`.

---

## Bug 4: Policy file overrides don't update change severity in JSON output

### Root Cause

In `reporter.py:551-561`, `_change_to_dict()` calls `_kind_to_severity(kind, policy)` which
only uses the *base policy name* (e.g., `"strict_abi"`), not the effective kind sets that
include PolicyFile overrides. The code is already annotated with `# FIX-G`.

```python
def _change_to_dict(c: object, *, policy: str = "strict_abi") -> dict[str, object]:
    ...
    "severity": _kind_to_severity(kind, policy) if kind else "unknown",
```

Meanwhile, `DiffResult._effective_kind_sets()` (checker.py:160-185) correctly applies
PolicyFile overrides, but this method is not used in `_change_to_dict()`.

### Fix Location

**File**: `abicheck/reporter.py`
- Function `_change_to_dict()` (line 551): Add `kind_sets` parameter
- Function `to_json()` (line 521): Pass effective kind sets to `_change_to_dict()`

### Fix

1. Modify `_change_to_dict` to accept optional `kind_sets`:

```python
def _change_to_dict(
    c: object,
    *,
    policy: str = "strict_abi",
    kind_sets: tuple[frozenset, frozenset, frozenset, frozenset] | None = None,
) -> dict[str, object]:
    kind = getattr(c, "kind", None)
    if kind and kind_sets:
        breaking, api_break, compatible, risk = kind_sets
        if kind in breaking:
            severity = "breaking"
        elif kind in api_break:
            severity = "api_break"
        elif kind in risk:
            severity = "risk"
        elif kind in compatible:
            severity = "compatible"
        else:
            severity = "unknown"
    elif kind:
        severity = _kind_to_severity(kind, policy)
    else:
        severity = "unknown"
    ...
```

2. In `to_json()`, compute effective kind sets and pass them:

```python
eff_sets = result._effective_kind_sets()
d["changes"] = [_change_to_dict(c, policy=effective_policy, kind_sets=eff_sets) for c in changes]
```

### Testing

**File**: `tests/test_policy_file.py` (extend existing)

| Test | Description |
|------|-------------|
| `test_policy_override_severity_in_json` | With `func_removed: ignore` override, verify change severity is `"compatible"` not `"breaking"` |
| `test_policy_override_verdict_and_severity_consistent` | Verify verdict and individual change severities agree |
| `test_no_policy_file_severity_unchanged` | Without policy file, severity matches base policy |

**Test type**: Unit test — construct DiffResult with policy_file, call `to_json()`, parse JSON.

---

## Bug 5: `--dso-only` flag doesn't filter executables

### Root Cause

In `cli.py:1589-1592`, `--dso-only` filtering uses `_is_elf_shared_object()` from `package.py`.
This function checks the ELF `e_type` field for `ET_DYN` (value 3). The problem is that
**position-independent executables (PIE)** compiled with `-pie` (the GCC default on modern
Linux) also have `e_type == ET_DYN`, making them indistinguishable from shared objects at the
ELF header level.

The test executables (e.g., `app_v1`) are PIE executables, so `_is_elf_shared_object()` returns
True for them — they are technically `ET_DYN` binaries.

### Fix Location

**File**: `abicheck/package.py`, function `_is_elf_shared_object()` (line 579)

### Fix

Enhance `_is_elf_shared_object()` to distinguish PIE executables from true shared objects.
Use heuristics:

1. **Check for `.interp` section** (executables have it, pure DSOs don't) — most reliable.
2. **Check filename**: Shared objects typically contain `.so` in the name.
3. **Check for `DT_SONAME`**: Shared objects usually have a SONAME dynamic tag.

Best approach: combine filename heuristic with ELF header check:

```python
def _is_elf_shared_object(path: Path) -> bool:
    """Check if a file is an ELF shared object (ET_DYN) and not a PIE executable."""
    # Quick filename check: if it has .so in the name, it's likely a DSO
    name = path.name
    if ".so" not in name and not name.startswith("lib"):
        # No .so suffix and no lib prefix — likely an executable
        # Fall through to ELF check for edge cases
        pass

    try:
        with open(path, "rb") as f:
            magic = f.read(4)
            if magic != _ELF_MAGIC:
                return False
            # ... existing e_type check ...
            if e_type != _ET_DYN:
                return False

            # Distinguish PIE executable from DSO:
            # Scan for PT_INTERP program header — executables have it, DSOs don't
            return not _has_interp_segment(f, ei_class, byte_order)
    except OSError:
        return False
```

Where `_has_interp_segment()` reads the program header table and checks for `PT_INTERP`
(type 3). This is the most reliable method.

### Testing

**File**: `tests/test_compare_release.py` (extend existing)

| Test | Description |
|------|-------------|
| `test_dso_only_excludes_pie_executables` | Directory with both `libfoo.so` and `app` (PIE), verify `--dso-only` only compares `libfoo.so` |
| `test_dso_only_includes_shared_objects` | Verify .so files are not excluded |
| `test_dso_only_excludes_static_executables` | Non-PIE ET_EXEC also excluded |
| `test_is_elf_shared_object_pie_detection` | Unit test `_is_elf_shared_object()` on known PIE binary |

**Test type**: Mix of unit tests on `_is_elf_shared_object()` and integration tests with
`compare-release --dso-only`.

---

## Bug 6: `compare-release` gives `NO_CHANGE` when library is renamed

### Root Cause

In `cli.py:1620-1646`, when libraries don't match by canonical name, they go into `removed_keys`
and `added_keys` lists. These are reported as warnings (line 1625-1631) but **do not affect
`worst_verdict`** (line 1646, initialized to `"NO_CHANGE"`). The verdict only changes from
matched library comparisons. Removed libraries are only treated as failures when
`--fail-on-removed-library` is explicitly set (line 1776).

The comment at line 1770-1771 states this is intentional: "A removed library is a deployment
decision." However, this makes `NO_CHANGE` misleading when libraries are actually removed.

### Fix Location

**File**: `abicheck/cli.py`, function `compare_release_cmd()` (lines 1646, 1770-1777)

### Fix Strategy

The verdict should reflect reality. A removed library is not "NO_CHANGE" — it's at minimum
a warning. Two-part fix:

1. **Change default verdict** when `removed_keys` is non-empty: set `worst_verdict` to
   at least `"COMPATIBLE_WITH_RISK"` (rather than NO_CHANGE).

2. **In JSON output**, include removed/added libraries in the verdict computation:

```python
# After line 1646:
worst_verdict = "NO_CHANGE"

# After all matched-key comparisons complete (after the for loop):
if removed_keys and worst_verdict == "NO_CHANGE":
    worst_verdict = "COMPATIBLE_WITH_RISK"
```

This ensures:
- Removed libraries elevate verdict to at minimum COMPATIBLE_WITH_RISK
- `--fail-on-removed-library` still controls the exit code 8 behavior
- The verdict doesn't say NO_CHANGE when libraries are actually missing

### Testing

**File**: `tests/test_compare_release.py` (extend existing)

| Test | Description |
|------|-------------|
| `test_removed_library_not_no_change` | Old has libfoo.so, new doesn't → verdict != NO_CHANGE |
| `test_removed_library_verdict_compatible_with_risk` | Verify verdict is COMPATIBLE_WITH_RISK |
| `test_fail_on_removed_exit_code` | With `--fail-on-removed-library`, exit code is 8 |
| `test_added_library_no_verdict_change` | Added-only library doesn't affect verdict |
| `test_renamed_library_detected` | libfoo.so → libbar.so shows both removed and added |

**Test type**: Integration test using `click.testing.CliRunner`.

---

## Bug 7: JSON output missing `old_file`/`new_file` when comparing snapshots

### Root Cause

In `cli.py:339-356`, `_collect_metadata()` returns `None` for JSON snapshot inputs:

```python
def _collect_metadata(path: Path) -> LibraryMetadata | None:
    text_fmt = _sniff_text_format(path)
    if text_fmt in ("json", "perl"):
        return None  # ← intentionally returns None for snapshots
```

In `reporter.py:494-499`, `old_file`/`new_file` are only added to JSON when metadata is non-None:

```python
if old_meta:
    d["old_file"] = old_meta
if new_meta:
    d["new_file"] = new_meta
```

This is intentional (avoid misleading metadata for serialized files), but the result is an
inconsistent JSON schema — the keys are present for binary inputs but absent for snapshots.

### Fix Location

**File**: `abicheck/reporter.py`, function `to_json()` (lines 494-499)

### Fix

Always include the keys, using `null` when metadata isn't available:

```python
d["old_file"] = _metadata_dict(getattr(result, "old_metadata", None))
d["new_file"] = _metadata_dict(getattr(result, "new_metadata", None))
```

Where `_metadata_dict()` already returns `None` for `None` input. The JSON output will have:
- Binary inputs: `"old_file": {"path": "...", "sha256": "...", "size": ...}`
- Snapshot inputs: `"old_file": null`

This makes the schema consistent and avoids KeyError for consumers.

### Testing

**File**: `tests/test_report_metadata.py` (extend existing) or `tests/test_serialization.py`

| Test | Description |
|------|-------------|
| `test_json_schema_has_old_new_file_keys_always` | Both binary and snapshot comparison JSON contain `old_file` and `new_file` keys |
| `test_json_snapshot_file_metadata_is_null` | Snapshot comparison has `"old_file": null` |
| `test_json_binary_file_metadata_populated` | Binary comparison has full metadata dict |

**Test type**: Unit test — construct DiffResult with/without metadata, call `to_json()`.

---

## Bug 8: `--lang c` with C++ headers produces unhelpful castxml error

### Root Cause

In `dumper.py:355-357`, when `--lang c` is explicitly set, `force_cpp` is False and the
auto-detection is skipped:

```python
force_cpp = lang and lang.upper() in ("C++", "CPP")  # False for --lang c
if not lang:                                           # skipped (lang="c")
    force_cpp = _detect_cpp_headers(headers)
```

This correctly honors the user's explicit choice, but when castxml subsequently fails with
a cryptic compiler error (`error: use of undeclared identifier 'class'`), the error message
doesn't explain *why* it failed.

### Fix Location

**File**: `abicheck/dumper.py`, function `_castxml_dump()` (lines 388-392)

### Fix

Add a diagnostic hint when castxml fails in C mode and the headers contain C++ syntax:

```python
if result.returncode != 0:
    hint = ""
    if not force_cpp and _detect_cpp_headers(headers):
        hint = (
            "\n\nHint: The header files appear to contain C++ syntax "
            "(class, namespace, template) but --lang c was specified. "
            "Try removing --lang or using --lang c++."
        )
    raise RuntimeError(
        f"castxml failed (exit {result.returncode}):\n"
        f"{result.stderr[:2000]}{hint}"
    )
```

This preserves the user's explicit choice (we don't auto-override `--lang c`) but provides
actionable guidance when it causes a failure.

### Testing

**File**: `tests/test_castxml_errors.py` (extend existing)

| Test | Description |
|------|-------------|
| `test_lang_c_with_cpp_header_shows_hint` | `--lang c` with C++ header → error message includes hint about C++ syntax |
| `test_lang_c_with_c_header_no_hint` | `--lang c` with pure C header → no hint in error |
| `test_lang_cpp_with_cpp_header_succeeds` | `--lang c++` with C++ header → success, no hint |

**Test type**: Integration test (requires castxml).

---

## Bug 9: Invalid header causes unhandled castxml timeout

### Root Cause

In `dumper.py:387-388`, `subprocess.run()` has `timeout=120` but the `TimeoutExpired` exception
is not caught. The existing `try` block catches `RuntimeError` and handles cleanup in `finally`,
but `subprocess.TimeoutExpired` propagates as an unhandled exception, printing a full stack
trace.

```python
try:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    # ... error checks ...
finally:
    agg_path.unlink(missing_ok=True)
    out_xml.unlink(missing_ok=True)
```

### Fix Location

**File**: `abicheck/dumper.py`, function `_castxml_dump()` (line 387-388)

### Fix

Catch `subprocess.TimeoutExpired` and convert it to a user-friendly `RuntimeError`:

```python
try:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
except subprocess.TimeoutExpired as exc:
    stderr_snippet = ""
    if exc.stderr:
        text = exc.stderr if isinstance(exc.stderr, str) else exc.stderr.decode("utf-8", errors="replace")
        stderr_snippet = f"\nPartial stderr: {text[:1000].strip()}"
    raise RuntimeError(
        f"castxml timed out after 120 seconds. The header file may contain "
        f"syntax that causes the compiler to hang. Check that the header "
        f"is valid and can be compiled with gcc/g++.{stderr_snippet}"
    ) from exc
```

This gives a clear, actionable error message instead of a stack trace.

### Testing

**File**: `tests/test_castxml_errors.py` (extend existing)

| Test | Description |
|------|-------------|
| `test_castxml_timeout_handled_gracefully` | Mock `subprocess.run` to raise `TimeoutExpired`, verify `RuntimeError` with user-friendly message |
| `test_castxml_timeout_message_content` | Verify message mentions timeout duration and suggests checking header validity |
| `test_castxml_timeout_cleanup` | Verify temp files are cleaned up even on timeout |

**Test type**: Unit test with `unittest.mock.patch` on `subprocess.run`.

---

## Implementation Priority

| Priority | Bug | Severity | Effort | Rationale |
|----------|-----|----------|--------|-----------|
| P0 | Bug 9 | High | Small | Unhandled exception → stack trace. Simple try/except. |
| P0 | Bug 6 | High | Small | Misleading NO_CHANGE verdict. One-line fix. |
| P1 | Bug 2 | Medium | Trivial | `min(100.0, ...)` wrapper. |
| P1 | Bug 4 | Medium | Medium | FIX-G already annotated. Pass kind_sets through. |
| P1 | Bug 1 | Medium | Medium | Add filtered_summary or show_only_applied to JSON. |
| P2 | Bug 5 | Medium | Medium | PIE detection requires PT_INTERP parsing. |
| P2 | Bug 7 | Low | Trivial | Always include keys with null fallback. |
| P2 | Bug 8 | Low | Small | Add diagnostic hint on failure. |
| P3 | Bug 3 | Low | Trivial | Add log message or document behavior. |

---

## Test Execution Plan

All tests should be runnable via:

```bash
# Run only bugfix regression tests
pytest tests/ -k "bug" -v

# Run with specific markers
pytest tests/ -m "not slow and not integration" -v   # unit tests only
pytest tests/ -m "integration" -v                     # integration tests (need castxml+gcc)
```

### Test Categories by Bug

| Bug | Test Type | Requires castxml? | Requires compilation? |
|-----|-----------|-------------------|----------------------|
| 1 | Unit | No | No |
| 2 | Unit | No | No |
| 3 | Integration | No | No |
| 4 | Unit | No | No |
| 5 | Unit + Integration | No (unit) / Yes (integration) | Yes (integration) |
| 6 | Integration | Yes | Yes |
| 7 | Unit | No | No |
| 8 | Integration | Yes | No |
| 9 | Unit (mocked) | No | No |

### Regression Test File

Create a single `tests/test_bugfix_batch1.py` file containing all unit-testable bug
regressions (Bugs 1, 2, 4, 7, 9). This keeps regression tests organized and easy to run:

```bash
pytest tests/test_bugfix_batch1.py -v
```

Integration tests for Bugs 3, 5, 6, 8 should be added to existing test files
(`test_compare_release.py`, `test_castxml_errors.py`, `test_cli_unit.py`) following
existing patterns and markers.
