# Testing coverage and usefulness

## Overall summary (current state)

`abicheck` has a **useful and mature core test suite** for ABI-diff behavior, with strongest confidence in pure-Python comparison logic and report generation.

At the same time, coverage highlights a clear improvement area: code paths that orchestrate external tools (`cli.py`, `dumper.py`, deeper DWARF parsing paths) are less exercised than the core comparator.

In short:

- **Regression safety for diff/classification logic is strong**.
- **End-to-end tool orchestration confidence is moderate** and should be improved next.

## Test status and test types

The repository uses three complementary test tiers:

1. **Fast unit/component tests** (`pytest -m "not integration and not libabigail"`)
   - Validate internal logic and data/report transformations.
   - Intended as the primary CI gate for quick feedback.

2. **Integration tests** (`-m integration`)
   - Build/compare example C/C++ cases and validate end-to-end ABI outcomes.
   - Depend on system tools such as castxml and compilers.

3. **Parity tests** (`-m libabigail`)
   - Compare selected behavior against `abidiff` expectations.
   - Helps prevent semantic drift from industry-standard ABI checks.

## Current baseline

Measured locally with:

```bash
pytest --cov=abicheck --cov-report=term-missing
```

Baseline snapshot:

- **229 passed** (fast gate), **38 deselected** (integration/parity filtered).
- **Total branch-aware coverage (fast CI gate): 55%**.
- Strongly covered modules: `checker.py` (94%), `model.py` (91%), `suppression.py` (92%), `sarif.py` (94%).
- Major coverage gaps: `dwarf_metadata.py` (15%) and deeper `dumper.py` internals (11%) / `dwarf_advanced.py` (35%).
- **Phase 1 completed:** `cli.py` is now at **71%** with dedicated command tests.

## How good is the coverage?

Coverage quality is **good for core correctness**, but **not yet good enough for full-system confidence**:

- Good: high-signal modules that decide ABI verdicts are thoroughly tested.
- Weak: user-entry flows and tool-integration paths are under-tested and can hide runtime integration bugs.

So the current ~55% should be interpreted as:

- acceptable as a **tracked baseline**,
- insufficient as a **long-term target**.

## Coverage setup in CI

Coverage reporting is configured and enforced:

- `pyproject.toml` defines coverage scope (`source = ["abicheck"]`) and enables branch coverage.
- Main CI test job runs pytest with coverage output (`term-missing` + `coverage.xml`).
- CI enforces a floor (`--cov-fail-under=52`) and uploads `coverage.xml` as an artifact.

## Plan to extend coverage

### Phase 1 (completed)

1. **CLI tests via `click.testing.CliRunner`**
   - Cover `dump`, `compare`, `compat` happy paths and error paths.
   - Validate exit codes, key user-facing messages, and option validation.

2. **Dumper orchestration tests**
   - Mock castxml/ELF adapters and subprocess boundaries.
   - Cover success path, malformed tool output, missing binaries, and partial data handling.

3. **Raise floor incrementally after each merge**
   - Ratchet started: **48 -> 52** (done), next targets **56 -> 60**.

### Phase 2 (integration hardening)

4. Expand integration matrices across representative example cases (already present under `examples/`).
5. Add negative integration scenarios (bad ELF, missing symbols, broken headers).

### Phase 3 (deeper DWARF confidence)

6. Add focused tests for DWARF metadata extraction edge cases and advanced attributes.
7. Add fixture-based regression tests for known tricky compiler outputs.

## How to address coverage gaps practically

Recommended workflow for contributors:

1. **Pick one low-coverage module** (`cli.py` or `dumper.py`) per PR.
2. Add tests first for at least one happy path and one failure path.
3. Run local fast gate with coverage:

   ```bash
   pytest tests/ -v --tb=short -m "not integration and not libabigail" \
     --cov=abicheck --cov-report=term-missing --cov-report=xml --cov-fail-under=52
   ```

4. If branch coverage improves, bump CI floor by a small step in the same PR.
5. Keep integration/parity tests stable as semantic guardrails.

This approach avoids disruptive jumps while continuously increasing real confidence.
