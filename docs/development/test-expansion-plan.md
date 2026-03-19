# Test Expansion Plan & Specification

> Created: 2026-03-19
> Status: PROPOSED
> Scope: Expand abicheck's validation surface using external test corpora
>   (libabigail, ABICC) and close documented detection gaps.

---

## 1. Motivation

abicheck currently has strong test infrastructure:

- 63 example cases with ground truth verdicts
- 690+ unit tests covering all 118 ChangeKinds
- 93%+ code coverage
- 100% mapping of ABICC's 66 de-duplicated RegTests.pm scenarios

However, three validation dimensions remain untapped:

1. **External test binaries** — libabigail ships pre-compiled ELF pairs with
   expected diffs; we don't consume them.
2. **End-to-end ABICC scenario replay** — we map ABICC patterns conceptually but
   don't feed identical source snippets to both tools and diff verdicts
   systematically.
3. **Real-world library pairs** — synthetic cases may miss emergent complexity
   (macro-heavy headers, C++ template forests, large vtables, versioned symbols).

Additionally, 14 example cases have documented `known_gap` entries where abicheck
returns an incorrect or incomplete verdict.

---

## 2. Goals & Non-Goals

### Goals

| ID | Goal | Success Metric |
|----|------|----------------|
| T1 | Import libabigail test binaries as regression fixtures | ≥20 ELF pairs importable; verdicts match or diverge with documented reason |
| T2 | Systematic ABICC RegTests.pm replay | All 66 de-duplicated scenarios produce matching or intentionally-divergent verdicts |
| T3 | Real-world library pair smoke tests | ≥3 library pairs (e.g., zlib, libpng, OpenSSL) with stable verdicts |
| T4 | Close HIGH-impact known gaps | 4 gaps addressed: case51 (visibility), case58 (var_removed), case59 (inline→BREAKING), case61 (var_added) |
| T5 | Close MEDIUM-impact known gaps | 2 gaps addressed: case54 (reserved field), case62 (opaque struct) |
| T6 | Improve macOS headerless coverage | Documented which macOS gaps require castxml vs which can use Mach-O metadata |

### Non-Goals

- Kernel module ABI (BTF/CTF) — out of scope
- Cross-architecture (32→64 bit) diffing
- Closed-source PDB-only Windows libraries (no header access)
- Achieving 100% verdict match with libabigail/ABICC — intentional divergences
  are acceptable when documented

---

## 3. Work Streams

### WS-1: libabigail Test Binary Import

**What:** Extract ELF binary pairs from libabigail's `tests/data/` tree and run
them through `abicheck compare`.

**Why:** Pre-compiled binaries exercise the ELF parser and DWARF reader with
artifacts produced by a different build of gcc/clang — surfaces assumptions about
compiler-specific DWARF layout.

**Spec:**

1. **Curate binary pairs.** Clone libabigail source (tag `libabigail-2.6` or
   latest stable). Identify subdirectories under `tests/data/` containing paired
   `.so` files with corresponding expected output (XML or text diff).

2. **Create fixture directory.** Store curated pairs under
   `tests/fixtures/libabigail/` with the following layout:
   ```
   tests/fixtures/libabigail/
   ├── manifest.json          # metadata: origin tag, case name, expected verdict
   ├── test-fn-removed/
   │   ├── old.so
   │   ├── new.so
   │   └── expected.txt       # libabigail's expected exit code + summary
   ├── test-type-size-change/
   │   ├── old.so
   │   ├── new.so
   │   └── expected.txt
   └── ...
   ```

3. **Write parametrized test.** New file `tests/test_libabigail_corpus.py`:
   - Discovers cases from `manifest.json`
   - Runs `abicheck compare old.so new.so` (ELF-only, no headers)
   - Compares verdict against manifest expectation
   - Categories: `parity` (must match), `stricter` (abicheck finds more),
     `known_divergence` (documented reason)
   - Marker: `@pytest.mark.libabigail_corpus`

4. **CI integration.** Add to `ci.yml` as an optional job gated by
   `heavy-parity-gate` condition (same pattern as existing parity jobs).

5. **Size budget.** Strip debug sections from fixture `.so` files where DWARF is
   not needed for the test scenario. Target: <10 MB total for fixtures.

**Acceptance criteria:**
- ≥20 binary pairs imported
- All verdicts documented in manifest.json
- CI job passes (parity + known divergences marked)

---

### WS-2: ABICC RegTests.pm Systematic Replay

**What:** Extract the ~66 de-duplicated C/C++ source snippets from ABICC's
`RegTests.pm`, compile them, and run both abicheck and ABICC against the
artifacts.

**Why:** Our current mapping (in `abicc-test-coverage-comparison.md`) is
conceptual — we verified ChangeKind existence, not verdict equivalence on
identical input. This closes that gap.

**Spec:**

1. **Extract scenarios.** Parse ABICC's `RegTests.pm` (Perl data structures) to
   extract `{scenario_name, v1_header, v2_header, v1_source, v2_source, lang}`
   tuples. Write a one-time Python extraction script
   `scripts/extract_abicc_regtests.py` that produces JSON:
   ```json
   [
     {
       "name": "AddedVirtualMethod",
       "lang": "cpp",
       "v1_header": "struct Base { virtual int foo(); };",
       "v2_header": "struct Base { virtual int foo(); virtual int bar(); };",
       "v1_source": "...",
       "v2_source": "...",
       "abicc_bin_verdict": "BREAKING",
       "abicc_src_verdict": "BREAKING"
     },
     ...
   ]
   ```

2. **Create test file.** `tests/test_abicc_regtest_replay.py`:
   - Loads extracted JSON scenarios
   - Compiles v1/v2 `.so` libraries from source+header
   - Runs `abicheck compare` with headers
   - Optionally runs `abi-compliance-checker` if available
   - Compares verdicts: parity / abicheck-stricter / divergence
   - Marker: `@pytest.mark.abicc` (requires gcc/g++, castxml)

3. **Expected outcome categories:**

   | Category | Count (est.) | Handling |
   |----------|-------------|----------|
   | Full parity | ~50 | Assert match |
   | abicheck stricter | ~10 | Assert abicheck ≥ ABICC severity |
   | Intentional divergence | ~6 | `xfail` with reason |

4. **Maintenance.** The extracted JSON is checked in and versioned. If ABICC
   updates RegTests.pm, re-run the extraction script. Pin to ABICC version in
   manifest.

**Acceptance criteria:**
- All 66 scenarios extracted and compiled
- ≥60/66 produce matching or stricter verdicts
- ≤6 documented divergences

---

### WS-3: Real-World Library Pair Smoke Tests

**What:** Compare actual released versions of popular C/C++ libraries to validate
that abicheck produces sensible verdicts on production artifacts.

**Why:** Synthetic tests use minimal source; real libraries stress the parser
with large symbol tables, complex type hierarchies, macro-heavy headers, and
compiler-specific DWARF.

**Spec:**

1. **Library selection criteria:**
   - Widely used (validates real-world relevance)
   - Known ABI policy (helps verify verdicts)
   - Available as binary packages (avoids build complexity)
   - Mix of C and C++ libraries

2. **Proposed library pairs:**

   | Library | v1 | v2 | Expected | Rationale |
   |---------|----|----|----------|-----------|
   | zlib | 1.2.13 | 1.3.1 | COMPATIBLE | Stable ABI, only additions |
   | libpng | 1.6.39 | 1.6.43 | COMPATIBLE | Patch-level, stable ABI |
   | OpenSSL | 1.1.1w | 3.0.13 | BREAKING | Major version, massive API churn |
   | libcurl | 8.4.0 | 8.6.0 | COMPATIBLE | Stable SONAME within major |
   | glib-2.0 | 2.76 | 2.80 | COMPATIBLE | Strong ABI stability policy |

3. **Test infrastructure.** `tests/test_realworld_smoke.py`:
   - Marker: `@pytest.mark.slow` (may take minutes to download/extract)
   - Downloads `.deb` or `.rpm` packages from archive.ubuntu.com or vault.centos.org
   - Extracts `.so` files and development headers from `-dev` packages
   - Runs `abicheck compare` with headers
   - Asserts high-level verdict (BREAKING vs COMPATIBLE)
   - Caches downloads in `tests/.cache/realworld/` (gitignored)

4. **Snapshot mode for CI.** To avoid network dependency in CI:
   - First run downloads + dumps JSON snapshots
   - Subsequent runs compare snapshots (no network needed)
   - Store snapshots in `tests/fixtures/realworld/` (small JSON, <1 MB each)

5. **CI integration.** Weekly scheduled workflow (`test-realworld.yml`) rather
   than per-PR. Failures create issues but don't block merges.

**Acceptance criteria:**
- ≥3 library pairs with stable verdicts
- No crashes or unhandled exceptions on real-world input
- Verdicts match known ABI policy for each library

---

### WS-4: Close HIGH-Impact Detection Gaps

These gaps affect real-world binary compatibility detection and should be
addressed in the checker/dumper code.

#### WS-4a: ELF visibility tracking (case51_protected_visibility)

**Gap:** DEFAULT→PROTECTED visibility change not detected.
**Root cause:** `elf_metadata.py` reads `st_other` but `checker.py` doesn't diff
visibility attributes beyond DEFAULT/HIDDEN.
**Fix:**
1. Add `elf_visibility` field to `Function`/`Variable` model (values: DEFAULT,
   PROTECTED, HIDDEN, INTERNAL) — kept separate from the existing `visibility`
   field which tracks API-level provenance (PUBLIC/HIDDEN/ELF_ONLY) and drives
   symbol filtering in `checker.py` (see m4 in Appendix A.3)
2. Extend `elf_metadata.py` to populate `elf_visibility` from `st_other` byte
3. Add detector in `checker.py`: `SYMBOL_VISIBILITY_CHANGED` (new ChangeKind if
   needed, or extend `FUNC_VISIBILITY_CHANGED`)
4. Verdict: COMPATIBLE (interposition policy concern, not binary break)
**Test:** Update case51 ground truth expected→actual, add unit test
**Effort:** Small

#### WS-4b: Global variable addition/removal in ELF-only mode (case58, case61)

**Gap:** ELF-only mode doesn't track global variable symbols.
**Root cause:** `dumper.py` ELF-only path focuses on `STT_FUNC` symbols; `STT_OBJECT`
symbols are filtered out without headers.
**Fix:**
1. In `dumper.py` ELF-only fallback, also collect `STT_OBJECT` symbols from
   `.dynsym` as `Variable` entries
2. Apply same compiler-internal filtering as for functions
3. Ensure `checker.py` already handles `VAR_REMOVED`/`VAR_ADDED` (it does)
**Test:** Update case58/case61 ground truth, add integration test
**Effort:** Small

#### WS-4c: func_removed_elf_only → BREAKING elevation (case59)

**Gap:** When a function disappears from `.dynsym` but remains declared in headers
(moved to `static inline`), verdict is COMPATIBLE instead of BREAKING.
**Root cause:** `func_removed_elf_only` ChangeKind has COMPATIBLE default verdict.
**Fix (mixed-mode only — see B2 in Appendix A.1):**

In pure ELF-only mode, all functions carry `Visibility.ELF_ONLY` (`model.py:36`,
`dumper.py:1134-1138`) and the checker selects `FUNC_REMOVED_ELF_ONLY` vs
`FUNC_REMOVED` from that single provenance bit (`checker.py:226-230`). There is
no persisted signal for "still declared in headers but removed from `.dynsym`",
so the header-vs-ELF distinction is **not implementable in pure ELF-only mode**.

Therefore:
1. **Mixed-mode (headers available):** Add `FUNC_REMOVED_FROM_BINARY` ChangeKind
   with BREAKING default. Emit it when a function is present in old `.dynsym` and
   absent from new `.dynsym`, **and** the function was header-declared (i.e.,
   `visibility != ELF_ONLY`). This is a binary break: consumers' PLT entries will
   fail to resolve at load time even though headers still declare the function.
2. **Pure ELF-only mode:** Retain `func_removed_elf_only` as-is (COMPATIBLE
   default). Without headers, we cannot distinguish intentionally-public from
   accidentally-leaked symbols, so a blanket elevation would produce excessive
   false positives (see M8: LTO and `-fvisibility=hidden` rebuilds).
3. **Policy overrides:**
   - `strict_abi` → elevates `func_removed_elf_only` to BREAKING even in
     ELF-only mode (user opts into strictness)
   - `plugin_abi` → keeps COMPATIBLE_WITH_RISK for both modes
**Test:** Update case59 ground truth (mixed-mode scenario), add unit tests for:
  (a) mixed-mode removal → FUNC_REMOVED_FROM_BINARY (BREAKING),
  (b) ELF-only removal → func_removed_elf_only (COMPATIBLE),
  (c) ELF-only removal + strict_abi policy → BREAKING
**Effort:** Medium

#### WS-4d: Visibility change detection enhancement

**Gap:** Broader visibility changes (DEFAULT→HIDDEN already tracked, but
PROTECTED→DEFAULT, INTERNAL→DEFAULT, etc. are not).
**Fix:** Covered by WS-4a. Ensure all `st_other` transitions are captured.

---

### WS-5: Close MEDIUM-Impact Detection Gaps

#### WS-5a: Reserved field recognition (case54_used_reserved_field)

**Gap:** Renaming `__reserved1`/`__reserved2` to real field names at same offset
triggers `struct_field_removed`.
**Root cause:** Name-based matching treats rename as remove+add.
**Fix:**
1. Add heuristic in `checker.py` field diff: if old field name matches
   `__reserved\d+` or `_pad\d*` or `__unused\d*`, and new field at same offset
   has same size, classify as `USED_RESERVED_FIELD` (already exists as
   ChangeKind) instead of `TYPE_FIELD_REMOVED` + `TYPE_FIELD_ADDED`
2. Verdict: COMPATIBLE (layout preserved)
**Test:** Update case54 ground truth, add unit test
**Effort:** Small

#### WS-5b: Opaque struct detection (case62_type_field_added_compatible)

**Gap:** Field added to opaque struct (accessed only via pointer) triggers
`struct_size_changed` even though callers never allocate/copy the struct.
**Root cause:** Checker has no concept of struct opacity at the call-site level.
**Fix:**
1. In `checker.py`, after detecting `TYPE_SIZE_CHANGED` or `TYPE_FIELD_ADDED`,
   check whether all references to this type in exported function signatures
   are pointer-only (no by-value params, no by-value returns, no sizeof usage)
2. If pointer-only: downgrade to `TYPE_FIELD_ADDED_COMPATIBLE`
3. Requires: cross-referencing type usage across all exported functions
4. Limitation: cannot determine opacity for types used as struct fields in other
   exported structs (transitive analysis needed)
**Test:** Update case62 ground truth, add unit test with pointer-only vs by-value
**Effort:** Medium-Large (cross-type analysis)

---

### WS-6: macOS Headerless Coverage Documentation

**What:** Audit all macOS `known_gap` entries and document which require castxml
(inherent limitation) vs which could be detected via Mach-O metadata improvements.

**Spec:**

1. **Audit matrix:**

   | Case | Gap | Fixable via Mach-O? | Requires castxml? |
   |------|-----|--------------------|--------------------|
   | case42 (alignment) | Type-level | No | Yes |
   | case55 (type kind) | struct→union | No | Yes |
   | case56 (packing) | Layout | No | Yes |
   | case57 (enum size) | Underlying type | No | Yes |
   | case60 (base class) | MI layout | No | Yes |

2. **Document in `docs/concepts/limitations.md`** a new section:
   "### macOS / Mach-O headerless mode limitations"
   explaining that type-level analysis requires castxml + headers and Mach-O
   binary-only mode is restricted to symbol-level checks.

3. **Add castxml availability detection to macOS integration tests** so that
   when castxml IS available, these cases are expected to pass.

**Effort:** Small (documentation + conditional test logic)

---

## 4. Implementation Order & Dependencies

```
Phase 1 (Quick wins — no external dependencies):
  WS-4a  ELF visibility tracking
  WS-4b  Global var ELF-only mode
  WS-5a  Reserved field heuristic
  WS-6   macOS documentation

Phase 2 (Moderate — requires code changes):
  WS-4c  func_removed_elf_only elevation
  WS-5b  Opaque struct detection

Phase 3 (Test infrastructure — requires external data):
  WS-1   libabigail binary import
  WS-2   ABICC RegTests replay

Phase 4 (Long-running — network + packages):
  WS-3   Real-world library pairs
```

Phase 1 items are independent and can be parallelized. Phase 2 depends on Phase 1
being stable (same files modified). Phase 3 and 4 are independent of Phases 1-2
and can start in parallel if resources allow.

---

## 5. New Files & Infrastructure

| File | Purpose | Phase |
|------|---------|-------|
| `tests/fixtures/libabigail/manifest.json` | Curated binary pair metadata | WS-1 |
| `tests/fixtures/libabigail/*.so` | Pre-compiled ELF pairs | WS-1 |
| `tests/test_libabigail_corpus.py` | Parametrized libabigail fixture tests | WS-1 |
| `scripts/extract_abicc_regtests.py` | One-time ABICC scenario extractor | WS-2 |
| `tests/fixtures/abicc_regtests.json` | Extracted ABICC scenarios | WS-2 |
| `tests/test_abicc_regtest_replay.py` | Systematic ABICC replay tests | WS-2 |
| `tests/test_realworld_smoke.py` | Real-world library pair tests | WS-3 |
| `tests/fixtures/realworld/*.json` | Cached snapshots for CI | WS-3 |
| `.github/workflows/test-realworld.yml` | Weekly smoke test workflow | WS-3 |

---

## 6. New Pytest Markers

| Marker | Purpose | CI Job |
|--------|---------|--------|
| `libabigail_corpus` | libabigail binary fixture tests | Gated (heavy-parity-gate) |
| `abicc` | ABICC RegTests replay (extends existing abicc-parity job) | Gated (heavy-parity-gate) |
| `realworld` | Real-world library pairs | Weekly scheduled |

Register in `conftest.py` and `pyproject.toml`.

---

## 7. Ground Truth Updates

After implementing detection fixes, update `examples/ground_truth.json`:

| Case | Current `known_gap` | After Fix |
|------|-------------------|-----------|
| case51 | "ELF visibility not tracked" | Remove gap, expected=COMPATIBLE, actual=COMPATIBLE |
| case54 | "reserved field rename → BREAKING" | Remove gap, expected=COMPATIBLE, actual=COMPATIBLE |
| case58 | "ELF-only no var tracking" | Remove gap, expected=BREAKING, actual=BREAKING |
| case59 | "func_removed_elf_only not elevated" | Remove gap, expected=BREAKING, actual=BREAKING |
| case61 | "ELF-only no var tracking" | Remove gap, expected=COMPATIBLE, actual=COMPATIBLE |
| case62 | "opaque struct not recognized" | Remove gap, expected=COMPATIBLE, actual=COMPATIBLE |

**Net effect:** 6 known_gap entries removed (14→8 remaining, all macOS/platform gaps).

---

## 8. CI Impact

| Change | Runtime Impact | Gate Impact |
|--------|---------------|-------------|
| WS-1 (libabigail corpus) | +2 min (gated job) | Non-blocking |
| WS-2 (ABICC replay) | +3 min (gated job) | Non-blocking |
| WS-3 (real-world) | +5 min (weekly only) | Non-blocking |
| WS-4/5 (gap fixes) | +10s (new unit tests) | Blocking (unit gate) |
| WS-6 (docs) | 0 | None |

Total impact on per-PR CI: ~10 seconds (unit tests only).
Heavy parity jobs add ~5 min but run conditionally.

---

## 9. Risk Assessment

| Risk | Mitigation |
|------|------------|
| libabigail test binaries too large for git | Strip debug sections; use git-lfs if >5 MB total |
| ABICC RegTests.pm format changes | Pin to specific ABICC version; extraction script is idempotent |
| Real-world package downloads flaky | Cache snapshots; weekly schedule tolerates transient failures |
| Opaque struct detection false negatives | Conservative: only downgrade when ALL references are pointer-only |
| Reserved field heuristic false positives | Strict pattern match: `__reserved\d+`, `_pad\d*`, `__unused\d*` only |
| func_removed elevation breaks existing users | Policy-gated: only BREAKING under `strict_abi`; COMPATIBLE_WITH_RISK under `plugin_abi` |

---

## 10. Success Criteria (Summary)

| Metric | Current | Target |
|--------|---------|--------|
| Example cases with known_gap | 14 | ≤8 |
| ABICC scenario parity (verified) | Conceptual 66/66 | Empirical 60+/66 |
| libabigail binary pair coverage | 0 | ≥20 |
| Real-world library pairs tested | 0 | ≥3 |
| Code coverage | 93% | ≥93% (no regression) |
| Unit test count | 690+ | 720+ |

---

## Appendix A: Review Panel Findings

> Reviewed 2026-03-19 by four specialist reviewers: Test Architecture, ABI Domain
> Expert, CI/DevOps, and Implementation Feasibility. Findings below are
> consolidated and cross-referenced.

### A.1 BLOCKERS (must resolve before implementation)

**B1. CI marker exclusion gap** *(Test Architecture)*
New markers (`libabigail_corpus`, `realworld`) are NOT excluded
from the unit-test `-m` filter in `ci.yml`. Tests will collect and fail in the
fast gate unless the filter is updated to:
`not integration and not libabigail and not libabigail_corpus and not abicc and not realworld`
Also add `conftest.py` skip-if-unavailable hooks for all three markers.

**B2. WS-4c approach infeasible in pure ELF-only mode** *(Feasibility)*
The plan proposes distinguishing "header-declared but ELF-removed" from "ELF-only
internal symbol removed." But in ELF-only mode, ALL functions are marked
`ELF_ONLY` because there are no headers — the distinction is impossible.
**Resolution options:**
(a) Elevate ALL `func_removed_elf_only` to BREAKING (simple but noisy),
(b) Use a heuristic for "looks like public API" (no leading underscore, no
compiler-internal prefix, exported in `.dynsym`),
(c) Only apply the elevation when headers ARE available (mixed mode), keeping
ELF-only mode as-is.
Recommend option (c) as safest; option (b) as stretch.

**B3. Network fallback undefined for WS-3** *(CI/DevOps)*
No retry logic, no mirror strategy, no first-run bootstrapping for snapshot mode.
**Resolution:** Commit initial snapshot JSONs from day one. Use
`ABICHECK_REALWORLD_DOWNLOAD=1` env var to refresh. Add 3-attempt retry with
exponential backoff. Use `snapshot.ubuntu.com` as secondary mirror.

**B4. Symbol version removal not validated** *(ABI Domain)*
Removing a symbol version (e.g., `foo@@LIBFOO_1.0` → only `foo@@LIBFOO_2.0`) is
a hard binary break (consumers get "version not found" at load time).
`SYMBOL_VERSION_DEFINED_REMOVED` ChangeKind exists but is not validated in the
gap-closure plan or ground truth matrix. Must be explicitly tested in WS-3
real-world tests (glibc, libstdc++ use heavy versioning).

### A.2 MAJOR Issues (significant rework needed)

**M1. Git-LFS required from the start** *(Test Architecture + CI/DevOps)*
Binary `.so` fixtures will permanently bloat repo history. Add `.gitattributes`
rule before committing any binary:
`tests/fixtures/libabigail/*.so filter=lfs diff=lfs merge=lfs -text`
Stripping DWARF from fixtures contradicts WS-1's goal of testing DWARF reader.
**Resolution:** Keep DWARF in fixtures that test DWARF paths; strip only for
symbol-level-only tests. Budget realistically for 15-20 MB with LFS.

**M2. Marker naming inconsistency** *(Test Architecture + CI/DevOps)*
**Resolved:** WS-2 and Section 6 now both use `@pytest.mark.abicc`, extending the
existing `abicc-parity` CI job (`ci.yml:200-217`). The previously conflicting
`abicc_replay` name has been removed from the marker table.

**M3. WS-5a: Reserved field detector already exists** *(Feasibility)*
`_diff_reserved_fields()` already exists at `checker.py:2398-2436` with regex
`^_{0,2}(reserved|pad|padding|spare|unused)\d*$`. The real bug is that
`_diff_type_fields()` ALSO fires `TYPE_FIELD_REMOVED` + `TYPE_FIELD_ADDED` for
the same rename, and those BREAKING verdicts override the COMPATIBLE
`USED_RESERVED_FIELD`.
**Resolution:** Rewrite WS-5a as: "Integrate reserved-field check INTO
`_diff_type_fields()` so it emits `USED_RESERVED_FIELD` INSTEAD OF (not in
addition to) `TYPE_FIELD_REMOVED` + `TYPE_FIELD_ADDED`." Effort: Minimal.

**M4. WS-5a pattern list too narrow** *(ABI Domain)*
Real-world reserved fields also use: `pad` (no digit), `spare`, `mbz`/`_mbz`
("must be zero"), `__pad\d*`, `_reserved` (no trailing digit), `__fill`,
`filler`. The plan's pattern will miss many real libraries (kernel UAPI, perf,
io_uring, KVM, DRM headers).
**Resolution:** Broaden to case-insensitive substring match for `reserved`,
`pad`, `spare`, `unused`, `mbz`, `fill` AND require same offset + same size.

**M5. WS-5a: Reserved field size change not addressed** *(ABI Domain)*
If `uint32_t __reserved` → `uint64_t real_field` at same offset but different
size, this is BREAKING (shifts subsequent fields). Plan must explicitly require
offset AND size match; if only offset matches but size differs, remain
`TYPE_FIELD_REMOVED` + `TYPE_FIELD_ADDED`.

**M6. WS-5b: Opaque struct analysis harder than described** *(Feasibility + ABI Domain)*
- String-based type matching (`"const Foo*"`) is fragile — no structured type
  references in the model. Must handle qualifiers, typedefs, namespaces.
- `TYPE_SIZE_CHANGED` has no compatible variant; a new ChangeKind needed.
- `sizeof()` in macros is undetectable by pointer-only analysis (castxml doesn't
  surface macro-level sizeof usage).
- Transitive by-value embedding MUST block the downgrade: if `struct Session` is
  embedded by-value in `struct Context` which is in public APIs, then `Session`
  growing is BREAKING even if `Session*` is pointer-only in direct API functions.
**Resolution:** Start with simpler heuristic: if type has `is_opaque=True` in old
version and gains fields in new version, it was always opaque to consumers →
COMPATIBLE. This avoids cross-reference analysis entirely. Add transitive check
as a later enhancement.

**M7. WS-4b: TLS variables omitted** *(ABI Domain)*
Plan only mentions `STT_OBJECT` but `STT_TLS` symbols (thread-local storage) are
also ABI-relevant. Removing a TLS variable is a binary break. Also consider COPY
relocation implications for variables with changed `st_size`.

**M8. WS-4c: LTO and -fvisibility=hidden false positives** *(ABI Domain)*
LTO can eliminate symbols that were in `.dynsym` of individual `.o` files.
`-fvisibility=hidden` with `__attribute__((visibility("default")))` on select
symbols means many functions legitimately disappear between builds. Elevating all
removals to BREAKING will produce false positives.
**Resolution:** Only elevate when the symbol was in `.dynsym` of BOTH old and new
libraries' *dynamic* symbol table (not static). If it was in old `.dynsym` but
absent from new `.dynsym`, that IS a break regardless of LTO.

**M9. CI cache strategy** *(CI/DevOps)*
`tests/.cache/realworld/` is useless in ephemeral CI runners. Need
`actions/cache` keyed on library version manifest hash. Add `tests/.cache/` to
root `.gitignore`.

**M10. WS-4a: Visibility verdict needs nuance** *(ABI Domain)*
- DEFAULT→PROTECTED: should be `COMPATIBLE_WITH_RISK` (breaks interposition;
  e.g., `LD_PRELOAD` overrides stop working, which some tools depend on)
- PROTECTED→HIDDEN or DEFAULT→HIDDEN: BREAKING (symbol no longer resolvable)
- HIDDEN→DEFAULT: COMPATIBLE (more visible)
Need a full visibility transition matrix, not a blanket COMPATIBLE verdict.

### A.3 MINOR Issues

**m1.** License file needed for redistributed libabigail fixtures (LGPL-3.0+).
**m2.** `realworld` tests should carry BOTH `@pytest.mark.realworld` and
`@pytest.mark.slow` so `-m "not slow"` continues to exclude all expensive tests.
**m3.** CI job runtime estimates (+2/+3 min) undercount `apt-get install` setup.
**m4.** `Visibility` enum in `model.py` (PUBLIC/HIDDEN/ELF_ONLY) is API-level,
not ELF `st_other`-level. Use separate `elf_visibility: str` field instead.
**m5.** WS-4b: Same `STT_OBJECT` omission exists in Mach-O and PE fallback paths
(dumper.py ~lines 1126-1147 and 1219-1234). Plan only addresses ELF.
**m6.** `testing.md` says `--cov-fail-under=52` but CI enforces `80` — stale.
**m7.** AArch64 `STO_AARCH64_VARIANT_PCS` in `st_other` is architecture-specific
and ignored. Low priority but worth noting.
**m8.** Flexible array members: struct with trailing `char data[]` is always
pointer-accessed but `sizeof` is meaningful for fixed portion. Opaque struct
heuristic should not downgrade such types.

### A.4 SUGGESTIONS

**S1.** Add manifest schema validation test for early error detection.
**S2.** Use `xfail(strict=True)` for `known_divergence` cases — auto-detects fixes.
**S3.** Combine WS-1/WS-2 into existing parity CI jobs to avoid duplicate setup.
**S4.** Register all markers canonically in `pyproject.toml`; remove redundant
`config.addinivalue_line` calls from `conftest.py`.
**S5.** Better real-world library choices: replace libpng patch-level pair (boring
diff) with **libsystemd** (opaque struct patterns — perfect for WS-5b validation)
or **Qt 5→6** (massive C++ vtable/MI stress test).
**S6.** Add **libicu** (73→74) to test symbol-suffix renaming convention.
**S7.** Coverage metric: 93% is local measurement, CI enforces 80%. Clarify which
is the target in Section 10.

### A.5 Effort Estimate Corrections

| Work Stream | Plan Estimate | Reviewer Consensus | Notes |
|-------------|---------------|--------------------|-------|
| WS-4a | Small | **Small** | Plumbing exists; add visibility transition matrix |
| WS-4b | Small | **Small** | ~10 lines; also fix Mach-O/PE paths + add STT_TLS |
| WS-4c | Medium | **Needs redesign** | Use option (c): only elevate in mixed mode |
| WS-5a | Small | **Minimal** | Detector exists; fix is suppressing duplicate emissions |
| WS-5b | Medium-Large | **Large** | Start with is_opaque heuristic instead |
