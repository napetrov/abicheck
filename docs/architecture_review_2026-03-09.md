# Architecture & Design Review — abicheck

**Date:** 2026-03-09  
**Reviewer:** Codex (GPT-5.2-Codex)  
**Scope:** Repository structure, module boundaries, design choices, and improvement roadmap.

## Executive summary

abicheck has a strong core architecture for a Python-first ABI checker: clean domain model, distinct pipeline stages, good test depth, and pragmatic compatibility goals. The main risks are not missing functionality, but **architectural drift** (duplicate code paths, mixed responsibilities in `checker.py`, and inconsistent source-of-truth across docs and implementation). Addressing those issues would make the project easier to evolve and safer for long-term maintenance.

## 1) Current architecture at a glance

The repository is organized around a mostly layered flow:

1. **Input / extraction**: `dumper.py`, `elf_metadata.py`, `dwarf_*` modules parse headers/ELF/DWARF into structured data.
2. **Core domain model**: `model.py` defines snapshots and ABI entities.
3. **Diff engine**: `checker.py` compares two snapshots and classifies changes.
4. **Presentation layer**: `reporter.py`, `html_report.py`, `xml_report.py`, `sarif.py` serialize results.
5. **CLI/application layer**: `cli.py` wires commands and output formats.
6. **Compatibility adapter**: `compat.py` supports ABICC-style descriptors and flags.

This shape is good: it allows evolution of detection backends while preserving report and CLI surfaces.

## 2) What is good

### 2.1 Clear product strategy and transition path

The project has a concrete positioning: ABICC-compatible migration path plus modern outputs (JSON/SARIF/Markdown/HTML). That strategy is visible both in the README and CLI UX, and lowers adoption friction.

### 2.2 Strong modularity in data flow

The model → compare → report chain is well separated conceptually. Most modules have single, recognizable responsibilities (e.g., `serialization.py` for persistence; `sarif.py` for SARIF mapping).

### 2.3 Excellent practical test surface

The test suite is broad (unit + parity + integration + format-specific coverage), and the `examples/` catalog provides realistic ABI break scenarios. This is a major architectural asset because ABI tools are regression-sensitive.

### 2.4 Security-minded parsing choices

Use of `defusedxml` and safe YAML loading patterns is a positive sign for supply-chain/CI safety and aligns with a tool that often consumes generated artifacts.

### 2.5 Documentation maturity

The repository includes ADRs, coverage docs, parity docs, usage guides, and sprint notes. This is above average and reduces bus-factor risk.

## 3) What is bad / risky

### 3.1 `checker.py` has grown into a “god module”

The change taxonomy, classification policy, and comparison orchestration are concentrated in one large file. This makes policy changes harder to reason about and increases merge conflict likelihood.

**Impact:** harder onboarding, higher accidental-coupling risk, slower safe iteration.

### 3.2 Multiple truth sources for policy semantics

Some rule semantics are repeated across README/docs/comments/code. When policy evolves (e.g., compatibility classification nuances), drift can happen between user-facing docs and actual verdict logic.

**Impact:** user confusion and compliance uncertainty in CI gates.

### 3.3 Architecture intent vs implementation drift risk

ADR guidance and practical implementation can diverge over time (e.g., optional vs runtime dependencies, or preferred parser paths). This is common in fast-moving tooling, but it should be guarded by explicit checks.

**Impact:** silent contract erosion and unexpected runtime dependencies.

### 3.4 Output/reporting logic partially duplicates derived metrics

Different report formats compute or present related summary metrics with slight variations. Without a single canonical summary builder, this can lead to inconsistent numbers/messages across markdown/html/json/sarif.

**Impact:** low trust in reports when teams compare formats.

### 3.5 Limited plugin boundary for future detectors

While modules exist for ELF/DWARF/castxml logic, there is no explicit detector plugin contract (`Detector` interface) with a unified result schema and capability flags.

**Impact:** adding new detectors (or replacing one) requires touching central orchestration logic.

## 4) Recommended improvements (prioritized)

### P0 (high value, low-medium effort)

1. **Split `checker.py` into policy + engine + rulesets**
   - `checker/engine.py`: diff orchestration over snapshots.
   - `checker/policy.py`: verdict mapping and severity rules.
   - `checker/rules/*.py`: function/type/elf/dwarf-specific detectors.
   - Keep a compatibility shim (`abicheck.checker`) for imports.

2. **Create a single “policy registry” as source-of-truth**
   - One table (or dataclass map) for `ChangeKind -> {default_verdict, severity, doc_slug}`.
   - Generate docs snippets from this registry where possible.

3. **Centralize summary metric computation**
   - Add `report_summary.py` with canonical counters/percentages.
   - All output adapters consume this shared structure.

### P1 (medium value, medium effort)

4. **Add detector capability contracts**
   - Define a protocol/interface with `run(old, new) -> DetectorResult` and metadata.
   - Allows graceful enable/disable and transparent “coverage gaps” reporting.

5. **Architectural conformance tests**
   - Tests that enforce key ADR claims (e.g., forbidden runtime subprocess paths in production mode, consistent verdict mapping coverage for all `ChangeKind`).

6. **Documentation anti-drift automation**
   - Add CI checks that compare generated policy tables against checked-in docs.

### P2 (longer horizon)

7. **Typed public API boundaries**
   - Add explicit exported API modules and stricter type contracts for extension authors.

8. **Performance observability**
   - Track stage timings (`dump`, parse, compare, render) and expose optional profiling output to detect regressions early.

## 5) Suggested target architecture

```text
abicheck/
  model.py
  snapshot/
    dumper.py
    serialization.py
    loaders/elf.py
    loaders/dwarf.py
    loaders/castxml.py
  diff/
    engine.py
    policy.py
    rules/
      functions.py
      types.py
      symbols.py
      dwarf.py
  report/
    summary.py
    markdown.py
    html.py
    xml.py
    sarif.py
  adapters/
    abicc_compat.py
  cli.py
```

This preserves current behavior while improving separations and making future detector growth less invasive.

## 6) Final assessment

- **Overall architecture grade:** **B+ (strong foundation, needs modular refactoring for scale).**
- **Best qualities:** practical modular pipeline, test richness, migration-friendly product design.
- **Most important next step:** decouple policy/rules from monolithic comparison logic and enforce one canonical policy registry.
