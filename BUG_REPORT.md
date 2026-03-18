# Bug Report: abicheck Real-World Testing Findings

**Date:** 2026-03-18
**Version:** 0.2.0
**Platform:** Linux x86_64, GCC 13.3.0, castxml 0.6.3
**Tester:** Automated testing via Claude Code

## Summary

Systematic testing of `abicheck` with real compiled C and C++ shared libraries
uncovered **12 issues** across core comparison logic, output formatting, edge
case handling, and CLI behavior. After code-level team review, **7 confirmed
bugs**, **3 design discussions/enhancement requests**, and **2 invalidated**
findings remain.

---

## Team Review Legend

Each bug now includes a **Review Verdict**:
- **CONFIRMED BUG** — Code-level analysis confirms incorrect behavior
- **DESIGN DISCUSSION** — Behavior is intentional but consequences may warrant changes
- **ENHANCEMENT REQUEST** — Not a bug; improvement to consider
- **INVALIDATED** — Original finding was incorrect or based on tester error

---

## Bug 1: Stripped binary function removal misclassified as COMPATIBLE

**Original Severity:** HIGH — CI/CD false negative
**Review Verdict:** DESIGN DISCUSSION

**Command:**
```bash
abicheck compare libtest_v1_stripped.so libtest_v2_stripped.so
```

**Expected:** `process_array` removal is a breaking ABI change (exit code 4).
**Actual:** Verdict is `COMPATIBLE` (exit code 0). The removal is reported as
`func_removed_elf_only` and listed under "Compatible Additions".

### Team Review

This is **intentional behavior**, documented in ADR-011
(`docs/development/adr/011-change-classification-taxonomy.md`). The rationale:

- **`checker_policy.py:28`** defines `FUNC_REMOVED_ELF_ONLY` with comment:
  "ELF-only symbol removed (visibility cleanup, not hard break)"
- **`checker_policy.py:361-362`** classifies it as COMPATIBLE:
  "ELF-only removed: symbol was never declared in headers, may be visibility cleanup"
- **`checker_policy.py:551`** impact text: "Symbol removed from ELF but was not
  in public headers; low risk unless dlsym() callers depend on it."

The design intent: without headers, the tool can't confirm the symbol was
part of the public API surface. Many ELF-exported symbols are internal
implementation details that get cleaned up between versions.

**However**, this creates a real risk for stripped production binaries where
headers are genuinely unavailable. The tool silently classifies **all** symbol
removals as compatible in stripped mode, including genuine public API removals.

**Recommendation:** Consider adding `--strict-elf-only` flag or making the
`strict_abi` policy treat `func_removed_elf_only` as BREAKING. The ADR itself
notes ABICC and libabigail both classify this as BREAKING.

---

## Bug 2: Header-based analysis reports C function signature changes as removal + addition

**Original Severity:** HIGH — Incorrect change classification
**Review Verdict:** CONFIRMED BUG

**Command:**
```bash
abicheck compare libv1.so libv2.so -H v1.h --new-header v2.h --format json
```

### Root Cause (code-level)

**`dumper.py:293-295`** — When `--lang` is not explicitly set to `c`, the
aggregate header is compiled with `.hpp` extension (C++ mode):
```python
force_c = lang and lang.upper() == "C"
agg_ext = ".h" if force_c else ".hpp"
```

This causes castxml to apply C++ name mangling to C functions:
- `add(int, int)` becomes `_Z3addii`
- `add(int, int, int)` becomes `_Z3addiii`

**`checker.py:329-372`** — Function matching in `_diff_functions()` uses the
mangled name as dictionary key. Since `_Z3addii` != `_Z3addiii`, the checker
reports the old as FUNC_REMOVED and new as FUNC_ADDED instead of detecting
FUNC_PARAMS_CHANGED.

**`dumper.py:525-530`** — Extern "C" detection exists but only works when
castxml omits the mangled attribute (C mode):
```python
raw_mangled = el.get("mangled", "")
is_extern_c = (el.get("extern") == "1" or not raw_mangled)
```

In C++ mode, castxml always provides mangled names, so `is_extern_c` is
False for C functions.

**Workaround:** Users can pass `--lang c` to force C compilation mode.
**Fix needed:** Auto-detect C linkage and use plain names for matching,
or default to `--lang c` when headers have `.h` extension only.

---

## Bug 3: Duplicate enum changes in DWARF-only mode

**Original Severity:** MEDIUM — Inflated change counts
**Review Verdict:** CONFIRMED BUG

**Command:**
```bash
abicheck compare libv1.so libv2.so --dwarf-only --format json
```

### Root Cause (code-level)

Two independent detectors both fire for enum changes:

1. **`checker.py:643` (`_diff_enums()`)** — AST-based enum detection:
   Description: `"Enum member value changed: Color::GREEN"`

2. **`checker.py:2813` (`_diff_enum_layouts()`)** — DWARF-based enum detection:
   Description: `"Enum member value changed: Color::GREEN (1 → 2)"`

Deduplication logic exists at **`checker.py:2155-2192`** (`_deduplicate_ast_dwarf()`)
with a mapping in `_DWARF_TO_AST_EQUIV`. However, the dedup uses **description
matching** at line 2180 (`(kind, description)` tuple), and since the two
detectors produce different description strings for the same change, the dedup
fails to recognize them as duplicates.

**Impact:** Each enum value change is counted as 2 breaking changes. The
suppression note in our test showed 6 suppressions for 2 actual enum changes.

**Fix needed:** Deduplicate by `(kind, symbol)` tuple instead of or in
addition to `(kind, description)`.

---

## Bug 4: Duplicate struct field offset changes from different evidence tiers

**Original Severity:** MEDIUM — Redundant output, inflated counts
**Review Verdict:** DESIGN DISCUSSION

**Command:**
```bash
abicheck compare libv1.so libv2.so --dwarf-only --format markdown
```

### Team Review

This is **partially intentional**. The two change kinds represent different
evidence tiers:

- `type_field_offset_changed` (bits) — from DWARF type info (AST-level)
- `struct_field_offset_changed` (bytes) — from DWARF layout (binary-level)

**`checker_policy.py`** classifies both as BREAKING with different
severity rationale:
- Line 294/567: "Old code reads/writes fields at stale offsets"
- Line 322/623: "Field moved to different offset; old code accesses wrong memory"

Deduplication mapping exists at **`checker.py:1814-1820`**:
```python
ChangeKind.STRUCT_FIELD_OFFSET_CHANGED: {ChangeKind.TYPE_FIELD_OFFSET_CHANGED},
```

However, the dedup only triggers when there is **BOTH** an AST finding AND
a DWARF finding for the **same symbol**. In DWARF-only mode, both findings
come from DWARF (different DWARF analysis layers), and the symbols differ:
- `type_field_offset_changed` symbol: `"Point"` (root type)
- `struct_field_offset_changed` symbol: `"Point::x"` (field-qualified)

Since symbols differ, the dedup doesn't match them.

**Recommendation:** Extend dedup to match cross-tier findings even when
symbol formats differ (e.g., "Point::x" should match changes on "Point" that
reference field "x").

---

## Bug 5: JSON output lacks per-change severity/verdict

**Original Severity:** MEDIUM
**Review Verdict:** ENHANCEMENT REQUEST

### Team Review

This is **intentional design**, documented in ADR-014
(`docs/development/adr/014-output-format-strategy.md`). The rationale:

- Severity is **policy-dependent** — the same `kind` can be BREAKING under
  `strict_abi` but COMPATIBLE under `sdk_vendor`
- **`reporter.py:505-535`** (`_change_to_dict()`) deliberately omits severity
  to keep the change representation policy-neutral
- The `impact` field provides human-readable context instead
- `docs/development/report-comparison.md` explicitly notes: "severity is
  implicit via kind (BREAKING/API_BREAK/COMPATIBLE)"

**However**, this forces JSON consumers to replicate the policy logic from
`checker_policy.py`, which is a real usability gap. The markdown format
separates changes into severity sections, but this information is lost in JSON.

**Recommendation:** Add an optional `"severity"` field that reflects the
active policy (since the policy IS known at report time). This doesn't
violate the policy-neutral design — it just materializes the result.

---

## Bug 6: `--report-mode leaf` JSON uses different keys than standard mode

**Original Severity:** MEDIUM — JSON schema inconsistency
**Review Verdict:** ENHANCEMENT REQUEST

### Team Review

This is **intentional and documented**. The leaf mode fundamentally changes
the output structure for root-cause analysis:

- **`reporter.py:374-416`** (`_to_json_leaf()`) outputs `leaf_changes` and
  `non_type_changes` instead of `changes`
- **`docs/user-guide/output-formats.md:76-79`** documents this structure
- **`tests/test_report_filtering.py:353-368`** tests this behavior

The `changes` key being empty (`[]`) rather than absent is the only real
issue — it could mislead naive consumers.

**Recommendation:** Either remove the empty `changes` key in leaf mode
(so consumers get KeyError and know to look elsewhere) or populate `changes`
with the union of `leaf_changes` + `non_type_changes` for backwards
compatibility.

---

## Bug 7: C++ DWARF-only dump extracts 0 functions

**Original Severity:** MEDIUM — Reduced C++ analysis quality
**Review Verdict:** CONFIRMED BUG

**Command:**
```bash
abicheck dump libcpptest.so --dwarf-only  # → "functions": []
abicheck dump libtest.so --dwarf-only     # → "functions": [9 items]
```

### Root Cause (code-level)

**`dwarf_snapshot.py:373-375`** — The critical filter:
```python
if not self._is_exported(mangled, name):
    return  # Function rejected
```

**`dwarf_snapshot.py:757-763`** — `_is_exported()` checks:
```python
def _is_exported(self, mangled: str, name: str) -> bool:
    if mangled and mangled in self._exported_names:
        return True
    if name and name in self._exported_names:
        return True
    return False
```

**`dwarf_snapshot.py:259-263`** — `_exported_names` is built from ELF:
```python
for sym in elf_meta.symbols:
    if sym.name and sym.visibility not in _HIDDEN_VIS:
        self._exported_names.add(sym.name)
```

**The asymmetry:**
- **C functions:** ELF stores `"add"`, DWARF DW_AT_name = `"add"` →
  `_is_exported("add", "add")` = True
- **C++ functions:** ELF stores `"_ZN6Widget8getValueEv"`, DWARF
  DW_AT_linkage_name = `"_ZNK6Widget8getValueEv"` (may differ due to const
  qualification), DW_AT_name = `"getValue"`. If the exact mangled string
  doesn't match (e.g., const vs non-const), and `"getValue"` is not in
  ELF exports (it isn't — ELF uses mangled names), the function is rejected.

**Fix needed:** Normalize mangled name comparison or build a demangled name
index from ELF exports for fallback matching.

---

## Bug 8: `compare-release` falsely reports "no DWARF" for C++ libraries

**Original Severity:** MEDIUM — Misleading diagnostic
**Review Verdict:** CONFIRMED BUG (consequence of Bug 7)

When 0 functions are extracted from C++ DWARF (Bug 7), the dumper falls
through to the "no DWARF" warning path. `readelf --debug-dump=info` confirms
DWARF sections are present with full type information.

**Fix:** Will be resolved when Bug 7 is fixed.

---

## Bug 9: Compiler internal types reported as breaking ABI changes

**Original Severity:** LOW — False positives
**Review Verdict:** CONFIRMED BUG (in DWARF path)

### Team Review

Filtering EXISTS for the castxml/header path:
- **`dumper.py:610-621`** — `_is_public_record_type()` rejects types starting
  with `__` (line 616) and built-in pseudo-file origins (line 619)

However, DWARF-extracted types **bypass this filter**. The DWARF path
(`dwarf_snapshot.py`) independently extracts types and does not apply the
same `__` prefix filtering. Result: `__va_list_tag`, `__builtin_va_list`,
`__gnuc_va_list` are included in DWARF snapshots and reported as ABI changes.

**Fix needed:** Apply the `__` prefix filter to DWARF-extracted types as
well, or add these specific types to a blocklist.

---

## Bug 10: Excessive "Duplicate mangled symbol" warnings with headers

**Original Severity:** LOW — Noisy output
**Review Verdict:** CONFIRMED BUG (cosmetic)

### Root Cause (code-level)

**`model.py:188-199`** — The `index()` method warns on duplicate mangled names:
```python
for f in self.functions:
    if f.mangled in func_map:
        _model_log.warning("Duplicate mangled symbol skipped...")
```

With castxml headers, struct/union types generate multiple entries (from
forward declarations, typedef aliases, and the definition itself). Each
triggers a separate warning. A self-compare with 2 structs produces
12 warnings (3 duplicates x 2 structs x 2 sides).

**Fix needed:** Deduplicate before indexing, or suppress warnings for
known-benign duplicates from castxml.

---

## Bug 11: `appcompat` with headers shows 0 relevant changes

**Original Severity:** HIGH — Incorrect appcompat output
**Review Verdict:** CONFIRMED BUG (consequence of Bug 2)

### Root Cause (code-level)

**`appcompat.py:399-426`** (`_is_relevant_to_app()`):
```python
if change.symbol in app.undefined_symbols:
    return True
```

- `change.symbol` with headers = C++ mangled name (e.g., `"_Z3addii"`)
- `app.undefined_symbols` from ELF = C linkage name (e.g., `"add"`)
- No match → all changes marked irrelevant

Without headers, `change.symbol` = plain name (e.g., `"add"`) →
correctly matches the app's ELF imports.

**Fix:** Will be resolved when Bug 2 is fixed (C functions should use
plain names regardless of header parsing mode).

---

## Bug 12: `--show-only source` changes exit code

**Original Severity:** LOW
**Review Verdict:** INVALIDATED

### Team Review

The original finding used `--show-only source`, which is **not a valid token**.
Valid tokens are: `breaking`, `api-break`, `risk`, `compatible`, `functions`,
`variables`, `types`, `enums`, `elf`, `added`, `removed`, `changed`.

Retesting with valid tokens shows exit codes are **consistent**:
```
--show-only breaking:    exit 4 (correct)
--show-only api-break:   exit 4 (correct)
--show-only compatible:  exit 4 (correct)
no filter:               exit 4 (correct)
```

The `cli.py:965` documentation confirms: "Does not affect exit codes."
The code at `cli.py:1117-1120` computes exit code from the full verdict,
not the filtered set.

**Minor issue found:** `--show-only source` (invalid token) exits with
code 0 instead of non-zero. Click error handling doesn't propagate the
exit code correctly.

---

## Revised Priority Ranking

| # | Bug | Review Verdict | Severity | Root Cause Location |
|---|-----|---------------|----------|-------------------|
| 2 | Header C++ mangling for C functions | **CONFIRMED BUG** | HIGH | `dumper.py:293-295`, `checker.py:329` |
| 11 | appcompat+headers = 0 relevant | **CONFIRMED BUG** | HIGH | `appcompat.py:399` (consequence of #2) |
| 7 | C++ DWARF dump 0 functions | **CONFIRMED BUG** | MEDIUM | `dwarf_snapshot.py:373, 757-763` |
| 3 | Duplicate enum changes | **CONFIRMED BUG** | MEDIUM | `checker.py:643, 2813` (dedup by description fails) |
| 8 | compare-release false no-DWARF | **CONFIRMED BUG** | MEDIUM | consequence of #7 |
| 9 | Compiler internals in DWARF path | **CONFIRMED BUG** | LOW | DWARF path skips `__` prefix filter |
| 10 | Excessive duplicate warnings | **CONFIRMED BUG** | LOW | `model.py:188-199` |
| 1 | Stripped func removal = COMPATIBLE | **DESIGN DISCUSSION** | — | `checker_policy.py:28, 361` (intentional) |
| 4 | Duplicate struct offsets (2 tiers) | **DESIGN DISCUSSION** | — | Dedup symbol mismatch in DWARF-only |
| 5 | JSON no per-change severity | **ENHANCEMENT** | — | `reporter.py:505` (intentional per ADR-014) |
| 6 | Leaf mode JSON different keys | **ENHANCEMENT** | — | `reporter.py:374` (intentional, documented) |
| 12 | --show-only source exit code | **INVALIDATED** | — | Tester used invalid token |

### Summary

- **7 confirmed bugs** (2 HIGH, 3 MEDIUM, 2 LOW)
- **2 design discussions** worth considering
- **2 enhancement requests** for improved DX
- **1 invalidated** finding

The most impactful cluster is **Bug 2 + Bug 11**: header-based C function
analysis uses C++ mangling, breaking both the change detection and
appcompat symbol matching. This affects any C library analyzed with
`-H` without explicit `--lang c`.

The second cluster is **Bug 7 + Bug 8**: C++ DWARF function extraction
fails due to mangled name matching asymmetry in `_is_exported()`,
degrading C++ analysis in `compare-release` and `--dwarf-only` modes.

---

## Test Environment

**Libraries built:**
- `libtest_v1.so` / `libtest_v2.so` — C library with 8+ intentional ABI breaks
- `libcpptest_v1.so` / `libcpptest_v2.so` — C++ library with vtable, layout, size changes
- `libtest_v1_stripped.so` / `libtest_v2_stripped.so` — Stripped (no debug info)
- `libempty.so` — Empty library (no symbols)
- `app` / `cppapp` — Consumer applications linked against v1

**ABI changes introduced in v2:**
- Struct field reordering (Point: x<->y)
- Struct size increase (Point: +z field, Record: name 32->64, id int->long)
- Enum value reassignment (GREEN: 1->2, BLUE: 2->1)
- Function parameter addition (add: 2->3 params)
- Pass-by-value to pointer (compute)
- Function removal (process_array)
- Variadic->non-variadic (log_message)
- Callback signature change (callback_t)
- New function addition (multiply)

**Commands tested:** `compare`, `dump`, `appcompat`, `compare-release`, `deps`
**Flags tested:** `--dwarf-only`, `-H/--header`, `--new-header`, `--format`
(markdown/json/sarif/html), `--stat`, `--show-only`, `--report-mode leaf`,
`--suppress`, `--policy`, `--show-impact`, `--version`, `--check-against`,
`--list-required-symbols`
