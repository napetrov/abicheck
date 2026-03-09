# ABICC Report Format Compliance Analysis

This document analyzes how well `abicheck compat` mode reports comply with
the output formats produced by `abi-compliance-checker` (ABICC), and whether
existing parsing harnesses (abi-tracker, lvc-monitor, CI integrations, distro
infrastructure) would continue to work with abicheck's output.

## Executive Summary

| Dimension | Status | Risk |
|-----------|--------|------|
| Exit codes | **Full parity** | None |
| XML descriptor input | **Full parity** | None |
| CLI flag acceptance | **Full parity** (40+ flags) | None |
| HTML report — visual appearance | **Similar but NOT identical** | Medium |
| HTML report — machine parsability | **NOT compatible** | **HIGH** |
| XML report output (`-report-format xml`) | **NOT supported** | **HIGH** |
| Perl dump format input | **NOT supported** (by design) | Medium |
| Console output format | **Different** | Low |
| Default report paths | **Different** | Medium |

### Critical Gaps

1. **No XML report output** — ABICC supports `-report-format xml` producing a
   structured XML report. abicheck only supports `html`, `json`, `md`. The
   `abi-tracker` and `lvc-monitor` tools parse ABICC's XML reports to extract
   compatibility percentages, problem counts, and affected symbols. **This is
   the single largest compatibility gap.**

2. **HTML report structure diverges from ABICC** — ABICC's HTML has a specific
   DOM structure that some harnesses scrape. abicheck's HTML is visually
   inspired by ABICC but uses entirely different CSS class names, element IDs,
   section structure, and table layouts.

3. **No `-report-format htm` alias** — ABICC uses `htm` not `html` for the
   format name. Scripts passing `-report-format htm` will fail.

---

## Detailed Analysis

### 1. Exit Codes (FULL PARITY)

| Code | ABICC Meaning | abicheck Meaning | Match |
|------|---------------|-------------------|:-----:|
| 0 | Compatible / no change | Compatible / no change | YES |
| 1 | Incompatible (breaking) | Breaking ABI change | YES |
| 2 | Source-level break or error | Source-level break or error | YES |

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

### 4. XML Report Output (NOT SUPPORTED — HIGH RISK)

**ABICC** produces XML reports via `-report-format xml` with this structure:

```xml
<?xml version="1.0" encoding="utf-8"?>
<report version="1.2"
        library="libfoo"
        version1="1.0"
        version2="2.0">
  <binary>
    <compatible>97.5</compatible>
    <removed>2</removed>
    <added>5</added>
    <problems_with_types>3</problems_with_types>
    <problems_with_symbols>1</problems_with_symbols>
    <problems_total>4</problems_total>
    <warnings>0</warnings>
    <affected>15</affected>
  </binary>
  <source>
    <compatible>95.0</compatible>
    ...
  </source>
  <problem_summary>
    <headers>...</headers>
    <libs>...</libs>
  </problem_summary>
</report>
```

**Key consumers that parse this XML:**
- **abi-tracker** (`upstream-tracker/modules/ABIReport.pm`) — extracts
  `<binary><compatible>` percentage and `<problems_total>` count
- **lvc-monitor** — same XML parsing for continuous monitoring
- **Fedora ABI tracking** — scripts parse XML for automated gating
- **openSUSE OBS** — integration parses XML reports

**abicheck gap:** The `-xml` flag is accepted as a stub with a warning but
does not produce XML output. The `-report-format` option only supports
`html`, `json`, `md`. Any harness expecting ABICC XML output will break.

**Recommendation:** Implement `to_xml()` in `reporter.py` that produces the
ABICC XML schema. The schema is simple (~30 elements) and maps directly to
data already available in `DiffResult`.

### 5. HTML Report Structure (PARTIAL — MEDIUM RISK)

**ABICC HTML structure** (key sections parseable by harnesses):

```
<title>Binary compatibility report for LIBNAME between VERSION1 and VERSION2</title>

<div id='Title'>
  <h1>Binary compatibility report for the <span style='...'>LIBNAME</span> library ...</h1>
</div>

<div id='Summary'>
  <h2>Test Info</h2>
  <table> ... library name, version1, version2, headers, libs ... </table>
  <h2>Test Results</h2>
  <table>
    <tr><td>Total binary compatibility problems</td><td>N (High: X, Medium: Y, Low: Z)</td></tr>
    <tr><td>Added symbols</td><td>N</td></tr>
    <tr><td>Removed symbols</td><td>N</td></tr>
  </table>
  <h2>Binary Compatibility: <span>XX.X%</span></h2>
</div>

<div id='TypeProblems_High'>...</div>
<div id='TypeProblems_Medium'>...</div>
<div id='TypeProblems_Low'>...</div>
<div id='InterfaceProblems_High'>...</div>
<div id='InterfaceProblems_Medium'>...</div>
<div id='InterfaceProblems_Low'>...</div>
<div id='Added'>...</div>
<div id='Removed'>...</div>
```

**abicheck HTML structure** (current):

```
<div class="header"><h1>ABI Compatibility Report — LIBNAME</h1></div>
<div class="verdict-box">...</div>
<div class="nav">...</div>
<div class="summary-section">...</div>
<div class="section section-removed" id="removed">...</div>
<div class="section section-changed" id="changed">...</div>
<div class="section section-added" id="added">...</div>
<div class="section section-suppressed" id="suppressed">...</div>
```

**Specific divergences:**

| Feature | ABICC HTML | abicheck HTML |
|---------|-----------|---------------|
| Title format | `Binary compatibility report for LIBNAME between V1 and V2` | `ABI Report: LIBNAME V1 → V2` |
| Main heading ID | `#Title` | `.header h1` |
| Summary section ID | `#Summary` | `.summary-section` |
| Problem severity levels | High/Medium/Low (3 tiers) | Breaking/Changed/Added (no severity tiers) |
| Type problems section | `#TypeProblems_High`, `_Medium`, `_Low` | No equivalent (merged into "Changed") |
| Interface problems section | `#InterfaceProblems_High`, `_Medium`, `_Low` | No equivalent (merged into "Changed") |
| Added symbols section | `#Added` | `#added` (lowercase) |
| Removed symbols section | `#Removed` | `#removed` (lowercase) |
| BC% display | `<h2>Binary Compatibility: <span>XX.X%</span></h2>` | `<div class="bc-metric">Binary Compatibility: <strong>XX.X%</strong>` |
| Problem details | Per-symbol expandable sections with old/new declarations | Flat table rows |
| CSS | Inline styles (no classes) | Class-based CSS |
| Emojis | None | Uses emoji icons (broken in some terminal renderers) |

**Known HTML scrapers that will break:**
- `abi-tracker` scrapes `<h2>Binary Compatibility: <span>` with regex
- Some CI scripts grep for `Binary compatibility problems.*(\d+)` in HTML
- Fedora bodhi integration parses the `#Summary` table

**Recommendation:** Add an `--abicc-html` mode that generates HTML with
ABICC-compatible element IDs, title format, and section structure. The
current HTML is fine as the default but won't satisfy parsers.

### 6. Console Output Format (LOW RISK)

ABICC console output:
```
Binary compatibility: 97.5%
Total binary compatibility problems: 3, warnings: 0
```

abicheck console output:
```
Verdict: BREAKING
Report:  compat_reports/libfoo/v1_to_v2/report.html
```

Most CI harnesses rely on exit codes, not console text, so this is low risk.
However, some scripts do grep stdout for the compatibility percentage.

### 7. Default Report Paths (MEDIUM RISK)

ABICC default: `compat_reports/LIBNAME/V1_to_V2/compat_report.html`
abicheck default: `compat_reports/LIBNAME/V1_to_V2/report.html`

Note the filename difference: `compat_report.html` vs `report.html`.
Scripts with hardcoded paths will break.

### 8. Dump Format (BY DESIGN — MEDIUM RISK)

abicheck uses JSON dumps; ABICC uses Perl `Data::Dumper` or XML dumps.
abicheck correctly detects and rejects ABICC dump formats with clear
migration guidance. This is a deliberate design choice, not a bug.

### 9. `-report-format` Value Names (LOW RISK)

ABICC uses `htm` and `xml` as format names.
abicheck uses `html`, `json`, `md`.

The `htm` alias is not recognized — scripts passing `-report-format htm`
will get an error.

---

## Prioritized Remediation Plan

### P0 — Critical (blocks drop-in replacement claims)

1. **Implement XML report output** (`-report-format xml`)
   - File: new `abicheck/xml_report.py`
   - Must produce ABICC-compatible XML schema with `<binary>`, `<source>`,
     `<compatible>`, `<problems_total>`, etc.
   - Wire into CLI: add `xml` to `-report-format` choices
   - Also make `-xml` stub flag produce XML format instead of just warning

2. **Add `htm` as alias for `html`** in `-report-format` choices
   - One-line fix in `cli.py`

3. **Fix default report filename** to `compat_report.html`
   - One-line fix in `cli.py` line ~1175

### P1 — High (breaks common harnesses)

4. **Add ABICC-compatible HTML mode** (`-old-style` flag)
   - Generate HTML with ABICC element IDs (`#Title`, `#Summary`, `#Added`,
     `#Removed`, `#TypeProblems_High`, etc.)
   - Use ABICC title format
   - Include BC% in ABICC-expected `<h2><span>` format
   - Separate type problems by severity (High/Medium/Low)

5. **Add console BC% output** matching ABICC format:
   `Binary compatibility: XX.X%`

### P2 — Medium (improves compatibility)

6. **Emit ABICC-style problem summary** in HTML with total counts
   matching `Total binary compatibility problems: N (High: X, Medium: Y, Low: Z)`

7. **Map change kinds to ABICC severity tiers** (High/Medium/Low)
   - High: symbol removal, type size change, vtable change
   - Medium: field offset change, return type change
   - Low: enum value change, calling convention

8. **Support ABICC `-dump-format xml`** for dump output (currently JSON only)

### P3 — Low (nice to have)

9. Remove emoji from HTML reports (use text-only labels for terminal compat)
10. Add `-show-retval` filter to actually control return-value display

---

## Test Coverage for Format Compliance

Current test coverage focuses on:
- Verdict correctness (strong)
- Flag acceptance (strong)
- HTML generation validity (strong)
- XSS escaping (strong)

Missing test coverage:
- **XML output format validation** (no XML output exists)
- **HTML DOM structure matching ABICC** (tests validate abicheck's own
  structure, not ABICC compatibility)
- **abi-tracker XML parsing simulation** (should add a test that parses
  output the same way abi-tracker does)
- **Default path matching** (not tested against ABICC defaults)
- **Console output format matching** (not tested)

---

## Conclusion

The `abicheck compat` mode achieves **excellent CLI flag parity** and
**correct exit code semantics**, making it a valid drop-in for CI scripts
that only check exit codes. However, **any harness that parses the report
content** (HTML scraping or XML parsing) will break because:

1. XML report format is entirely missing
2. HTML structure diverges from ABICC in element IDs, section layout, and
   severity classification
3. Default report filenames differ

For organizations that only use `abi-compliance-checker` exit codes in CI
gates, abicheck is a safe drop-in today. For organizations that use
`abi-tracker`, `lvc-monitor`, or custom report parsers, **the XML report
gap is a blocking issue**.
