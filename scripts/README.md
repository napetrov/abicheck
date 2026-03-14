# scripts/

Utility scripts for benchmarking, stress testing, and validation.

## Public Library Stress Test

End-to-end ABI compatibility validation against 40+ real-world library pairs
(patch / minor / major version changes) from conda-forge.

### 1. Fetch packages

```bash
bash scripts/fetch_public_libs.sh --dest /tmp/ac_run
```

By default uses `/tmp/ac_run` as the working directory.
Requires `conda` (or `mamba` / `micromamba`) in `PATH`.

### 2. Run stress test

```bash
python scripts/stress_test_public_libs.py --base /tmp/ac_run
```

Both code paths are exercised for each pair:
- **dump+compare**: `abicheck dump` → `abicheck compare --format json`
- **compat**: ABICC-compatible XML descriptor via `abicheck compat`

Output:
```
✅ Correct: 28/44   ❌ FP: 0   ⚠ FN: 2   ⚡ discord: 0   ℹ info: 14
📄 /tmp/ac_run/stress_test.md
```

### 3. CI integration

The stress test can be run in CI (requires pre-fetched packages on the runner):

```yaml
- name: Stress test (public libs)
  run: python scripts/stress_test_public_libs.py --base ${{ env.LIBS_CACHE }} --output stress_report.md
```

---

## Examples Runtime Validation

Validates the `examples/` cases using real compilation + `LD_PRELOAD`:

```bash
# from repo root
python scripts/validate_examples_runtime.py --examples examples/ --output docs/
```

Produces:
- `docs/full_validation_preload.json` — machine-readable results
- `docs/full_validation_preload.md`   — human-readable Markdown table

---

## Other scripts

| Script | Purpose |
|--------|---------|
| `benchmark_comparison.py` | Compare abicheck performance against libabigail |
| `demo_libz.py`            | Quick demo: check libz ABI between two versions |
