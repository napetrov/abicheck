# Project Goals -- abicheck

> **Context:** abi-compliance-checker (ABICC) is no longer actively maintained.
> libabigail is maintained by Red Hat but focuses on DWARF-only binary analysis.
> `abicheck` is a modern Python alternative -- drop-in compatible with ABICC first, then better.

---

## Goal 1 -- Drop-In Replacement for ABICC
Support everything ABICC currently does so existing users/pipelines can migrate without changes:
- Same detection coverage (C/C++ ABI breaks: symbols, types, vtables, enums, layout)
- CLI interface compatible with ABICC inputs (XML descriptors, headers+libs)
- JSON/HTML/Markdown reports with equivalent verdict semantics
- Support for suppression files

**Done:** 114 ChangeKinds implemented; suppression files fully supported (YAML + ABICC skip/whitelist formats);
XML report generation for ABICC-compatible output; ABICC compat CLI with all major flags;
auto-forwarding `abicheck compat <flags>` to `compat check`; test parity for ABICC 2.3.

---

## Goal 2 -- Close Known Gaps + Extend
Fix known ABICC / libabigail limitations and add new detection capability:
- Toolchain/flag drift detection (`DW_AT_producer`, `-fshort-enums`, `-fpack-struct`)
- DWARF-aware layout analysis (calling convention, packing, RTTI/visibility boundaries)
- Header/API surface diff (AST-based, macro contracts, inline/template changes)
- Confidence/evidence tiers in output (ELF_ONLY / DWARF_AWARE / HEADER_AWARE)

**Done:** DWARF-aware struct/enum layout; calling convention, packing, toolchain flags detection;
AST-DWARF deduplication; field qualifiers (const/volatile/mutable); enum/parameter rename heuristics;
ELF_ONLY visibility tier used throughout detection; `Confidence` enum (high/medium/low) on
`DiffResult` with `coverage_warnings` for disabled detectors (v0.2.0).
**TODO:** Formalize HEADER_AWARE tier as distinct from DWARF_AWARE in JSON output schema.

---

## Goal 3 -- Pass libabigail Test Suite
Run `abicheck` against libabigail's own regression test cases and reach 100% pass rate:
- Mirror libabigail's `tests/` corpus as integration examples
- Add per-case expected verdicts to CI
- Use as the compatibility regression gate before each release

**Done:** ~54 parity test functions across multiple suites (test_abicc_parity, test_abicc_full_parity,
test_abidiff_parity, test_xml_parity, test_sprint7/10 parity); 13 new ABI compatibility test cases
(cases 42, 49–62); sentinel enum detection; function deletion edge-case hardening (abicc #100).

---

## Goal 4 -- Agent-Friendly Design
Make the tool convenient for AI agents and automation pipelines:
- Structured JSON output (machine-readable, no scraping)
- Clear exit codes:
  - `compare` command: 0 = compatible/no_change, 2 = source break, 4 = breaking ABI change
  - `compat` command: 0 = compatible/no_change, 1 = breaking, 2 = error
- Python API (`from abicheck import compare, dump`) -- not just CLI
- `--format json/markdown` output modes
- Snapshot files for offline/async workflows (`abicheck dump` -> `.abi.json`)

**Done:** JSON output, snapshot format, exit codes (0/2/4), SARIF 2.1.0 output;
MCP server for AI agent integration; GitHub Action (`napetrov/abicheck@v1`) for CI;
report filtering (`--show-only`, `--stat`, `--show-impact`, `--report-mode leaf`)
for CI gate pipelines.

---

## Goal 5 -- Compatibility Break Encyclopedia
For each break type: what it is, how it appears in the real world, and which tool detects it:
- `examples/caseXX_*/` -- minimal compilable C/C++ examples
- Per-case `README.md` with: scenario -> what breaks -> which tools detect -> severity
- Comparison table: `abicheck` vs `abicc` vs `libabigail` vs `nm`-only
- Coverage matrix showing evidence tier required (ELF-only / DWARF / Header / Runtime)

**Done:** 63 example cases (01-62 + 26b) with per-case README.md; gap_report.md with coverage matrix
(abicheck vs ABICC vs libabigail vs nm); abi_breaking_cases_catalog.md in docs;
cross-platform CMake build support for all example cases.

---

## Goal 6 -- Distribution & Documentation
### conda-forge package
Target: distribute via conda-forge — `conda install -c conda-forge abicheck`.
- `castxml` will be declared as a conda run dependency so users get a working install with zero manual setup
- PyPI will remain available (`pip install abicheck`) for users who prefer pip, with
  castxml as a documented external prerequisite
- conda-forge recipe will auto-update on each PyPI release via conda-forge bot

### GitHub Pages documentation site
Public documentation at `https://napetrov.github.io/abicheck/`:
- Getting started / installation
- CLI reference
- ABI break catalog (rendered from `examples/`)
- Tool comparison table
- Architecture overview

**Done:** MkDocs (Material theme) site with full navigation; GitHub Actions auto-deploy to GitHub Pages
on main push; docs include getting_started, CLI reference, case catalog, tool comparison, SARIF guide,
ABICC compat guide, troubleshooting; published to PyPI and conda-forge; Trusted Publishing (OIDC)
for PyPI; publish workflow with dry-run mode.

---

## Status Summary

| Goal | Status |
|------|--------|
| G1: ABICC drop-in | Done — 114 ChangeKinds, compat CLI, suppression files, XML reports |
| G2: Known gaps | DWARF layout, toolchain flags, AST-DWARF dedup, confidence tracking done; HEADER_AWARE tier TODO |
| G3: libabigail tests | Done — ~54 parity test functions + 63 example cases |
| G4: Agent-friendly | Done — JSON, SARIF, exit codes, snapshots, MCP server, GitHub Action |
| G5: Break encyclopedia | Done — 63 example cases with docs + coverage matrix |
| G6: Distribution & docs | Done — PyPI, conda-forge, MkDocs + GitHub Pages |
