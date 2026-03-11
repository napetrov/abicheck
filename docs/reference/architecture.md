# Architecture & Analysis Pipeline

This page explains how `abicheck` works internally — what it analyzes, in what order,
and how the four analysis tiers combine to produce a verdict.

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
│                  │  checker_policy                        │     │
│                  │  • maps ChangeKind → Verdict           │     │
│                  │  • 53 BREAKING + 38 COMPATIBLE         │     │
│                  │  + 11 API_BREAK ChangeKinds            │     │
│                  │  • final verdict = worst of all        │     │
│                  └─────────────┬──────────────────────────┘     │
│                                │                                 │
│                  ┌─────────────▼──────────────────────────┐     │
│                  │  DiffResult                            │     │
│                  │  { verdict, changes: [Change] }        │     │
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
  cli.py            ← CLI entry points (dump / compare / compat / compat-dump)
  dumper.py         ← builds ABI snapshot from .so + headers (calls all 4 tiers)
  checker.py        ← runs detectors on two snapshots → DiffResult
  checker_policy.py ← ChangeKind enum, BREAKING/COMPATIBLE/API_BREAK sets, verdict logic
  detectors.py      ← detector protocol + detector result types
  model.py          ← core data model: AbiSnapshot, Function, RecordType, Change
  compat.py         ← ABICC XML descriptor parsing + compat mapping
  report_summary.py ← canonical counters shared by all reporters
  reporter.py       ← Markdown reporter
  sarif.py          ← SARIF reporter (GitHub Code Scanning)
  html_report.py    ← HTML reporter (ABICC-compatible)
  xml_report.py     ← XML reporter (ABICC-compatible machine-readable)
  suppression.py    ← suppression engine (compare YAML + compat -skip-* flags)
  serialization.py  ← JSON snapshot read/write
  elf_metadata.py   ← Tier 2: ELF symbol table, SONAME, visibility
  dwarf_metadata.py ← Tier 3: DWARF struct layout, field offsets
  dwarf_advanced.py ← Tier 4: calling conventions, packing, toolchain flags
  dwarf_unified.py  ← unified DWARF pass (~50% I/O savings via single-pass read)
```

---

## Data flow (internal)

```text
Input: libfoo.so + include/foo.h
           │
           ▼
      dumper.py
      ├── castxml → parses headers → AST
      │   └── extracts: functions, types, vtable, noexcept, inline
      ├── elf_metadata.py → reads .dynsym, .gnu.version, SONAME
      ├── dwarf_metadata.py → reads DWARF .debug_info (struct layouts)
      └── dwarf_unified.py → single-pass DWARF read (performance)
           │
           ▼
      AbiSnapshot (JSON)
      { functions: [...], types: [...], elf: {...} }
           │
     (compare two snapshots)
           │
           ▼
      checker.py
      └── runs each detector on (old_snapshot, new_snapshot)
          ├── FuncDetector → FUNC_REMOVED, FUNC_PARAMS_CHANGED, ...
          ├── TypeDetector → TYPE_SIZE_CHANGED, TYPE_VTABLE_CHANGED, ...
          ├── ElfDetector  → SONAME_CHANGED, VISIBILITY_LEAK, ...
          └── DwarfDetector → CALLING_CONVENTION_CHANGED, ...
           │
           ▼
      checker_policy.py
      compute_verdict(changes) → Verdict
      (worst of: BREAKING > API_BREAK > COMPATIBLE > NO_CHANGE)
           │
           ▼
      DiffResult { verdict, changes: [Change] }
           │
           ▼
      reporter / sarif / html_report / xml_report
```

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
  "types": [ ... ],
  "elf": {
    "soname": "libfoo.so.1",
    "exported_symbols": ["_Z8foo_initv"],
    "symbol_versions": { ... }
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
| Verdicts in report | NO_CHANGE / COMPATIBLE / API_BREAK / BREAKING | ABICC-style compatibility report |
| Exit codes | 0 / 1(err) / 2 / 4 | 0 / 1 / 2(API_BREAK) |
| ABICC flag parity | — | full (`-lib`, `-old`, `-new`, `-s`, ...) |
| Recommended for | new integrations | migrating from ABICC |
