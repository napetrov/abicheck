# ABICC Report Format Compliance Analysis

This document analyzes how well `abicheck compat` mode reports comply with
the output formats produced by `abi-compliance-checker` (ABICC), and whether
existing parsing harnesses (abi-tracker, lvc-monitor, CI integrations, distro
infrastructure) would continue to work with abicheck's output.

## Executive Summary

| Dimension | Status | Risk |
|-----------|--------|------|
| Exit codes (0/1/2) | **Full parity** | None |
| XML descriptor input | **Full parity** | None |
| CLI flag acceptance | **Full parity** (40+ flags) | None |
| XML report output (`-report-format xml`) | **Implemented** (ABICC schema) | Low |
| `htm` format alias | **Implemented** | None |
| Default report filename | **Fixed** (`compat_report.*`) | None |
| Console BC% output | **Implemented** (ABICC format) | None |
| HTML report — visual appearance | Similar but NOT identical | Medium |
| HTML report — machine parsability | Different DOM structure | **HIGH** |
| Perl dump format input | NOT supported (by design) | Medium |
| ABICC exit codes 3-11 | NOT implemented | Low |

### What Was Fixed

1. **XML report output** — New `xml_report.py` produces ABICC-compatible XML
   with the real schema: `<reports><report kind="binary|source">` containing
   `<test_info>`, `<test_results>`, `<problem_summary>`, severity-tiered
   `<problems_with_types>` / `<problems_with_symbols>`, and detail sections.

2. **`htm` format alias** — `-report-format htm` is now accepted as an alias
   for `html`, matching ABICC convention.

3. **Default report filename** — Changed from `report.html` to
   `compat_report.html` to match ABICC convention.

4. **Console BC% output** — Now prints ABICC-format lines:
   `Binary compatibility: XX.X%` and
   `Total binary compatibility problems: N, warnings: 0`

### Remaining Gaps

1. **HTML report DOM structure** — ABICC's HTML uses specific element IDs
   (`#Title`, `#Summary`, `#Added`, `#Removed`, `#TypeProblems_High`, etc.)
   that scrapers depend on. Our HTML uses different structure.

2. **ABICC extended exit codes** — ABICC defines codes 3-11 for specific
   errors (not found, access error, compile error, etc.). We use 2 for all
   errors.

---

## Detailed Analysis

### 1. Exit Codes (FULL PARITY for 0/1/2)

| Code | ABICC Meaning | abicheck Meaning | Match |
|------|---------------|-------------------|:-----:|
| 0 | Compatible / no change | Compatible / no change | YES |
| 1 | Incompatible (breaking) | Breaking ABI change | YES |
| 2 | Source-level break or error | Source-level break or error | YES |
| 3 | System command not found | (uses exit 2) | NO |
| 4 | Cannot access input files | (uses exit 2) | NO |
| 5 | Cannot compile headers | (uses exit 2) | NO |
| 6-11 | Various specific errors | (uses exit 2) | NO |

The primary verdict codes (0/1/2) match. ABICC's extended codes (3-11) are
all mapped to exit 2 in abicheck, which is acceptable for most CI pipelines
that only check for 0 vs non-zero.

The `-strict` promotion (SOURCE_BREAK → exit 1) also matches.

### 2. XML Descriptor Input Format (FULL PARITY)

Both tools accept the same XML descriptor format:
```xml
<version>2025.0</version>
<headers>/path/to/include/</headers>
<libs>/path/to/libfoo.so</libs>
```

abicheck correctly supports:
- Multiple `<headers>` and `<libs>` elements
- `{RELPATH}` macro substitution
- XXE-safe parsing (improvement over ABICC)

### 3. CLI Flag Acceptance (FULL PARITY)

All 40+ ABICC CLI flags are accepted. Functional flags work identically.
Stub flags are accepted with warnings. See `docs/abicc_compat.md` for the
complete flag reference.

### 4. XML Report Output (IMPLEMENTED)

abicheck now produces XML reports via `-report-format xml` that match the
real ABICC XML schema. No formal DTD/XSD exists for ABICC's XML — the
format is defined implicitly by the ABICC Perl source code.

**Real ABICC XML structure** (verified from source):

```xml
<?xml version="1.0" encoding="utf-8"?>
<reports>
  <report kind="binary" version="1.2">
    <test_info>
      <library>LIBNAME</library>
      <version1><number>V1</number><arch>x86_64</arch></version1>
      <version2><number>V2</number><arch>x86_64</arch></version2>
    </test_info>
    <test_results>
      <verdict>compatible|incompatible</verdict>
      <affected>N.N</affected>
      <symbols>N</symbols>
    </test_results>
    <problem_summary>
      <added_symbols>N</added_symbols>
      <removed_symbols>N</removed_symbols>
      <problems_with_types>
        <high>N</high><medium>N</medium><low>N</low><safe>N</safe>
      </problems_with_types>
      <problems_with_symbols>
        <high>N</high><medium>N</medium><low>N</low><safe>N</safe>
      </problems_with_symbols>
    </problem_summary>
    <added_symbols><name>sym1</name>...</added_symbols>
    <removed_symbols><name>sym1</name>...</removed_symbols>
    <problems_with_types severity="High">
      <type name="TypeName">
        <problem id="Size_Of_Type">
          <change old_value="8" new_value="16">Description</change>
        </problem>
      </type>
    </problems_with_types>
    <problems_with_symbols severity="Medium">
      <symbol name="_Z3foov">
        <problem id="Parameter_Type">
          <change old_value="int" new_value="long">Description</change>
        </problem>
      </symbol>
    </problems_with_symbols>
  </report>
  <report kind="source" version="1.2">
    <!-- same structure, excludes binary-only changes -->
  </report>
</reports>
```

**abicheck implementation coverage:**

| ABICC XML Element | abicheck | Notes |
|-------------------|:--------:|-------|
| `<reports>` wrapper | YES | |
| `<report kind="binary\|source">` | YES | |
| `<test_info>` | YES | Missing `<arch>`, `<gcc>` sub-elements |
| `<test_results>` | YES | `<verdict>`, `<affected>`, `<symbols>` |
| `<problem_summary>` | YES | Full severity tiers (high/medium/low/safe) |
| `<added_symbols>` detail | YES | Flat `<name>` list (ABICC nests by header/library) |
| `<removed_symbols>` detail | YES | Flat `<name>` list |
| `<problems_with_types severity="">` | YES | `<type>/<problem>/<change>` hierarchy |
| `<problems_with_symbols severity="">` | YES | `<symbol>/<problem>/<change>` hierarchy |
| `<effect>`, `<overcome>` in problems | NO | ABICC includes remediation hints |
| `<affected>` in type problems | NO | Per-type affected symbol list |
| `<header>/<library>` nesting | NO | ABICC groups by header file, then library |
| `<problems_with_constants>` | NO | Constant checking not yet implemented |

**Key consumers and compatibility:**

| Consumer | Parses | Status |
|----------|--------|--------|
| abi-tracker | `<report>`, `<test_results>`, `<problem_summary>` | **Compatible** |
| lvc-monitor | Same as abi-tracker | **Compatible** |
| Fedora dist.abicheck | Primarily exit codes | **Compatible** |
| openSUSE OBS | XML problem_summary | **Compatible** |
| Custom HTML scrapers | HTML DOM | **NOT compatible** (see section 5) |

### 5. HTML Report Structure (PARTIAL — MEDIUM RISK)

**ABICC HTML structure** (key sections):

```
<title>Binary compatibility report for LIBNAME between V1 and V2</title>
<div id='Title'><h1>Binary compatibility report...</h1></div>
<div id='Summary'>
  <h2>Test Info</h2> <table class='summary'>...</table>
  <h2>Test Results</h2> <table>... BC % ...</table>
  <h2>Binary Compatibility: <span>XX.X%</span></h2>
</div>
<div id='TypeProblems_High'>...</div>
<div id='TypeProblems_Medium'>...</div>
<div id='InterfaceProblems_High'>...</div>
<div id='Added'>...</div>
<div id='Removed'>...</div>
```

ABICC also embeds machine-readable metadata in an HTML comment:
```
verdict:incompatible;kind:binary;affected:2.5;added:5;removed:2;
type_problems_high:3;...
```

**abicheck HTML structure** (current):

```
<div class="header"><h1>ABI Compatibility Report — LIBNAME</h1></div>
<div class="verdict-box">...</div>
<div class="summary-section">...</div>
<div class="section section-removed" id="removed">...</div>
<div class="section section-changed" id="changed">...</div>
<div class="section section-added" id="added">...</div>
```

**Key divergences:**

| Feature | ABICC | abicheck |
|---------|-------|----------|
| Element IDs | `#Title`, `#Summary`, `#Added`, `#Removed` | `.header`, `.summary-section`, `#added`, `#removed` |
| Title format | `Binary compatibility report for LIBNAME between V1 and V2` | `ABI Report: LIBNAME V1 → V2` |
| Severity tiers | High/Medium/Low (separate sections) | Flat (all in "Changed") |
| BC% location | `<h2>Binary Compatibility: <span>XX.X%</span></h2>` | `<div class="bc-metric">` |
| CSS approach | Inline styles | Class-based |
| META_DATA comment | Present | Absent |

**Recommendation:** Wire the `-old-style` flag to generate ABICC-compatible
HTML with matching element IDs and section structure.

### 6. Console Output Format (IMPLEMENTED)

abicheck now prints ABICC-compatible console output:
```
Binary compatibility: 97.5%
Total binary compatibility problems: 3, warnings: 0
Verdict: BREAKING
Report:  compat_reports/libfoo/v1_to_v2/compat_report.html
```

The first two lines match ABICC's stderr format. The Verdict and Report
lines are abicheck additions.

### 7. Default Report Paths (FIXED)

ABICC default: `compat_reports/LIBNAME/V1_to_V2/compat_report.html`
abicheck default: `compat_reports/LIBNAME/V1_to_V2/compat_report.html`

Now matches. Previously was `report.html`.

### 8. Dump Format (BY DESIGN — MEDIUM RISK)

abicheck uses JSON dumps; ABICC uses Perl `Data::Dumper` or XML dumps.
abicheck correctly detects and rejects ABICC dump formats with clear
migration guidance. This is a deliberate design choice, not a bug.

### 9. ABICC Severity Mapping

ABICC classifies all problems into severity tiers. abicheck now implements
this mapping for the XML report:

| Severity | Change Kinds |
|----------|-------------|
| **High** | func_removed, type_size_changed, type_vtable_changed, type_base_changed, struct_size_changed, func_virtual_removed, func_deleted, base_class_position_changed, type_kind_changed |
| **Medium** | func_return_changed, func_params_changed, type_field_offset_changed, type_field_type_changed, type_field_removed, var_type_changed, calling_convention_changed, soname_changed, symbol_type_changed, typedef_base_changed, union_field_removed |
| **Low** | enum_member_value_changed, field_bitfield_changed, func_visibility_changed, func_noexcept_changed, enum_underlying_size_changed, symbol_binding_changed, all other breaking kinds |

---

## Remaining Remediation Plan

### P1 — High (improves HTML parser compatibility)

1. **Wire `-old-style` flag** to generate ABICC-compatible HTML:
   - Match element IDs (`#Title`, `#Summary`, `#Added`, `#Removed`)
   - Match title format
   - Separate type problems by severity (High/Medium/Low sections)
   - Embed META_DATA comment for machine parsing

### P2 — Medium

2. **Add `<arch>` and `<gcc>` to XML `<test_info>`** from snapshot metadata
3. **Add `<header>/<library>` grouping** in XML detail sections
4. **Add `<effect>` and `<overcome>` elements** to XML problem details
5. **Implement `<problems_with_constants>`** section

### P3 — Low

6. Map ABICC exit codes 3-11 to specific error conditions
7. Remove emoji from HTML reports for terminal compatibility
8. Add embedded META_DATA comment to HTML reports

---

## Test Coverage

| Area | Tests | Status |
|------|-------|--------|
| XML report schema structure | 8 tests | PASS |
| XML report counts/verdicts | 6 tests | PASS |
| XML report detail sections | 5 tests | PASS |
| XML report parsability (abi-tracker sim) | 3 tests | PASS |
| write_xml_report file I/O | 2 tests | PASS |
| `-report-format` choices (htm, xml, html) | 3 tests | PASS |
| Default filename (`compat_report.*`) | 1 test | PASS |
| Console output format | 2 tests | PASS |
| HTML report (existing) | 69 tests | PASS |
| Compat flags (existing) | 27 tests | PASS |
| Total | **~126 tests** | **ALL PASS** |

---

## Conclusion

With the XML report implementation, `abicheck compat` now produces output
that is parseable by the major ABICC report consumers: **abi-tracker**,
**lvc-monitor**, **Fedora dist.abicheck**, and **openSUSE OBS**. The XML
schema matches ABICC's structure with `<reports>/<report kind>/<test_info>/
<test_results>/<problem_summary>` hierarchy and severity-tiered problem
detail sections.

**Safe for drop-in replacement when:**
- CI pipelines check exit codes only → YES (since v1)
- Infrastructure parses XML reports → YES (now implemented)
- Harnesses scrape HTML DOM → NO (HTML IDs differ, needs `-old-style`)
