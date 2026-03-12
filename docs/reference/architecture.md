# Architecture & Analysis Pipeline

This page explains how `abicheck` works internally — what it analyses, in what order,
and how all components combine to produce a verdict.

---

## Overview

`abicheck` uses **four independent analysis tiers** to build a complete picture of
a library's ABI and API surface. Each tier captures things the others cannot.

| Tier | Source | What it catches |
|------|--------|-----------------|
| 1 — castxml/header | C/C++ headers via castxml | function signatures, types, vtables, templates, `noexcept`, `inline` |
| 2 — ELF | `.so` symbol table | symbol presence/removal, SONAME, visibility, binding, versioning |
| 3 — DWARF layout | debug info (`-g`) | struct/class field offsets, sizes, alignment |
| 4 — Advanced DWARF | debug info (`-g`) | calling conventions, struct packing, toolchain flag drift |

The final verdict is the **worst** of all ChangeKinds found across all tiers.

---

## Workflow: `dump` + `compare`

This is the recommended workflow for new integrations.

```text
┌──────────────────────────────────────────────────────────────────┐
│  abicheck dump                                                   │
│                                                                  │
│  libfoo_v1.so ──► ┌────────────────────────────────────────┐    │
│  include/foo.h ──►│  Tier 1: castxml                       │    │
│                   │  (parses headers → C++ AST)            │    │
│                   │  • function signatures                 │    │
│                   │  • struct/class types & vtables        │    │
│                   │  • template instantiations             │    │
│                   │  • noexcept, inline, access levels     │    │
│                   └─────────────┬──────────────────────────┘    │
│                                 │                                │
│                   ┌─────────────▼──────────────────────────┐    │
│                   │  Tier 2: ELF reader                    │    │
│                   │  (reads .so symbol table)              │    │
│                   │  • exported symbol names               │    │
│                   │  • SONAME, RPATH, DT_NEEDED            │    │
│                   │  • symbol visibility & binding         │    │
│                   │  • GNU symbol versioning               │    │
│                   └─────────────┬──────────────────────────┘    │
│                                 │                                │
│                   ┌─────────────▼──────────────────────────┐    │
│                   │  Tier 3: DWARF layout (optional)       │    │
│                   │  (requires -g debug info in .so)       │    │
│                   │  • struct field offsets                │    │
│                   │  • class/union sizes & alignment       │    │
│                   │  • base class offsets                  │    │
│                   └─────────────┬──────────────────────────┘    │
│                                 │                                │
│                   ┌─────────────▼──────────────────────────┐    │
│                   │  Tier 4: Advanced DWARF (optional)     │    │
│                   │  (requires -g debug info in .so)       │    │
│                   │  • calling conventions                 │    │
│                   │  • struct packing (#pragma pack)       │    │
│                   │  • toolchain flag drift (DW_AT_prod.)  │    │
│                   └─────────────┬──────────────────────────┘    │
│                                 │                                │
│                   ┌─────────────▼──────────────────────────┐    │
│                   │  ABI Snapshot (JSON)                   │    │
│                   │  foo-v1.json                           │    │
│                   └────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘

         (repeat for libfoo_v2.so → foo-v2.json)

┌──────────────────────────────────────────────────────────────────┐
│  abicheck compare                                                │
│                                                                  │
│  foo-v1.json ──► ┌────────────────────────────────────────┐     │
│  foo-v2.json ──► │  Checker engine                        │     │
│                  │  • runs detectors on paired snapshots  │     │
│                  │  • each detector emits ChangeKinds     │     │
│                  └─────────────┬──────────────────────────┘     │
│                                │                                 │
│                  ┌─────────────▼──────────────────────────┐     │
│                  │  Suppression engine                    │     │
│                  │  • matches Changes against rules       │     │
│                  │  • suppressed entries kept for audit   │     │
│                  └─────────────┬──────────────────────────┘     │
│                                │                                 │
│                  ┌─────────────▼──────────────────────────┐     │
│                  │  Policy                                │     │
│                  │  • maps ChangeKind → Verdict           │     │
│                  │  • 53 BREAKING + 38 COMPATIBLE         │     │
│                  │  + 11 API_BREAK ChangeKinds            │     │
│                  │  • final verdict = worst of all        │     │
│                  └─────────────┬──────────────────────────┘     │
│                                │                                 │
│            ┌───────────────────┼───────────────────────────┐    │
│            ▼                   ▼                           ▼    │
│  Markdown report         JSON report               SARIF report  │
│  (stdout / -o)           (-o result.json)          (-o abi.sarif)│
└──────────────────────────────────────────────────────────────────┘
```

---

## Workflow: `compat` mode (ABICC drop-in)

Use this when you already have ABICC XML descriptor pipelines.

```text
┌──────────────────────────────────────────────────────────────────┐
│  abicheck compat                                                 │
│                                                                  │
│  OLD.xml ──► ┌─────────────────────────────────────────────┐    │
│  NEW.xml ──► │  compat layer                               │    │
│              │  • parses ABICC XML descriptors             │    │
│              │  • extracts headers path + .so path         │    │
│              │  • calls same dump engine as compare mode   │    │
│              └──────────────┬──────────────────────────────┘    │
│                             │                                    │
│                   ┌─────────▼──────────────────────────────┐    │
│                   │  same 4-tier analysis pipeline         │    │
│                   │  (Tier 1–4, see above)                 │    │
│                   └──────────────┬─────────────────────────┘    │
│                                  │                               │
│                   ┌──────────────▼─────────────────────────┐    │
│                   │  compat exit-code mapping              │    │
│                   │  exit 0 = NO_CHANGE / COMPATIBLE       │    │
│                   │  exit 1 = BREAKING or tool error       │    │
│                   │  exit 2 = API_BREAK                    │    │
│                   └──────────────┬─────────────────────────┘    │
│                                  │                               │
│               ┌──────────────────┼──────────────────────┐       │
│               ▼                  ▼                       ▼       │
│        HTML report         JSON report             XML report    │
│        (ABICC-style)                               (ABICC-style) │
└──────────────────────────────────────────────────────────────────┘
```

---

## When tiers activate

```text
Configuration              Tier 1     Tier 2     Tier 3     Tier 4
───────────────────────    ──────     ──────     ──────     ──────
headers + .so (no -g)       ✅          ✅          ❌          ❌
headers + .so (with -g)     ✅          ✅          ✅          ✅
.so only (no headers)       ❌          ✅          partial     partial
```

> **Recommended:** always pass headers (`-H include/`) for full Tier 1 analysis.
> Without headers, abicheck falls back to ELF-only mode — misses type layout,
> vtable, template, and noexcept changes.

---

## Module map

```text
abicheck/
  cli.py              ← CLI entry points (dump / compare / compat / compat-dump)
  dumper.py           ← builds ABI snapshot from .so + headers (calls all 4 tiers)
  checker.py          ← runs detectors on two snapshots → list[Change]
  checker_policy.py   ← ChangeKind enum, BREAKING/COMPATIBLE/API_BREAK sets
  detectors.py        ← detector protocol + detector result types
  model.py            ← legacy data model: AbiSnapshot, Function, RecordType
  compat.py           ← ABICC XML descriptor parsing + compat mapping
  report_summary.py   ← canonical counters shared by all reporters
  reporter.py         ← Markdown reporter
  sarif.py            ← SARIF reporter (GitHub Code Scanning)
  html_report.py      ← HTML reporter (ABICC-compatible)
  xml_report.py       ← XML reporter (ABICC-compatible machine-readable)
  suppression.py      ← CLI suppression engine (YAML rules for compare/compat)
  serialization.py    ← JSON snapshot read/write
  elf_metadata.py     ← Tier 2: ELF symbol table, SONAME, visibility
  dwarf_metadata.py   ← Tier 3: DWARF struct layout, field offsets
  dwarf_advanced.py   ← Tier 4: calling conventions, packing, toolchain flags
  dwarf_unified.py    ← unified DWARF pass (~50% I/O savings via single-pass read)
  core/
    model/
      change.py       ← Change, ChangeKind, ChangeSeverity, AnnotatedChange
      origin.py       ← Origin (which tier detected the change)
      policy_result.py← PolicyResult, PolicySummary, PolicyVerdict
    corpus/
      normalizer.py   ← AbiSnapshot → NormalizedSnapshot (dedup, intern, canonicalise)
      builder.py      ← NormalizedSnapshot → Corpus (indexed for fast diff)
    diff/
      symbol_diff.py  ← symbol-level Changes (added/removed/changed functions & vars)
      type_layout_diff.py ← struct/class layout Changes (field offsets, sizes)
    suppressions/
      rule.py         ← SuppressionRule, SuppressionScope dataclasses
      engine.py       ← SuppressionEngine: RE2-based, O(N), compile-at-load
    policy/
      base.py         ← PolicyProfile ABC
      strict_abi.py   ← StrictAbiPolicy  (BREAK→BLOCK, REVIEW_NEEDED→WARN)
      sdk_vendor.py   ← SdkVendorPolicy  (same as strict currently)
      plugin_abi.py   ← PluginAbiPolicy  (BREAK→WARN only)
    pipeline.py       ← analyse() + analyse_full(): end-to-end Python API
```

---

## Full data flow

```text
Input: libfoo.so + include/foo.h
           │
           ▼
      dumper.py
      ├── castxml            → parses headers → AST (functions, types, vtable)
      ├── elf_metadata.py    → reads .dynsym, .gnu.version, SONAME
      ├── dwarf_metadata.py  → reads DWARF .debug_info (struct layouts)
      └── dwarf_unified.py   → single-pass DWARF read (performance)
           │
           ▼
      AbiSnapshot (JSON)
      { functions: [...], types: [...], elf: {...} }
           │
     (compare two snapshots)
           │
           ▼
      core/corpus/normalizer.py
      └── AbiSnapshot → NormalizedSnapshot
          (dedup, intern strings, canonicalise type names)
           │
           ▼
      core/diff/symbol_diff.py        → list[Change]  (func/var level)
      core/diff/type_layout_diff.py   → list[Change]  (struct/class level)
           │
           ▼  sorted(entity_type, entity_name, change_kind)
           │
      core/suppressions/engine.py
      └── SuppressionEngine.apply(changes)
          → SuppressionResult {
              active:     list[Change]   (not matched by any rule)
              suppressed: list[Change]   (severity = SUPPRESSED)
              match_map:  audit trail    (entity_type, name, kind) → rule
            }
           │
           ▼  sorted(active + suppressed) — restores original order
           │
      core/policy/<profile>.py
      └── PolicyProfile.apply(changes)
          → PolicyResult {
              annotated_changes: list[AnnotatedChange]
              summary: PolicySummary {
                verdict,             ← PASS / WARN / BLOCK
                incompatible_count,
                suppressed_count,
                review_needed_count,
              }
            }
           │
           ▼
      reporter / sarif / html_report / xml_report
```

---

## Suppression engine

Intentional ABI changes can be acknowledged and filtered out without masking
unrelated breakage. The suppression engine matches each `Change` against a list
of `SuppressionRule` objects compiled at load time.

### SuppressionRule (`abicheck/core/suppressions/rule.py`)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `entity_glob` | `str \| None` | `None` | Shell-style glob matched against the entity name (`std::*`, `*detail*`) |
| `entity_regex` | `str \| None` | `None` | RE2 regex; if both glob and regex are set, **both must match** (AND semantics) |
| `change_kind` | `str \| None` | `None` | `ChangeKind` value string (e.g. `"func_removed"`); `None` = any kind |
| `scope` | `SuppressionScope` | `SuppressionScope()` | Platform/profile/version filters — parsed but not yet enforced; raises `ValueError` if set |
| `reason` | `str` | `""` | Human-readable justification (appears in report audit trail) |

### SuppressionEngine (`abicheck/core/suppressions/engine.py`)

- All glob and regex patterns compiled once in `__init__()` via **google-re2** — O(N) guaranteed, no backtracking.
- **First-match wins**: earliest rule whose patterns + `change_kind` all match suppresses the Change.
- Suppressed changes carry `severity = ChangeSeverity.SUPPRESSED` and are included in `SuppressionResult.suppressed` for audit.
- Audit trail: `SuppressionResult.match_map[(entity_type, entity_name, change_kind.value)] → SuppressionRule`.

### CLI suppression (YAML)

The CLI (`abicheck compare` / `abicheck compat`) uses the YAML-based engine in
`abicheck/suppression.py`. Rule fields: `symbol`, `symbol_pattern`, `type_pattern`, `reason`.
See `examples/suppression_example.yaml` for a runnable example.

### Python API

```python
from abicheck.core.pipeline import analyse_full
from abicheck.core.suppressions import SuppressionRule

result = analyse_full(
    snap_v1, snap_v2,
    rules=[
        SuppressionRule(entity_glob="*detail*", reason="internal namespace"),
        SuppressionRule(
            entity_regex=r"_ZN3foo6Client10disconnectEv",
            change_kind="func_removed",
            reason="deprecated in v1.8, removed in v2.0",
        ),
    ],
    policy="strict_abi",   # or "sdk_vendor" / "plugin_abi"
)
print(result.summary.verdict)          # PolicyVerdict.PASS / WARN / BLOCK
print(result.summary.suppressed_count)
```

---

## Policy profiles (`abicheck/core/policy/`)

| Profile | Class | Behaviour |
|---------|-------|-----------|
| `strict_abi` | `StrictAbiPolicy` | `BREAK → BLOCK`, `REVIEW_NEEDED → WARN`. Zero-tolerance; for system libraries and OS distributions. |
| `sdk_vendor` | `SdkVendorPolicy` | Currently identical to `strict_abi`. Differentiated profile planned. For SDK/vendor libraries. |
| `plugin_abi` | `PluginAbiPolicy` | `BREAK → WARN` only (no BLOCK). For plugin ABIs where some ABI growth is tolerated. |

> Policy profiles are available via the Python API (`analyse_full(policy=...)`).
> A `--policy` CLI flag is planned.

---

## Snapshot format

ABI snapshots are portable JSON files created by `abicheck dump`.

```json
{
  "version": "1",
  "library": "libfoo",
  "library_version": "1.0",
  "functions": [
    {
      "name": "foo_init",
      "mangled": "_Z8foo_initv",
      "return_type": "int",
      "params": [],
      "is_virtual": false,
      "noexcept": false
    }
  ],
  "types": [ "..." ],
  "elf": {
    "soname": "libfoo.so.1",
    "exported_symbols": ["_Z8foo_initv"],
    "symbol_versions": {}
  }
}
```

Snapshots can be stored in CI artifacts for offline comparison and ABI history tracking.

---

## Choosing a workflow

```text
Do you have ABICC XML descriptors already?
├── YES → use `abicheck compat` (drop-in, same flags)
│          then migrate to `abicheck compare` when ready
│
└── NO → use `abicheck dump` + `abicheck compare`
          │
          Is your .so compiled with -g (debug info)?
          ├── YES → full 4-tier analysis (most accurate)
          └── NO  → Tier 1+2 only (headers + ELF)
                    covers the majority of ABI breaks
```

---

## Comparison: `compare` vs `compat`

| Feature | `compare` | `compat` |
|---------|-----------|---------|
| Input | JSON snapshots | ABICC XML descriptors |
| Output formats | md, json, sarif, html | html, json, xml, md |
| Verdicts | NO_CHANGE / COMPATIBLE / API_BREAK / BREAKING | ABICC-style compatibility report |
| Exit codes | 0 / 1(err) / 2 / 4 | 0 / 1 / 2(API_BREAK) |
| Suppression | YAML rules (`suppression.py`) | `-skip-*` flags + YAML |
| ABICC flag parity | — | partial (see [from_abicc.md](../migration/from_abicc.md)) |
| Recommended for | new integrations | migrating from ABICC |
