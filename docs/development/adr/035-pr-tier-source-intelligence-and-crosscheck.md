# ADR-035: PR-Tier Source Intelligence and Cross-Source Validation

**Date:** 2026-06-14
**Status:** Proposed
**Decision maker:** (pending review)

---

## Context

A field proposal ("Source scans в abicheck: уровни глубины, инструменты,
кросс-чеки и интеграция с билдом") argues that source-aware analysis should
not be an all-or-nothing "dump every translation unit's AST" mode run only at
release/nightly. Instead it proposes a configurable ladder of source scans
(`S0..S6`) with per-level cost, a risk-scored escalation policy, cross-source
validation, and build-integrated fact extraction — so that compatibility risk
is caught **on the PR**, cheaply, and deeper analysis runs only when triggered.

Most of that architecture already exists in abicheck. ADR-028…033 define an
optional build/source evidence stack:

- **L0/L1/L2** — artifact-authoritative binary, debug-info, and header-AST scan
  (`dumper.py`, `dumper_castxml.py`, `elf/pe/macho_metadata.py`, `dwarf_*.py`).
- **L3** — build/toolchain context from compile DB, CMake, Ninja, Bazel, Make
  (`buildsource/adapters/*`, `build_evidence.py`, `build_diff.py`).
- **L4** — scoped per-TU source-ABI replay via clang/castxml/android backends
  with per-TU caching (`source_replay.py`, `source_extractors/*`).
- **L5** — source/implementation graph (include/call/type/build edges, Kythe /
  CodeQL ingest) (`source_graph.py`, `call_graph.py`, `include_graph.py`).
- A CI complexity ladder, replay scopes (`off`/`headers-only`/`changed`/
  `target`/`full`), per-TU + content-addressed caches, evidence policy, and
  coverage/metrics reporting (ADR-033 D1–D10).

Mapped onto that stack, the proposal's `S0..S6` scale is **not a new axis** —
it largely re-derives the existing L-layers:

| Proposal level | abicheck today | Gap |
|---|---|---|
| `S0` diff classifier + risk score | `recommend-collect-mode` (path → mode) | no numeric risk score / escalation thresholds / `risk_rules` config |
| `S1` compile-DB / build-flag scan | **L3** (5 adapters, flag-drift diff) | covered |
| `S2` preprocessor + include graph | **L5** include edges (`clang -MM`) | no per-TU macro-value capture, no private-header-leak / generated-config detection |
| `S3` lexical/pattern scan (no compiler) | — | **missing entirely** (no compiler-free tier) |
| `S4` symbol/reference index | **L5** call edges + Kythe/CodeQL ingest | no clangd-index integration (acceptable) |
| `S5` targeted semantic AST | **L4** scoped replay | covered |
| `S6` full AST | **L4** `--source-abi-scope full` | covered |
| cross-checks (§6) | partial (`dumper` logs some leaks) | **no cross-check findings** as `ChangeKind`s |
| build-plugin / wrapper extraction (§8) | ADR-032 extractor plugin + ADR-033 D1 "Phase 6" | **not implemented**; no dump/facts artifact protocol |
| normalized facts, caches, coverage report | covered (ADR-030/033) | extend naming for new tiers |

So three genuine gaps remain, and they are exactly where the proposal's value
concentrates:

1. **No cheap, always-on PR tier.** Every existing evidence layer (L3–L5) needs
   a compile DB or a compiler. There is nothing that runs in `<5%` of build
   cost on *every* PR with no toolchain (the proposal's `S0`/`S2`-macro/`S3`).
2. **No cross-source validation engine.** abicheck holds binary exports, header
   AST, build flags, and source facts in one snapshot but never diffs them
   *against each other within a single version* (exported-but-not-public,
   header built with different macros than the shipped TU, private-header leaks,
   ODR type variants).
3. **No build-integrated extraction or single `scan` UX.** Capability is spread
   across `dump`/`compare`/`collect`/`compare-graph`; there is no risk → budget
   → escalation orchestrator, and no way to ingest facts emitted *by the
   product build* instead of re-running a frontend.

---

## Decision

### D1. Keep the L0–L5 numbering; do not adopt a parallel `S0..S6` scale

The proposal's source ladder is folded into the existing L-layers per the
mapping table above. A second numbering axis would fork the docs/ADR set
(ADR-028…033) and confuse the evidence model for no capability gain. New work
is described as *extensions of named layers*, and the **authority rule
(ADR-028 D3) is preserved**: L0/L1/L2 artifact evidence stays authoritative for
`BREAKING` verdicts; everything added here emits `RISK` or `API_BREAK` findings
that explain, localize, and add confidence — never a standalone shipped break.

### D2. Add an always-on, compiler-free PR pre-scan tier (extends L2/L5)

A new cheap tier runs on every PR over **changed + public** files, needing no
compile DB and no compiler:

- **Pattern pre-scan** (new `buildsource/pattern_scan.py`): regex/lexical scan
  for ABI-risk constructs — `#pragma pack`, `alignas`, `__attribute__((packed|
  visibility))`, `__declspec(dllexport|dllimport)`, `extern "C"`, calling-
  convention macros, explicit / `extern` template instantiation, `inline
  namespace`, public virtual methods, `operator new`/`delete`. Emits advisory
  facts and escalation triggers, never a final verdict. Starts as a stdlib
  regex scanner (no new dependency); Tree-sitter is an optional later backend.
- **Preprocessor pre-scan** (extends `buildsource/include_graph.py`): when a
  compile DB is present, capture per-TU macro values for ABI-affecting macros
  and detect *public-header-includes-private/generated-header* leaks and
  per-TU macro-value divergence for the same public type.

These feed D3 (escalation) and D4 (cross-checks). Output is normalized facts in
the existing `buildsource` schema, with coverage reported (ADR-033 D6/D9).

### D3. Risk-scored escalation and budgeted orchestration via a `scan` command

- Promote `recommend_collect_mode()` to compute a **numeric risk score** from a
  `risk_rules` config block (path globs → weights: public header `+50`, export
  map `+50`, ABI-affecting flag `+40`, exported-symbol definition `+30`,
  reachable-from-public `+25`, template-instantiation change `+35`,
  docs/tests-only `-100`). Score selects the evidence depth (thresholds map to
  the existing `off`/`build`/`source-changed`/`source-target`/`graph-*` modes).
- Add a **`scan`** subcommand (`abicheck/cli_scan.py`, registered per the
  CLAUDE.md sibling-module pattern) that orchestrates: classify → always-on
  tier (D2) → escalate L3/L4/L5 by score within a **time/TU budget** → emit one
  coverage- and confidence-annotated report. Partial results are first-class:
  the report states exactly which tiers ran and at what cache-hit rate, never a
  bare "source scan failed". `scan` is a convenience front-end over existing
  `dump`/`compare`/`collect`; it adds no new authority.

### D4. Cross-source validation engine (new findings, RISK/API_BREAK tier)

New `buildsource/crosscheck.py` consumes one merged snapshot and diffs its
evidence sources against each other *within a single version*. Each check is a
named `ChangeKind` (added per the four-step procedure in `/CLAUDE.md`,
partitioned into `RISK_KINDS` or `API_BREAK_KINDS` — never `BREAKING_KINDS`,
per D1). Initial set, cheapest first:

| Check | Inputs | Tier |
|---|---|---|
| `exported_not_public` | binary exports ↔ L2 header decls | RISK |
| `public_not_exported` | L2 header decls ↔ binary exports | RISK |
| `header_build_context_mismatch` | L2 header macros/flags ↔ L3 build flags | API_BREAK |
| `private_header_leak` | L5 include graph ↔ install manifest | RISK |
| `odr_type_variant` | L4 per-TU layouts of one type | API_BREAK |
| `public_to_internal_dependency` / behavioral risk | L5 reachability ↔ PR changed files | RISK |

The §6.8 provider-agreement matrix maps directly onto the existing
`LayerConfidence`; each finding records which providers (`public_header_ast`,
`source_index`, `binary_exports`, `debug_info`, `build_config`) corroborate the
entity, driving the confidence tag.

### D5. Build-integrated extraction: dump/facts artifact protocol + providers

Implement the proposal's §8 as concrete ADR-032 extractor providers, with the
extended-variant §8.0 distinction made explicit:

- **Flow 1 (abicheck-runs-replay)** — already supported: `dump --sources` /
  `collect` replays selected compile commands. Stays the portable default.
- **Flow 2 (build-emits-facts)** — new: a standardized **dump/facts artifact
  protocol** the product build drops next to its binary, which abicheck then
  ingests without re-running a frontend:

  ```text
  abicheck_inputs/
    manifest.json
    binary/…  headers/…  build/compile_commands.json
    source_facts/*.jsonl   # preferred — normalized facts
    raw_ast/*.json.zst     # optional, debug/forensic only
    pp/*.macros.jsonl  deps/*.d   # optional
  ```

  This rides the existing `merge` flow (artifact-side + source-side dumps merged
  into one baseline, ADR-028 D8 / ADR-033 amendment).

- **Providers** (ADR-032 manifest extractors): a Clang plugin
  (`-fplugin=…`, normalized facts during normal compile, no raw AST by default)
  and a compiler wrapper (`abicheck-cc clang++ …`, companion extraction action).
  GCC `-fdump-lang-class`/`-tinst` and MSVC remain documented fallbacks.

**Canonical rule:** normalized source facts are the comparison format; raw AST
dumps are an MVP-ingest/forensic fallback only. The Clang plugin is positioned
as a *performance optimization* (removes the second frontend pass), never a
requirement — it is compiler-version-sensitive, so `compile_commands.json`
replay + LibTooling/CastXML stays the supported portable path.

### D6. Additive `.abicheck.yml` schema for levels, budgets, and cross-checks

Extend the config loaded by `buildsource/inline.py` with optional `source:
{ budgets, levels }`, `risk_rules`, and `crosschecks: { <check>: info|warning|
error }` blocks. All additive and defaulted-off where they imply new cost; they
map onto the existing collect-mode / evidence-policy machinery rather than
replacing it.

---

## Consequences

**Positive**

- A real always-on PR signal (D2/D3) catches ABI-affecting flag/macro changes,
  private-header leaks, and risky source patterns without a build or a compiler.
- The cross-check engine (D4) turns abicheck from single-source-of-truth into a
  multi-evidence system with corroboration-based confidence and better
  explanations — at low cost, since the inputs already sit in the snapshot.
- Flow 2 (D5) lets vendor/closed-source consumers contribute exact-build-context
  facts without shipping sources or letting abicheck rebuild the project.

**Negative / costs**

- The Clang plugin and compiler wrapper are compiler-version-sensitive and add
  maintenance surface; mitigated by keeping them strictly optional optimizations
  behind the portable replay path (D5) and the ADR-032 action ceiling.
- New `ChangeKind`s (D4) must stay correctly partitioned (import-time assertion)
  and earn corpus/FP-rate-gate coverage before they can gate, to avoid false
  positives on legitimate internal noise.
- `scan` (D3) adds a CLI surface; it must remain a thin orchestrator so the
  authority rule (D1) is not diluted.

**Out of scope**

- Replacing or re-numbering the L0–L5 model.
- Making any source/cross-check finding authoritative for a `BREAKING` verdict.
- clangd-index integration (the existing call/include graph is sufficient).

---

## Relationship to existing ADRs

- **ADR-028** — preserves the evidence-pack authority rule (D1); adds Flow 2
  artifact protocol on the merge path (D5).
- **ADR-029/030/031** — D2/D4 consume L3/L4/L5 outputs; no model change.
- **ADR-032** — D5 plugin/wrapper are extractor providers under its security
  model and action ceiling.
- **ADR-033** — D2/D3 extend the CI ladder, replay scopes, caches, and coverage
  reporting; D5 realizes its "Phase 6: instrumented compiler/build plugins".
- **ADR-025** — D3 generalizes PR-diff-as-trigger into a scored escalation.

See the phased work breakdown in
[plans/g19-pr-source-intelligence.md](../plans/g19-pr-source-intelligence.md).

---

## References

- Source-scan strategy proposal (uploaded field document, 2026-06).
- ADR-028 — Source and Build Evidence Pack
  ([028-source-build-evidence-pack.md](028-source-build-evidence-pack.md))
- ADR-032 — Evidence Extractor Plugin Interface
  ([032-evidence-extractor-plugin-interface.md](032-evidence-extractor-plugin-interface.md))
- ADR-033 — CI Rollout, Performance, Caching, and Validation
  ([033-ci-rollout-performance-and-validation.md](033-ci-rollout-performance-and-validation.md))
- Clang plugins: https://clang.llvm.org/docs/ClangPlugins.html
- LibTooling: https://clang.llvm.org/docs/LibTooling.html
- Tree-sitter: https://tree-sitter.github.io/tree-sitter/
