# Tool Comparison: abicheck vs abidiff vs ABICC

This document explains how each tool works, what analysis method it uses, and why
the benchmark numbers come out the way they do.

---

## How each tool analyses ABI

### abicheck (compare mode)

```
.so (v1) ──► ELF reader: exported symbols, SONAME, visibility
             castxml (Clang AST): types, methods, vtable, noexcept
             DWARF reader: size cross-check
          ──► snapshot (JSON)
                              ├──► checker engine ──► verdict
.so (v2) ──► (same) ──► snapshot (JSON) ┘
```

**Analysis basis:** ELF symbol table + Clang AST via castxml + DWARF.  
**Header requirement:** Yes — headers are passed to castxml for full type analysis.  
**Compiler requirement:** None — castxml runs separately as a standalone tool.

This gives abicheck three independent data sources per symbol: ELF (what is exported),
AST (what the C++ type contract says), and DWARF (actual compiled layout for cross-check).

---

### abicheck (compat mode)

Same analysis engine as `compare`, but accepts **ABICC-format XML descriptors**
instead of snapshots:

```xml
<descriptor>
  <version>1.0</version>
  <headers>/path/to/include/foo.h</headers>
  <libs>/path/to/libfoo.so</libs>
</descriptor>
```

Used as a drop-in for ABICC-based CI pipelines (`abicheck compat -lib foo -old v1.xml -new v2.xml`).

**Why compat scores lower (40/42 vs 42/42):**  
`compat` follows ABICC's verdict vocabulary: COMPATIBLE, BREAKING, NO_CHANGE.
It cannot emit `API_BREAK` — the verdict for source-level-only breaks that are binary-safe
(e.g. a parameter rename, or reduced access level in a class method).  
Two benchmark cases (`case31_enum_rename`, `case34_access_level`) expect `API_BREAK`,
so they score as misses in compat mode.  
This is intentional and documented in `examples/ground_truth.json` as `expected_compat`.

**When to use `compat`:** When you have an existing ABICC XML pipeline and want to
migrate to abicheck without rewriting scripts.  
**When to use `compare`:** For all new integrations — full verdict set including `API_BREAK`.

---

### abicheck (strict mode)

`compat` with `-s` / `--strict` flag. Promotes `COMPATIBLE` → `BREAKING` and
`API_BREAK` → `BREAKING`.

Two sub-modes via `--strict-mode`:
- `full` (default with `-s`): `COMPATIBLE` + `API_BREAK` → `BREAKING` (matches ABICC `-strict`)
- `api`: only `API_BREAK` → `BREAKING`, additive `COMPATIBLE` changes stay `COMPATIBLE`

**Why strict scores 31/42 (not 100%):**  
Nine benchmark cases are legitimately `COMPATIBLE` (additive changes, SONAME addition,
symbol versioning policy, etc.). `--strict-mode full` promotes these to `BREAKING` —
intentionally, just like ABICC `-strict`. These are correct tool outputs for the
strict policy, but score as misses against the ground truth which says `COMPATIBLE`.

**Why strict (31/42) > ABICC dumper (20/30 = 66%):**  
ABICC dumper fails to even produce a result on 12 cases (ERROR + TIMEOUT), so its
denominator is only 30. abicheck strict runs on all 42 cases — even cases where the
verdict is intentionally promoted. If you normalise ABICC dumper to 42 cases,
its effective accuracy is 20/42 = 48%, well below strict's 31/42 = 73%.

**When to use strict:** CI gates where any COMPATIBLE addition (e.g. new symbol) should
fail the build. Use `--strict-mode api` to avoid false positives on purely additive changes.

---

### abidiff (ELF mode, no headers)

```
.so (v1) ──► abidw ──► ABI XML ──┐
                                  ├──► abidiff ──► report
.so (v2) ──► abidw ──► ABI XML ──┘
```

**Analysis basis:** DWARF debug info only (requires `-g` at compile time).  
**Header requirement:** None (in ELF mode).  
**Compiler requirement:** None.

abidiff reads type information from DWARF sections of the `.so`. It can detect layout
changes if the types are fully described in DWARF, but misses semantic changes that
are not encoded in DWARF (noexcept, inline, access level, etc.).

**Benchmark result: 11/42 (26%)**  
abidiff misses anything that is not directly a symbol removal or a change that DWARF
fully describes. Specifically:
- Struct layout, vtable, return type changes → DWARF often marks as COMPATIBLE because
  it cannot determine binary impact without header type context
- Enum value semantics, typedef chains → COMPATIBLE
- noexcept, static qualifier, const qualifier, access level → not in DWARF at all

---

### abidiff (+headers)

```
.so (v1) ──► abidw --headers-dir /path/to/headers/ ──► ABI XML ──┐
                                                                   ├──► abidiff ──► report
.so (v2) ──► abidw --headers-dir /path/to/headers/ ──► ABI XML ──┘
```

**`--headers-dir` role:** Filters which symbols are considered public API.
It does **not** provide additional type information — abidiff still reads types from DWARF.

**Why abidiff+headers = abidiff in our suite (both 11/42):**  
Our benchmark examples are compiled with `-fvisibility=default`, meaning all symbols
are exported by default. None of the headers use `__attribute__((visibility("hidden")))`.  
So the header filter changes nothing — all symbols are already public in both modes.  
The fundamental limitation is that abidiff relies on DWARF for types, not AST.
Even with perfect headers, it cannot see noexcept, static-qualifier changes, or
source-level-only changes that have no ELF/DWARF representation.

**When would `--headers-dir` help?** If the library uses `visibility("hidden")` for internal
symbols in the headers, `--headers-dir` would filter them out and reduce false positives.
It does not improve detection of semantic changes.

---

### ABICC (abi-dumper workflow)

```
.so (v1, compiled with -g) ──► abi-dumper ──► v1.abi ──┐
                                                         ├──► abi-compliance-checker ──► report
.so (v2, compiled with -g) ──► abi-dumper ──► v2.abi ──┘
```

**Analysis basis:** DWARF — same as abidiff, but through Perl-based abi-dumper.  
**Header requirement:** Optional (pass `-public-headers` to filter to public API).  
**Compiler requirement:** None. Debug build (`-g`) required.

**Benchmark result: 20/30 scored (66%) — 12 cases ERROR/TIMEOUT:**
- `case09_cpp_vtable`: 122s timeout (abi-compliance-checker with complex vtable)
- `case28/30/31/32/33/34/35/36/40`: ERROR — abi-dumper fails on these C++ patterns
  (typedef chains, access levels, field renames, anon structs, etc.)

**Why ABICC(dump) accuracy is 66% but effective is only 48%:**  
Scoring 20/30 looks reasonable, but 12 out of 42 cases don't even run. For a fair comparison:
20/42 = **48%** effective accuracy. Meanwhile abicheck gets 42/42 = 100%.

---

### ABICC (XML / legacy mode)

```
v1.xml (headers dir + .so path) ──► abi-compliance-checker (invokes GCC internally) ──► report
v2.xml (headers dir + .so path) ──┘
```

**Analysis basis:** GCC-compiled AST from headers.  
**Header requirement:** Yes — must point to headers directory.  
**Compiler requirement:** Yes — **GCC only**. Clang and icpx are not supported.

**Why ABICC(xml) is slow and unreliable:**
1. **GCC invocation per case** — even for 5-line headers, GCC startup costs dominate
2. **Directory input causes redefinition errors** — if the descriptor's `<headers>` tag
   points to a directory, `abi-compliance-checker` includes ALL `.h` files found there,
   including duplicates from build subdirs → redefinition errors → wrong verdicts
3. **GCC bug #78040** — does not work correctly with GCC 6+ (warns on every run)
4. **`case16_inline_to_non_inline`**: reliably hits 120s timeout

**Our fix in PR #72:** Pass a specific header file path instead of a directory in
`<headers>`. This drops runtime from 120s → ~1s and fixes wrong verdicts.

**Benchmark result: 25/41 (60%) — 1 case TIMEOUT, rest scored.**

---

## Verdict vocabulary comparison

| Verdict | abicheck compare | abicheck compat | abidiff | ABICC |
|---------|:---:|:---:|:---:|:---:|
| `NO_CHANGE` | ✅ | ✅ | ✅ (exit 0) | ⚠️ reports 100% compat |
| `COMPATIBLE` | ✅ | ✅ | ✅ (exit 4) | ⚠️ reports 100% compat |
| `API_BREAK` | ✅ | ❌ not supported | ❌ | ❌ |
| `BREAKING` | ✅ | ✅ | ✅ (exit 8+) | ✅ |

`API_BREAK` = source-level break, binary-compatible. Example: parameter renamed,
access level changed, pure API contract violation with no ABI binary change.
Only `abicheck compare` can emit this verdict.

---

## Why abicheck achieves 100%

abicheck uses three independent analysis passes per comparison:

1. **ELF pass** — symbol table diff: detections visibility changes, SONAME, symbol binding,
   symbol version policy, added/removed/renamed exported symbols
2. **castxml pass** — Clang AST diff: detects noexcept, static qualifier, const qualifier,
   method-became-static, pure virtual additions, access level, parameter/return type changes
   that are invisible in ELF/DWARF
3. **DWARF cross-check** — type size/layout validation to catch pack/align changes that
   headers alone may not expose

Neither abidiff nor ABICC runs all three passes. abidiff has no AST (misses noexcept, static,
const). ABICC has no ELF pass (misses SONAME, visibility). ABICC(dump) has no AST
(same gaps as abidiff plus instability on complex C++).

---

## Benchmark summary (2026-03-11, 42 cases)

| Tool | Scored | Correct | Accuracy | Not scored | Time |
|------|:------:|:-------:|:--------:|:----------:|------|
| abicheck (compare) | 42 | 42 | **100%** | 0 | 212s |
| abicheck (compat)  | 42 | 40 | 95% | 0 — 2 API_BREAK n/a | 79s |
| abicheck (strict)  | 42 | 31 | 73% | 0 — 9 intentional FP | 78s |
| abidiff            | 42 | 11 | 26% | 0 | 2.5s |
| abidiff+headers    | 42 | 11 | 26% | 0 | 3.9s |
| ABICC(dump)        | 30 | 20 | 66% (48% of 42) | 12 ERROR/TIMEOUT | 294s |
| ABICC(xml)         | 41 | 25 | 61% (60% of 42) | 1 TIMEOUT | 445s |

See [benchmark_report.md](benchmark_report.md) for the full per-case table.

---

## Choosing the right tool

| Scenario | Recommended |
|----------|-------------|
| New CI pipeline, full accuracy | `abicheck compare` |
| Migrating from ABICC XML pipeline | `abicheck compat` |
| Strict gate (any addition = fail) | `abicheck compat -s --strict-mode api` |
| Debug build available, DWARF check | `abicheck compare` (castxml already better) |
| Quick ELF-only sanity check | `abidiff` (fast, 26% but catches symbol removals) |
