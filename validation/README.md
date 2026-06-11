# validation/ — real-world validation runs

Evidence-based validation of abicheck against real upstream C/C++ shared
libraries (not synthetic fixtures), used to drive planning and improvement.

- `REPORT.md` — latest validation report (start here)
- `DESIGN_ANALYSIS.md` — code-level root cause + architectural fix per false
  positive. FP-1/FP-2 are fixed in `abicheck/model.py` + `abicheck/diff_types.py`;
  FP-3/FP-4 are guarded by strict-xfail regression tests in
  `tests/test_real_world_false_positives.py`.
- `data/manifest.json` — the curated version-pair matrix (exact upstream files)
- `data/results.json` — raw per-`.so` comparison results
- `data/false_positive_evidence.json` — false-positive exemplars
- `suppress_internal.yaml` — internal-namespace suppression used in the report
- `scripts/run_matrix.py` — reproducible harness

Binaries are intentionally not committed; reproduce them from `data/manifest.json`
(conda-forge, `https://conda.anaconda.org/conda-forge/linux-64/<file>`).

## abi-laboratory.pro parity oracle

`scripts/fetch_tracker_oracle.py` turns the published verdicts on
[abi-laboratory.pro/tracker](https://abi-laboratory.pro/index.php?view=tracker)
into a labelled ground-truth oracle. The tracker is run by the author of
`abi-compliance-checker` (the tool abicheck replaces) and reports a
backward-compatibility verdict for every consecutive release of ~800 libraries —
an independent reference label for real-world ABI outcomes.

It only reads the public timeline page (no ABI dumps are downloaded or
redistributed), so the licensing surface stays at "reading a web page". Harvested
oracles land in `data/tracker_oracle/<lib>.json` and are **gitignored**
(regenerable, third-party-derived).

```bash
# 1. Harvest oracles (expected verdicts) for one or more libraries
python validation/scripts/fetch_tracker_oracle.py zstd libxml2 openssl
#   -> data/tracker_oracle/zstd.json : consecutive (old -> new) pairs, each
#      labelled COMPATIBLE / BREAKING from the tracker's backward-compat figure.

# 2. Run abicheck on binaries for those versions (e.g. via run_matrix.py),
#    producing a results list/object that maps pair ids to abicheck verdicts.

# 3. Score abicheck against the oracle
python validation/scripts/fetch_tracker_oracle.py zstd --compare results.json
#   [zstd] comparable=37 agreement=97.3% match=36 stricter=0 weaker=1 ...
#     WEAKER (likely FN): zstd_0.7.3_to_0.7.4 oracle=BREAKING abicheck=COMPATIBLE
```

Status semantics from `--compare`:

| Status | Meaning |
|--------|---------|
| `MATCH` | abicheck and the tracker agree |
| `ABICHECK_STRICTER` | abicheck flags BREAKING where the tracker says COMPATIBLE — often legitimate (ABICC has documented blind spots), worth spot-checking |
| `ABICHECK_WEAKER` | abicheck says COMPATIBLE where the tracker found a break — a likely **false negative**, the high-value signal to investigate |
| `UNCOMPARABLE` | no clear verdict on one side, or no abicheck result for the pair (excluded from the agreement rate) |

Parsing is pure and unit-tested offline against a synthetic timeline fixture in
`tests/test_tracker_oracle.py` (CI never hits the network).
