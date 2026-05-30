# Backlog

Near-term hardening items that are scoped but not yet implemented. This list
is deliberately small and concrete — strategic / architectural ideas live in
[Goals](goals.md), not here.

## MSVC + PDB end-to-end CI

**Status:** TODO (near-term, high priority)

**Problem.** abicheck implements PDB parsing (`pdb_parser.py`, `pdb_metadata.py`,
`pdb_utils.py`) and PE/COFF metadata extraction (`pe_metadata.py`), but the
Windows CI lane currently builds and compares with the **MinGW/GCC** toolchain
only. There is no end-to-end job that:

1. builds a fixture DLL **with MSVC** (`cl.exe` / `link.exe`),
2. emits a matching **PDB**,
3. runs `abicheck dump` + `abicheck compare` over the MSVC-produced artifacts,
4. asserts the verdict against a known-good ground truth.

This is the largest gap in the current platform-coverage story: the MSVC + PDB
path is exercised only by unit tests over synthetic/recorded inputs, never by a
real Microsoft toolchain in CI.

**Proposed work.**

- Add a `windows-msvc` CI lane (GitHub-hosted `windows-latest` runner, which
  ships MSVC build tools) that compiles a small C/C++ fixture with `cl.exe`,
  produces a `.dll` + `.pdb`, and runs an end-to-end compare.
- Seed 2–3 MSVC/PDB fixtures mirroring existing ELF example cases (e.g. a
  struct-size change and a function-removal) so the lane has ground truth.
- Gate the lane behind a marker (e.g. `@pytest.mark.msvc`) so default fast runs
  stay toolchain-free, mirroring the existing `integration` / `libabigail` /
  `abicc` marker discipline.
- If GitHub-hosted MSVC proves too constrained for the PDB scenarios we need,
  fall back to a scheduled self-hosted validation job.

**Risks.** Windows toolchain setup complexity; CI runtime/cost; PDB layout
differences across MSVC versions. Scope a spike before committing the lane.

## Other deferred roadmap items

These came out of an external roadmap review. They are recorded here so they are
not lost, but they are lower priority than the MSVC lane above and several are
strategy decisions rather than engineering tasks.

### Still open

| Item | Notes |
|------|-------|
| Parser/fuzzer safety checks | Add a fuzz/parser-safety harness for ELF/PE/Mach-O/XML/YAML inputs (the security docs already warn that untrusted binaries deserve sandboxing). |

### Done

These were implemented after the review (alongside the canonical
`evidence_tier` work):

| Item | Where |
|------|-------|
| Versioned JSON Schema file + stability guarantee | `abicheck/schemas/compare_report.schema.json` + `abicheck.schemas` module; every report emits `report_schema_version`; documented in `docs/user-guide/output-formats.md`; validated by `tests/test_report_schema.py`. |
| `abicompat` / `abipkgdiff` parity lanes | `tests/test_abicompat_parity.py`, `tests/test_abipkgdiff_parity.py`; wired into the `libabigail-parity` CI lane. |
| Package-format test matrix | `tests/test_package_extractor_matrix.py` — real round-trip extraction + a unified malicious-payload matrix for the stdlib formats. |
| Release-pinned benchmark artifacts | `scripts/benchmark_comparison.py` emits `benchmark_report.json` (versions, git commit, ground-truth digest, accuracy); `publish.yml` attaches it to each GitHub Release. |
