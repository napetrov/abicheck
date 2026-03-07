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

**Done:** Sprint 1 closes 13 detection gaps; Sprint 2 adds ELF-only layer; Sprint 5 adds ABICC compat CLI.
**TODO:** Audit ABICC feature list -> gap matrix -> fill remaining items.

---

## Goal 2 -- Close Known Gaps + Extend
Fix known ABICC / libabigail limitations and add new detection capability:
- Toolchain/flag drift detection (`DW_AT_producer`, `-fshort-enums`, `-fpack-struct`)
- DWARF-aware layout analysis (calling convention, packing, RTTI/visibility boundaries)
- Header/API surface diff (AST-based, macro contracts, inline/template changes)
- Confidence/evidence tiers in output (ELF_ONLY / DWARF_AWARE / HEADER_AWARE)

**Done:** Sprint 3 = DWARF-aware struct/enum layout; Sprint 4 = calling convention, packing, toolchain flags.
**TODO:** Header/AST tier, evidence levels in output.

---

## Goal 3 -- Pass libabigail Test Suite
Run `abicheck` against libabigail's own regression test cases and reach 100% pass rate:
- Mirror libabigail's `tests/` corpus as integration examples
- Add per-case expected verdicts to CI
- Use as the compatibility regression gate before each release

**In progress:** Sprint 6 adds initial libabigail parity tests (10 cases).
**TODO:** Expand to full libabigail test corpus.

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

**Partially done:** JSON output, snapshot format. **TODO:** SARIF output, Python API docs.

---

## Goal 5 -- Compatibility Break Encyclopedia
For each break type: what it is, how it appears in the real world, and which tool detects it:
- `examples/caseXX_*/` -- minimal compilable C/C++ examples
- Per-case `README.md` with: scenario -> what breaks -> which tools detect -> severity
- Comparison table: `abicheck` vs `abicc` vs `libabigail` vs `nm`-only
- Coverage matrix showing evidence tier required (ELF-only / DWARF / Header / Runtime)

**In progress:** cases 01-24 done. **TODO:** v2 cases 25-32, libabigail-parity cases.

---

## Goal 6 -- GitHub Pages Documentation Site
Public documentation at `https://napetrov.github.io/abicheck/`:
- Getting started / installation
- CLI reference
- ABI break catalog (rendered from `examples/`)
- Tool comparison table
- Architecture overview

**TODO:** Set up `docs/` Jekyll/MkDocs site, GitHub Actions publish workflow.

---

## Status Summary

| Goal | Status |
|------|--------|
| G1: ABICC drop-in | Sprint 1-5 done: core detectors, ELF, DWARF, compat CLI |
| G2: Known gaps | Sprint 2-4 done: ELF-only, DWARF layout, advanced DWARF |
| G3: libabigail tests | Sprint 6 started: 10 parity cases |
| G4: Agent-friendly | Partial -- JSON/snapshot done, SARIF TODO |
| G5: Break encyclopedia | In progress -- cases 01-24 done |
| G6: GitHub Pages | Not started |
