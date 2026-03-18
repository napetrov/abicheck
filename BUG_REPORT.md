# Bug Report: abicheck Real-World Testing Findings

**Date:** 2026-03-18
**Version:** 0.2.0
**Platform:** Linux x86_64, GCC 13.3.0, castxml 0.6.3
**Tester:** Automated testing via Claude Code

## Summary

Systematic testing of `abicheck` with real compiled C and C++ shared libraries
uncovered **12 bugs** across core comparison logic, output formatting, edge case
handling, and CLI behavior. Several are high-severity issues that could cause
CI/CD pipelines to miss genuine ABI breaks.

---

## Bug 1 (HIGH): Stripped binary function removal misclassified as COMPATIBLE

**Severity:** HIGH — CI/CD false negative
**Command:**
```bash
abicheck compare libtest_v1_stripped.so libtest_v2_stripped.so
```

**Expected:** `process_array` removal is a breaking ABI change (exit code 4).
**Actual:** Verdict is `COMPATIBLE` (exit code 0). The removal is reported as
`func_removed_elf_only` and listed under "Compatible Additions".

**Impact:** A stripped library that removes a public function is silently
classified as compatible. Any CI/CD pipeline relying on exit codes will pass
when it should fail. The dynamic linker will refuse to load old binaries that
reference the removed symbol.

**Reproduction:**
```bash
gcc -shared -fPIC -o libv1.so v1.c && strip libv1.so
gcc -shared -fPIC -o libv2.so v2.c && strip libv2.so  # v2 removes process_array
abicheck compare libv1.so libv2.so --stat
# Output: COMPATIBLE: 3 compatible (3 total)
# Exit code: 0
```

---

## Bug 2 (HIGH): Header-based analysis reports signature changes as removal + addition

**Severity:** HIGH — Incorrect change classification
**Command:**
```bash
abicheck compare libv1.so libv2.so -H v1.h --new-header v2.h --format json
```

**Expected:** Functions whose signatures changed (e.g. `add(int, int)` →
`add(int, int, int)`) should be reported as `func_params_changed`.
**Actual:** They are reported as `func_removed` for the old C++-mangled name
(`_Z3addii`) AND `func_added` for the new mangled name (`_Z3addiii`).

This happens because castxml assigns C++ mangled names to C functions. The
mangled names differ when parameters change, so the checker sees them as
different symbols.

**Contrast with DWARF-only mode:** DWARF-only correctly reports
`func_params_changed` for `add` and `param_pointer_level_changed` for
`compute`, since DWARF uses the linker symbol name `add` (no mangling).

**Affected functions in test case:**
- `add` — reported as removed `_Z3addii` + added `_Z3addiii`
- `compute` — reported as removed `_Z7compute5Pointd` + added `_Z7computeP5Pointd`
- `log_message` — reported as removed `_Z11log_messagePKcz` + added `_Z11log_messagePKc`
- `register_callback` — reported as removed/added with different callback types

---

## Bug 3 (MEDIUM): Duplicate enum changes in DWARF-only mode

**Severity:** MEDIUM — Inflated change counts
**Command:**
```bash
abicheck compare libv1.so libv2.so --dwarf-only --format json
```

**Expected:** Each enum value change reported once.
**Actual:** `enum_member_value_changed` reported TWICE per member:
1. `"Enum member value changed: Color::GREEN"` (no values in description)
2. `"Enum member value changed: Color::GREEN (1 → 2)"` (values in description)

Both have identical `kind`, `symbol`, `old_value`, `new_value` but different
`description` strings. Both are emitted even in DWARF-only mode, suggesting two
separate analysis paths (DWARF enums vs DWARF advanced) independently detect the
same change without deduplication.

**Impact:** Change counts are inflated (4 enum changes instead of 2). This
also inflates the "breaking changes" count shown in summaries and can cause
suppression rules to match multiple times.

---

## Bug 4 (MEDIUM): Duplicate struct field offset changes from different evidence tiers

**Severity:** MEDIUM — Redundant output, inflated counts
**Command:**
```bash
abicheck compare libv1.so libv2.so --dwarf-only --format markdown
```

**Expected:** Each field offset change reported once.
**Actual:** Two different change kinds report the same change:
- `type_field_offset_changed`: "Field offset changed: Point::x (0 → 32 bits)"
- `struct_field_offset_changed`: "Field offset changed: Point::x (+0 → +4)"

These come from different evidence tiers (DWARF type analysis vs DWARF layout
analysis) and use different units (bits vs bytes), but represent the same
underlying change. Both count toward the breaking changes total.

**Impact:** A single field offset change is counted as 2 breaking changes,
inflating severity metrics.

---

## Bug 5 (MEDIUM): JSON output lacks per-change severity/verdict

**Severity:** MEDIUM — JSON consumers cannot classify changes
**Command:**
```bash
abicheck compare libv1.so libv2.so --dwarf-only --format json
```

**Expected:** Each change in the JSON `changes` array should include a
`severity` or `verdict` field (e.g., `"severity": "breaking"`,
`"severity": "compatible"`, `"severity": "source_break"`).
**Actual:** Change objects only have: `kind`, `symbol`, `description`,
`old_value`, `new_value`, `impact`, `affected_symbols`, `caused_count`.

The markdown format clearly separates changes into "Breaking Changes",
"Source-Level Breaks", and "Compatible Additions" sections, but this
categorization is lost in JSON.

**Impact:** Programmatic consumers of the JSON output cannot determine which
changes are breaking vs compatible without hardcoding the
kind-to-severity mapping from `checker_policy.py`.

---

## Bug 6 (MEDIUM): `--report-mode leaf` JSON uses different keys than standard mode

**Severity:** MEDIUM — JSON schema inconsistency
**Command:**
```bash
abicheck compare libv1.so libv2.so --dwarf-only --report-mode leaf --format json
```

**Expected:** Leaf-mode JSON should populate `changes` list (same key as standard mode).
**Actual:**
- `changes` key exists but is empty (`[]`)
- Data is split across `leaf_changes` (18 items) and `non_type_changes` (11 items)

**Impact:** Any JSON consumer (CI scripts, MCP clients, SARIF converters) that
reads `data["changes"]` will see 0 changes in leaf mode despite a `BREAKING`
verdict. This is a breaking schema change between report modes.

---

## Bug 7 (MEDIUM): C++ DWARF-only dump extracts 0 functions

**Severity:** MEDIUM — Reduced C++ analysis quality
**Command:**
```bash
abicheck dump libcpptest.so --dwarf-only
```

**Expected:** DWARF function entries extracted for C++ member functions.
**Actual:** `"functions": []` in the JSON snapshot. Types (classes, vtables)
are correctly extracted, but no function signatures.

**Contrast:** C library DWARF dump correctly extracts 9 functions.
C++ library with headers correctly extracts 12 functions.

**Impact:** C++ DWARF-only analysis only detects type/layout/vtable changes
but misses function signature changes. The compare-release command (which
doesn't accept headers) falls back to ELF-only symbol comparison for C++
libraries, missing type-level breaks entirely.

---

## Bug 8 (MEDIUM): `compare-release` falsely reports "no DWARF" for C++ libraries

**Severity:** MEDIUM — Misleading diagnostic
**Command:**
```bash
abicheck compare-release release_v1/ release_v2/  # dirs with C++ .so files
```

**Expected:** DWARF debug info is detected and used.
**Actual:** Warning: "No headers provided and no DWARF debug info — only
ELF-exported symbols will be captured" for C++ libraries.

`readelf --debug-dump=info` confirms DWARF sections are present. This is a
consequence of Bug 7 — since 0 functions are extracted from C++ DWARF, the
dumper falls through to the "no DWARF" warning path.

**Impact:** C++ library comparisons in `compare-release` silently degrade to
ELF-only mode (5 changes detected instead of 10-11).

---

## Bug 9 (LOW): Compiler internal types reported as breaking ABI changes

**Severity:** LOW — False positives from compiler internals
**Command:**
```bash
abicheck compare libv1.so libv2.so --dwarf-only --format markdown
```

**Observed:** These compiler-internal types are reported as breaking:
- `type_removed: __va_list_tag` — Breaking
- `typedef_removed: __gnuc_va_list` — Breaking
- `typedef_removed: __builtin_va_list` — Breaking
- `typedef_removed: va_list` — Breaking

When comparing against an empty library, `size_t` is also reported.

**Impact:** These types are compiler implementation details, not part of the
library's public ABI. They inflate the breaking change count. `va_list` is
only present when variadic functions use it; `__va_list_tag` and
`__builtin_va_list` should never be in the public ABI surface.

---

## Bug 10 (LOW): Excessive "Duplicate mangled symbol" warnings with headers

**Severity:** LOW — Noisy output
**Command:**
```bash
abicheck compare libv1.so libv1.so -H v1.h  # self-compare
```

**Expected:** Clean output (NO_CHANGE, no warnings).
**Actual:** 12 warnings emitted:
```
WARNING: Duplicate mangled symbol skipped (first-wins): Point in libtest_v1.so@old
WARNING: Duplicate mangled symbol skipped (first-wins): Point in libtest_v1.so@old
WARNING: Duplicate mangled symbol skipped (first-wins): Point in libtest_v1.so@old
WARNING: Duplicate mangled symbol skipped (first-wins): Record in libtest_v1.so@old
...
```

Each struct name triggers 3 warnings per side (6 per struct, 12 total for
Point + Record). These appear because castxml generates multiple entries
for struct/union types that get treated as mangled symbol names.

**Impact:** Noisy output that obscures real issues. In CI logs, these warnings
could be confused with actual problems.

---

## Bug 11 (HIGH): `appcompat` with headers shows 0 relevant changes despite breaking changes

**Severity:** HIGH — Incorrect appcompat output
**Command:**
```bash
abicheck appcompat app libv1.so libv2.so -H v1.h --format markdown
```

**Expected:** Relevant changes shown (struct layout breaks, enum changes, etc.
affecting app's symbols).
**Actual:** "Relevant Changes (0 of 11 total) — None of the library's ABI
changes affect your application."

**Contrast:** Without `-H`, the same command correctly shows 17 relevant
changes.

The `process_array` missing symbol IS correctly detected in both cases,
but the type-level changes that affect `add`, `compute`, `create_record`,
`free_record` are not mapped to the app's symbols when headers are used.

**Root cause hypothesis:** Header-based analysis uses C++-mangled symbol
names (Bug 2), which don't match the ELF import symbols extracted from the
application binary (which uses C linkage names like `add`, not `_Z3addii`).

---

## Bug 12 (LOW): `--show-only source` changes exit code from 4 to 2

**Severity:** LOW — Inconsistent exit code semantics
**Command:**
```bash
abicheck compare libv1.so libv2.so --dwarf-only --show-only source
# Exit code: 2 (API_BREAK)

abicheck compare libv1.so libv2.so --dwarf-only --show-only breaking
# Exit code: 4 (BREAKING)

abicheck compare libv1.so libv2.so --dwarf-only
# Exit code: 4 (BREAKING)
```

**Expected:** Exit code reflects the full comparison verdict (4 = BREAKING)
regardless of display filter, since `--show-only` is a display filter, not
a verdict modifier.
**Actual:** `--show-only source` changes exit code to 2 (API_BREAK).

**Impact:** CI/CD workflows that use `--show-only source` to focus on
source-level changes will see a different exit code than the actual verdict.
The markdown output still shows "Verdict: BREAKING" even when exit code is 2.

---

## Test Environment

**Libraries built:**
- `libtest_v1.so` / `libtest_v2.so` — C library with 8+ intentional ABI breaks
- `libcpptest_v1.so` / `libcpptest_v2.so` — C++ library with vtable, layout, size changes
- `libtest_v1_stripped.so` / `libtest_v2_stripped.so` — Stripped (no debug info)
- `libempty.so` — Empty library (no symbols)
- `app` / `cppapp` — Consumer applications linked against v1

**ABI changes introduced in v2:**
- Struct field reordering (Point: x↔y)
- Struct size increase (Point: +z field, Record: name 32→64, id int→long)
- Enum value reassignment (GREEN: 1→2, BLUE: 2→1)
- Function parameter addition (add: 2→3 params)
- Pass-by-value to pointer (compute)
- Function removal (process_array)
- Variadic→non-variadic (log_message)
- Callback signature change (callback_t)
- New function addition (multiply)

**Commands tested:** `compare`, `dump`, `appcompat`, `compare-release`, `deps`
**Flags tested:** `--dwarf-only`, `-H/--header`, `--new-header`, `--format`
(markdown/json/sarif/html), `--stat`, `--show-only`, `--report-mode leaf`,
`--suppress`, `--policy`, `--show-impact`, `--version`, `--check-against`,
`--list-required-symbols`

## Priority Ranking

| # | Bug | Severity | Impact |
|---|-----|----------|--------|
| 1 | Stripped func removal = COMPATIBLE | HIGH | CI/CD false negative |
| 11 | appcompat+headers = 0 relevant | HIGH | Incorrect app analysis |
| 2 | Header sig changes = remove+add | HIGH | Wrong change classification |
| 3 | Duplicate enum changes | MEDIUM | Inflated counts |
| 4 | Duplicate struct offset changes | MEDIUM | Inflated counts |
| 5 | JSON no per-change severity | MEDIUM | JSON consumers broken |
| 6 | Leaf mode JSON wrong keys | MEDIUM | Schema inconsistency |
| 7 | C++ DWARF dump 0 functions | MEDIUM | Reduced C++ analysis |
| 8 | compare-release false no-DWARF | MEDIUM | Misleading diagnostic |
| 9 | Compiler internal types = breaking | LOW | False positives |
| 10 | Excessive duplicate warnings | LOW | Noisy output |
| 12 | --show-only source exit code | LOW | Inconsistent exit codes |
