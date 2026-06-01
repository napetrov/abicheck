# Real-world validation artifacts — June 2026

Supporting data for [`../realworld-validation-2026-06.md`](../realworld-validation-2026-06.md).

| File | What it is |
|---|---|
| `harness.py` | Cross-version oneDAL `compare` driver (verdict, kind histogram, timing, warnings). |
| `selfsweep.py` | 100-library self-comparison robustness + false-positive sweep. |
| `onedal_results.jsonl` | One JSON line per oneDAL library pair (14 pairs + inventory deltas). |
| `selfsweep_results.jsonl` | One JSON line per self-compared system library (100). |
| `selfsweep_summary.json` | Aggregate counters for the self-compare sweep. |
| `*.slim.json` | Headline `compare` reports with the multi-MB `changes` array reduced to a kind histogram + 20 samples. |

Full (un-slimmed) reports were 80–90 MB each and are not committed; regenerate
with the scripts above (see the report's §9 Reproduction).
