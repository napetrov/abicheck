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
1. Add `visibility` field to `Function`/`Variable` model (values: DEFAULT,
   PROTECTED, HIDDEN, INTERNAL)
2. Extend `elf_metadata.py` to populate visibility from `st_other` byte
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
**Fix:**
1. Split detection: if function is in old ELF `.dynsym` and missing from new
   `.dynsym`, this is a binary-level break regardless of header presence
2. Rename or add: `FUNC_REMOVED_FROM_BINARY` with BREAKING verdict
3. Keep `func_removed_elf_only` for the case where function was never in headers
   (truly ELF-only symbol that may be internal)
4. Policy: `strict_abi` → BREAKING, `plugin_abi` → COMPATIBLE_WITH_RISK
**Test:** Update case59 ground truth, add unit test with both scenarios
**Effort:** Medium (requires careful distinction between "header-declared but
ELF-removed" vs "ELF-only internal symbol removed")

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
| `abicc_replay` | ABICC RegTests replay | Gated (heavy-parity-gate) |
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
