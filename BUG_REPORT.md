# abicheck Bug Report

**Tool version**: 0.2.0
**Platform**: Linux x86_64, GCC, castxml 0.6.3
**Date**: 2026-03-19

---

## Test Summary

Comprehensive testing was performed across 63 example cases, edge cases, all output formats, dump/snapshot roundtrip, appcompat, compare-release, deps, policy files, suppression files, and various CLI option combinations.

- **63 example cases**: 61 correct, 2 known-gap mismatches (case49, case62)
- **9 bugs found** (detailed below)

---

## Bug 1: `--show-only` JSON output — summary/changes inconsistency

**Severity**: Medium
**Command**:
```bash
abicheck compare libv1.so libv2.so --show-only breaking --format json
```

**Expected**: When `--show-only breaking` filters out non-breaking changes, the JSON `summary` section should either also reflect the filtered view, or the output should clearly distinguish between full summary and filtered changes.

**Actual**: The `changes` array is empty (filtered), but `summary` still shows `risk_changes: 1` and `total_changes: 1`. This creates an inconsistency where the summary counts don't match the visible changes array.

**Reproduction**:
```bash
abicheck compare examples/build/case15_noexcept_change/libv1.so \
  examples/build/case15_noexcept_change/libv2.so \
  --old-header examples/case15_noexcept_change/v1.h \
  --new-header examples/case15_noexcept_change/v2.h \
  --show-only breaking --format json
# Result: changes=[], but summary.risk_changes=1, summary.total_changes=1
```

---

## Bug 2: `affected_pct` exceeds 100%

**Severity**: Medium
**Command**:
```bash
abicheck compare libv1.so libv2.so --format json
```

**Expected**: `affected_pct` should be capped at 100.0 or the calculation should not produce values over 100%.

**Actual**: When a library has multiple changes affecting the same function (e.g., `func_return_changed` + `func_params_changed` for the same function), `affected_pct` can exceed 100% (observed: `125.0`).

**Reproduction**:
```bash
# Create libs where one function has both return type and parameter changes
# plus another function is removed
abicheck compare /tmp/libmulti_v1.so /tmp/libmulti_v2.so \
  --old-header /tmp/test_multi_v1.h --new-header /tmp/test_multi_v2.h --format json
# Result: "affected_pct": 125.0
```

---

## Bug 3: `-o` silently creates parent directories that don't exist

**Severity**: Low
**Command**:
```bash
abicheck compare libv1.so libv2.so -o /nonexistent/dir/output.json --format json
```

**Expected**: Either fail with an error that the output directory doesn't exist, or document the auto-creation behavior.

**Actual**: Silently creates `/nonexistent/dir/` and writes the file. Reports "Report written to /nonexistent/dir/output.json" with exit code 4 (from the BREAKING verdict). While auto-creation can be convenient, it's unexpected and could mask path typos (e.g., writing to `/tmp/typo_dir/report.json` instead of `/tmp/reports/report.json`).

---

## Bug 4: Policy file overrides don't update change severity in JSON output

**Severity**: Medium
**Command**:
```bash
abicheck compare libv1.so libv2.so --policy-file policy.yaml --format json
```
Where `policy.yaml` contains:
```yaml
base_policy: strict_abi
overrides:
  func_removed: ignore
```

**Expected**: When a policy override downgrades `func_removed` from `breaking` to `ignore` (COMPATIBLE), the change entry in JSON should reflect `"severity": "compatible"` or `"severity": "ignored"`.

**Actual**: The verdict correctly changes to `COMPATIBLE`, but the individual change still shows `"severity": "breaking"` in the JSON output. This is confusing — the change is classified as breaking severity but the verdict says compatible.

**Reproduction**:
```bash
abicheck compare examples/build/case01_symbol_removal/libv1.so \
  examples/build/case01_symbol_removal/libv2.so \
  --old-header examples/case01_symbol_removal/v1.h \
  --new-header examples/case01_symbol_removal/v2.h \
  --policy-file /tmp/test_policy.yaml --format json
# Result: verdict=COMPATIBLE, but changes[0].severity="breaking"
```

---

## Bug 5: `--dso-only` flag in `compare-release` doesn't filter executables

**Severity**: Medium
**Command**:
```bash
abicheck compare-release /old_dir /new_dir --dso-only
```

**Expected**: With `--dso-only`, only shared libraries (.so files) should be compared, and executables should be excluded.

**Actual**: Executables (e.g., `app_v1`) are still included in the comparison results. The output is identical with and without `--dso-only`.

**Reproduction**:
```bash
mkdir -p /tmp/rel_old /tmp/rel_new
cp examples/build/case01_symbol_removal/libv1.so /tmp/rel_old/libtest.so
cp examples/build/case01_symbol_removal/app_v1 /tmp/rel_old/
cp examples/build/case01_symbol_removal/libv2.so /tmp/rel_new/libtest.so
cp examples/build/case01_symbol_removal/app_v1 /tmp/rel_new/

# Both produce identical output including app_v1:
abicheck compare-release /tmp/rel_old /tmp/rel_new --dso-only
abicheck compare-release /tmp/rel_old /tmp/rel_new
```

---

## Bug 6: `compare-release` gives `NO_CHANGE` when library is renamed (removed + added)

**Severity**: High
**Command**:
```bash
abicheck compare-release /old_dir /new_dir
```

**Expected**: When a library is removed from old and a different-named library is added to new, the verdict should indicate a potential breaking change (at minimum a warning), since consumers depending on the old library name will fail to load.

**Actual**: Verdict is `NO_CHANGE` even though the output correctly shows "Removed Libraries: libv1.so" and "Added Libraries: libv2.so". A renamed library is effectively a removal for existing consumers.

**Reproduction**:
```bash
mkdir -p /tmp/rel_old /tmp/rel_new
cp examples/build/case01_symbol_removal/libv1.so /tmp/rel_old/
cp examples/build/case01_symbol_removal/libv2.so /tmp/rel_new/
abicheck compare-release /tmp/rel_old /tmp/rel_new
# Result: Verdict: NO_CHANGE, but shows "Removed Libraries: libv1.so"
```

---

## Bug 7: JSON output missing `old_file`/`new_file` when comparing snapshots

**Severity**: Low
**Command**:
```bash
abicheck compare snapshot_v1.json snapshot_v2.json --format json
```

**Expected**: JSON output should include `old_file` and `new_file` metadata sections (or at least a note that they're not available from snapshots).

**Actual**: The `old_file` and `new_file` keys are completely absent from the JSON output when comparing snapshots. This makes the JSON schema inconsistent — consumers parsing the JSON may get KeyError or need to handle both cases.

**Reproduction**:
```bash
abicheck dump libv1.so --header v1.h --version 1.0 -o snap_v1.json
abicheck dump libv2.so --header v2.h --version 2.0 -o snap_v2.json
abicheck compare snap_v1.json snap_v2.json --format json
# Result: JSON has no "old_file" or "new_file" keys
```

---

## Bug 8: `--lang c` with C++ headers produces unhelpful castxml error

**Severity**: Low
**Command**:
```bash
abicheck compare libv1.so libv2.so --old-header v1.hpp --new-header v2.hpp --lang c
```

**Expected**: Either auto-detect the language from the header content/extension, or provide a clear error message saying "C++ headers detected but --lang c was specified".

**Actual**: castxml fails with a raw compiler error (`error: use of undeclared identifier 'class'`) which is confusing for users who may not understand why their header fails.

**Reproduction**:
```bash
abicheck compare examples/build/case09_cpp_vtable/libv1.so \
  examples/build/case09_cpp_vtable/libv2.so \
  --old-header examples/case09_cpp_vtable/v1.h \
  --new-header examples/case09_cpp_vtable/v2.h --lang c
# Result: "castxml failed (exit 1): error: use of undeclared identifier 'class'"
```

---

## Bug 9: Invalid header causes unhandled castxml timeout (120s hang + stack trace)

**Severity**: High
**Command**:
```bash
echo "struct {{{ invalid C" > /tmp/bad_header.h
abicheck compare libv1.so libv2.so --old-header /tmp/bad_header.h --new-header /tmp/bad_header.h
```

**Expected**: castxml should fail quickly on a syntactically invalid header, and abicheck should catch the error and display a user-friendly message like "Header file failed to parse".

**Actual**: castxml hangs for the full 120-second timeout, then abicheck crashes with an unhandled `subprocess.TimeoutExpired` exception, printing a full Python stack trace to the user. The error is not caught or handled gracefully.

**Stack trace**:
```
File "/home/user/abicheck/abicheck/dumper.py", line 388, in _castxml_dump
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
subprocess.TimeoutExpired: Command '['castxml', ...]' timed out after 120 seconds
```

**Impact**: Users with malformed headers experience a 2-minute hang followed by a confusing stack trace instead of an immediate, actionable error message.

---

## Additional Observations (Not Bugs)

### Known Gaps Confirmed
- **case49** (executable stack): Tool returns `NO_CHANGE` — expected, as executable stack is a linker flag not detectable via symbol/type analysis.
- **case62** (type field added compatible): Tool returns `BREAKING` — struct_size_changed fires because Session grows; tool cannot determine the struct is opaque.

### Positive Findings
- All 4 output formats (markdown, json, sarif, html) produce valid output
- Dump/snapshot roundtrip is fully consistent with direct comparison
- Appcompat correctly filters changes to only those affecting the application
- Suppression files work correctly with both exact matches and patterns
- Error handling is good for: missing files, wrong formats, empty files, corrupted JSON, invalid arguments
- Performance is excellent: 500 functions compared in 0.38s
- `--strict-elf-only` correctly elevates ELF-only removals to BREAKING
- `deps` command correctly resolves dependency trees
