# Contributing to abicheck

Thank you for your interest in contributing!

## Requirements

- Linux (ELF/DWARF tooling is Linux-specific)
- Python ≥ 3.10
- `castxml` + `g++` or `clang++`
- `git`

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

## Running tests

```bash
# Unit + integration tests (no external tools required)
python -m pytest tests/ -m "not integration and not libabigail and not abicc"

# Full suite (requires castxml, abidiff, abi-compliance-checker)
python -m pytest tests/
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
2. Place it in one of `BREAKING_KINDS`, `API_BREAK_KINDS`, or `COMPATIBLE_KINDS`
3. Implement detection in the relevant detector in `abicheck/`
4. Add a unit test in `tests/`
5. Document in `docs/` if user-visible

## Questions

Open an [issue](https://github.com/napetrov/abicheck/issues) or discussion.
