# abicheck Bug Report

**Tool version:** 0.2.0
**Platform:** Linux x86_64 (Ubuntu 24.04, GCC 13.3.0, castxml 0.6.3)
**Date:** 2026-03-18

## Summary

Testing abicheck against real compiled shared libraries with various use cases
uncovered **8 confirmed bugs** ranging from duplicate detection to incorrect
report formatting and unhandled errors.

---

## Bug 1: Duplicate Enum Change Detection (HIGH)

**Command:**
```bash
abicheck compare v1/libenum.so v2/libenum.so \
  --old-header v1/libenum.h --new-header v2/libenum.h
```

**Problem:** Each enum member value change is reported **twice** — once from the
header/AST-based detector (symbol=`Color`, description `Enum member value
changed: Color::GREEN`) and once from the DWARF-based detector
(symbol=`Color::GREEN`, description `Enum member value changed: Color::GREEN (1
→ 2)`). The two entries have slightly different formats but describe the same
semantic change.

**Expected:** Each enum value change should appear exactly once. The two
detection paths (AST and DWARF) should be deduplicated.

**Impact:** Inflated breaking change counts (4 reported instead of 2), misleading
CI gate decisions, confusing reports.

**Reproduction JSON output:**
```
enum_member_value_changed  symbol=Color          old=1 new=2  (from AST)
enum_member_value_changed  symbol=Color          old=2 new=3  (from AST)
enum_member_value_changed  symbol=Color::GREEN   old=1 new=2  (from DWARF)
enum_member_value_changed  symbol=Color::BLUE    old=2 new=3  (from DWARF)
```

---

## Bug 2: `func_params_changed` Shows Raw Python Repr in C Mode (MEDIUM)

**Command:**
```bash
abicheck compare v1/libtest.so v2/libtest.so \
  --old-header v1/libtest.h --new-header v2/libtest.h --lang c
```

**Problem:** When a function's parameter types change and `--lang c` is used, the
description exposes internal Python types in the old/new values:

```
Parameters changed: multiply
  (`[('int', <ParamKind.VALUE: 'value'>), ('int', <ParamKind.VALUE: 'value'>)]`
   → `[('long int', <ParamKind.VALUE: 'value'>), ('long int', <ParamKind.VALUE: 'value'>)]`)
```

**Expected:** Human-readable formatting like:
```
Parameters changed: multiply (`int, int` → `long int, long int`)
```

**Impact:** Poor user experience, confusing reports. The raw `<ParamKind.VALUE:
'value'>` text is meaningless to users.

---

## Bug 3: Snapshot Comparison Shows JSON File Metadata Instead of Library Metadata (MEDIUM)

**Command:**
```bash
abicheck dump v1/libtest.so -H v1/libtest.h --version 1.0 -o baseline.json
abicheck dump v2/libtest.so -H v2/libtest.h --version 2.0 -o v2.json
abicheck compare baseline.json v2.json
```

**Problem:** The "Library Files" section in the report shows the JSON snapshot
file's path, size, and SHA-256 hash instead of the original library's metadata:

```
| **Path** | `baseline.json` | `v2.json` |
| **SHA-256** | `26cc72e9ca99…` | `78bcebe8d25e…` |
| **Size** | 5.2 KB | 4.0 KB |
```

**Expected:** The report should show the original library path/size/hash as
stored in the snapshot (e.g., `v1/libtest.so`, 15.9 KB).

**Impact:** Misleading file information. Users see JSON file sizes (5.2 KB)
instead of actual library sizes (15.9 KB), which could be confusing when
reviewing ABI reports.

---

## Bug 4: Policy File Override Changes Verdict But Not Report Section Headers (MEDIUM)

**Command:**
```bash
# Policy file that downgrades func_removed to "warn"
cat > policy.yaml << 'EOF'
version: 1
overrides:
  func_removed: warn
EOF

abicheck compare v1/libtest.so v2/libtest.so \
  --old-header v1/libtest.h --new-header v2/libtest.h \
  --policy-file policy.yaml
```

**Problem:** The verdict correctly changes to `API_BREAK` (exit 2) reflecting the
downgraded severity, but the report body still shows the changes under **"❌
Breaking Changes"** heading with `func_removed` labels. The section header does
not reflect that the policy reclassified these changes.

**Expected:** Changes reclassified by policy should appear under the appropriate
section header (e.g., "⚠️ Deployment Risk Changes" or "⚠️ Warnings") matching
their effective severity, not their original severity.

**Similarly for `--policy-file` with `enum_member_value_changed: ignore`:** The
verdict becomes `COMPATIBLE` (exit 0), but the summary still says "Breaking
changes: 4" and lists them under "❌ Breaking Changes".

---

## Bug 5: Unhandled Exception When Output Directory Doesn't Exist (LOW)

**Command:**
```bash
abicheck compare v1/libtest.so v2/libtest.so \
  --old-header v1/libtest.h --new-header v2/libtest.h \
  -o /nonexistent/dir/report.md
```

**Problem:** The tool crashes with a raw Python traceback:
```
FileNotFoundError: [Errno 2] No such file or directory: '/nonexistent/dir/report.md'
```

**Expected:** A user-friendly error message like:
```
Error: Output directory '/nonexistent/dir' does not exist.
```

**Location:** `abicheck/cli.py:1103` — `output.write_text(text, encoding="utf-8")`

---

## Bug 6: `compare-release` Treats Object Files (.o) as Libraries (LOW)

**Command:**
```bash
abicheck compare-release v1/ v2/ -H v1/libtest.h
```

**Problem:** When scanning directories, `compare-release` picks up `.o` (object)
files and reports them. In the test, `libtest.o` was listed under "⚠️ Removed
Libraries" even though object files are not shared libraries and should be
excluded from ABI comparison.

**Expected:** `compare-release` should filter to recognized shared library
extensions (`.so`, `.so.*`, `.dylib`, `.dll`) and ELF shared object type, skipping
`.o`, `.a`, and other non-shared-library files.

---

## Bug 7: `deps` Silently Reports PASS for Non-ELF Files (LOW)

**Command:**
```bash
abicheck deps /usr/bin/which  # this is a shell script
```

**Problem:** The `deps` command emits a WARNING about magic number mismatch but
still reports `Loadability: PASS`, `ABI risk: PASS`, `Risk score: low`. This is
misleading — a shell script has no ELF dependencies to analyze.

**Expected:** The tool should fail with a clear error when the input is not an
ELF binary, or at minimum set loadability to UNKNOWN/SKIP rather than PASS.

---

## Bug 8: `affected_pct` Always Reports 0.0 in JSON Output (LOW)

**Command:**
```bash
abicheck compare v1/libtest.so v2/libtest.so \
  --old-header v1/libtest.h --new-header v2/libtest.h --format json
```

**Problem:** The JSON summary field `affected_pct` is always `0.0` even when 2
out of 3 functions are affected (subtract removed, multiply changed):

```json
"summary": {
    "breaking": 2,
    "total_changes": 3,
    "binary_compatibility_pct": 33.3,
    "affected_pct": 0.0
}
```

**Expected:** `affected_pct` should reflect the percentage of original symbols
that are affected by changes (e.g., ~66.7% since 2 of 3 original functions
changed).

---

## Additional Observations (Not Bugs, But Noteworthy)

### C++ Name Mangling Masks Parameter Changes

When comparing C++ libraries (default `--lang c++`), a function like
`multiply(int, int)` → `multiply(long, long)` is reported as `func_removed` +
`func_added` (two separate mangled symbols) rather than `func_params_changed`.
This is technically correct since the mangled names differ, but it masks the
real semantic change. In `--lang c` mode, the same change is correctly
reported as `func_params_changed`.

### `-H` (Shared Header) Can Produce Wrong Results

Using `-H` applies the same header to both old and new sides. If the API changed,
this means one side gets the wrong header, leading to incorrect analysis (e.g.,
`subtract` reported as "visibility changed to hidden" instead of "removed"
because the old header declares it but the new binary doesn't export it).

### `compare-release` With Wrong Shared Header

Using `-H` in `compare-release` applies the header to ALL libraries in the
directories. This gives incorrect results for libraries that don't match the
header (e.g., `libreturn.so` reported as NO_CHANGE when it actually changed).

---

## Test Environment Setup

All tests used hand-compiled shared libraries with DWARF debug info:

```bash
# Example compilation
gcc -shared -fPIC -g -o v1/libtest.so v1/libtest.c
gcc -shared -fPIC -g -o v2/libtest.so v2/libtest.c
```

**Tools:** Python 3.11, castxml 0.6.3, GCC 13.3.0, pyelftools 0.32

**Total tests run:** 54
**Bugs found:** 8
**Tests passing correctly:** 46
