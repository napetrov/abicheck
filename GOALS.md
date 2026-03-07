# Project Goals — abicheck

> **Context:** abi-compliance-checker (ABICC) and libabigail are no longer actively maintained.
> `abicheck` is their modern Python successor — drop-in compatible first, then better.

---

## Goal 1 — Drop-In Replacement for ABICC
Support everything ABICC currently does so existing users/pipelines can migrate without changes:
- Same detection coverage (C/C++ ABI breaks: symbols, types, vtables, enums, layout)
- CLI interface compatible with ABICC inputs (XML descriptors, headers+libs)
- JSON/HTML/Markdown reports with equivalent verdict semantics
- Support for suppression files

**Done:** Sprint 1 closes 13 detection gaps; Sprint 2 adds ELF-only layer ABICC lacks.
**TODO:** Audit ABICC feature list → gap matrix → fill remaining items.

---

## Goal 2 — Close Known Gaps + Extend
Fix known ABICC / libabigail limitations and add new detection capability:
- Toolchain/flag drift detection (`DW_AT_producer`, `-fshort-enums`, `-fpack-struct`)
- DWARF-aware layout analysis (calling convention, packing, RTTI/visibility boundaries)
- Header/API surface diff (AST-based, macro contracts, inline/template changes)
- Confidence/evidence tiers in output (ELF_ONLY / DWARF_AWARE / HEADER_AWARE)

**Roadmap:** Sprint 3 = DWARF-aware tier; Sprint 4 = header/AST tier.

---

## Goal 3 — Pass libabigail Test Suite
Run `abicheck` against libabigail's own regression test cases and reach 100% pass rate:
- Mirror libabigail's `tests/` corpus as integration examples
- Add per-case expected verdicts to CI
- Use as the compatibility regression gate before each release

**TODO:** Clone libabigail test suite, map to `examples/caseXX_*`, run in CI.

---

## Goal 4 — Agent-Friendly Design
Make the tool convenient for AI agents and automation pipelines:
- Structured JSON output (machine-readable, no scraping)
- Clear exit codes (0=no change, 1=breaking, 2=compatible additions, 3=error)
- Python API (`from abicheck import compare, dump`) — not just CLI
- `--format json/markdown/sarif` output modes
- MCP / tool-use compatible JSON schema for change entries
- Snapshot files for offline/async workflows (`abicheck dump` → `.abi.json`)

**Partially done:** JSON output, snapshot format. **TODO:** SARIF output, Python API docs, MCP schema.

---

## Goal 5 — Compatibility Break Encyclopedia
For each break type: what it is, how it appears in the real world, and which tool detects it:
- `examples/caseXX_*/` — minimal compilable C/C++ examples
- Per-case `README.md` with: scenario → what breaks → which tools detect → severity
- Comparison table: `abicheck` vs `abicc` vs `libabigail` vs `nm`-only
- Coverage matrix showing evidence tier required (ELF-only / DWARF / Header / Runtime)

**In progress:** cases 01–24 done. **TODO:** v2 cases 25–32, libabigail-parity cases.

---

## Goal 6 — GitHub Pages Documentation Site
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
| G1: ABICC drop-in | 🟡 In progress — Sprint 1+2 close major gaps |
| G2: Known gaps | 🟡 In progress — Sprint 2 ELF done, Sprint 3 DWARF next |
| G3: libabigail tests | 🔴 Not started |
| G4: Agent-friendly | 🟡 Partial — JSON/snapshot done, SARIF/MCP TODO |
| G5: Break encyclopedia | 🟡 In progress — cases 01–24 done |
| G6: GitHub Pages | 🔴 Not started |
