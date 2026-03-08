# Testing coverage and usefulness

This project already has a broad test suite with three tiers of confidence:

1. **Fast unit and component tests** (`pytest -m "not integration and not libabigail"`) for core logic and report generation.
2. **Integration tests** (`-m integration`) that build example C/C++ cases and verify ABI outcomes end-to-end.
3. **Parity tests** (`-m libabigail`) that compare selected results against `abidiff` behavior.

## Current baseline

Measured locally with:

```bash
pytest --cov=abicheck --cov-report=term-missing
```

Result summary:

- **221 passed**, **38 skipped**.
- **Total branch-aware coverage: 49%**.
- Strongly covered modules: `checker.py` (96%), `model.py` (94%), `suppression.py` (93%), `sarif.py` (93%).
- Low-coverage/high-opportunity modules: `cli.py` (0%), `dumper.py` (0%), `dwarf_metadata.py` (21%), `dwarf_advanced.py` (40%).

## Usefulness assessment

The suite is **useful and meaningful** for regression safety in the ABI-diff core:

- The most risk-sensitive comparison/classification paths are heavily covered.
- Realistic example-based tests validate behavior across many ABI change scenarios.
- External-tool parity checks reduce semantic drift from industry tooling.

Main gap:

- Entrypoint/UX (`cli.py`) and snapshot extraction orchestration (`dumper.py`) have little direct coverage and could hide integration bugs.

## Code coverage setup

Coverage reporting is now configured in project tooling and CI:

- `pyproject.toml` defines coverage source scope (`abicheck`) and branch coverage.
- CI test job now runs pytest with coverage output (`term-missing` + `coverage.xml`).
- CI enforces a floor with `--cov-fail-under=48` and uploads `coverage.xml` as a workflow artifact.

## Recommended next targets

1. Add CLI tests using `click.testing.CliRunner` for `dump`, `compare`, and error/exit-code paths.
2. Add dumper tests by mocking castxml/ELF adapters to cover orchestration and failure handling.
3. Raise CI threshold gradually (e.g., 50 -> 55 -> 60) as these tests land.
