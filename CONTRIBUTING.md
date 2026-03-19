# Contributing to abicheck

Thank you for your interest in contributing!

## Requirements

- Python >= 3.10
- `git`
- Linux for full test suite: `castxml` + `g++` or `clang++` (ELF/DWARF/header tests)
- Windows/macOS: unit tests and PE/Mach-O tests run without extra system dependencies

## Setup

### Option A: conda-forge (recommended)

```bash
# Create a development environment with all dependencies
conda create -n abicheck-dev python=3.10 castxml -c conda-forge
conda activate abicheck-dev

git clone https://github.com/napetrov/abicheck.git
cd abicheck
pip install -e ".[dev]"
```

### Option B: pip + system castxml

```bash
# Install castxml separately (Ubuntu/Debian)
sudo apt install castxml g++

git clone https://github.com/napetrov/abicheck.git
cd abicheck
pip install -e ".[dev]"
```

## Testing

abicheck uses a layered testing strategy with `pytest`.

### Quick tests (default CI gate)

Fast unit and component tests — no external tools required:

```bash
pytest tests/ -v --tb=short \
  -m "not integration and not libabigail and not abicc" \
  --cov=abicheck --cov-report=term-missing
```

### Integration tests

Requires `castxml` and `gcc`/`g++`:

```bash
pytest tests/ -v -m "integration"
```

### Full suite (all external tools)

Requires `castxml`, `abidiff`, and `abi-compliance-checker`:

```bash
pytest tests/ --cov=abicheck --cov-report=term-missing
```

### Test markers

| Marker | Requirements | What it covers |
|--------|-------------|----------------|
| (default) | Python only | Core logic, report serialization, suppression rules, CLI |
| `integration` | castxml, gcc/g++ | Real toolchain interactions, ELF/DWARF parsing |
| `libabigail` | abidiff, gcc/g++ | libabigail parity tests |
| `abicc` | abi-compliance-checker, gcc/g++ | ABICC compatibility parity tests |

### Example validation

Run the 63 example cases against ground truth:

```bash
pytest tests/ -v -k "example" --tb=short
```

Or use the benchmark script:

```bash
python3 scripts/benchmark_comparison.py --skip-abicc
```

## Code style

```bash
ruff check abicheck/ tests/
mypy abicheck/
```

Both must pass before submitting a PR. CI enforces both.

## PR workflow

1. Branch: `git checkout -b feat/<name>` or `fix/<name>`
2. Make changes, add tests
3. `ruff check` + `mypy` + `pytest` all green locally
4. Push and open PR — CodeRabbit will review automatically
5. Address all review comments before merge
6. CI must be fully green (all checks)

## Commit style

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add --policy-file support
fix: correct CFA register extraction for epilogue frames
docs: update README with v0.1 requirements
test: add coverage for PolicyFile.compute_verdict
```

## Adding a new ChangeKind

1. Add the kind to `ChangeKind` enum in `abicheck/checker_policy.py`
2. Place it in exactly one of `BREAKING_KINDS`, `API_BREAK_KINDS`, `COMPATIBLE_KINDS`, or `RISK_KINDS`
3. Implement detection in the relevant detector in `abicheck/`
4. Add a unit test in `tests/`
5. Document in `docs/` if user-visible

## Questions

Open an [issue](https://github.com/napetrov/abicheck/issues) or discussion.
