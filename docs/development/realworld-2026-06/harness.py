#!/usr/bin/env python3
"""Real-world abicheck validation harness.

Runs `abicheck compare` over matched library pairs, captures verdict,
summary counts, change-kind histogram, timing, and stderr warnings.
Writes a machine-readable results.jsonl plus per-pair JSON reports.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

REPORTS = Path("/tmp/val/reports")
REPORTS.mkdir(parents=True, exist_ok=True)


def soname_stem(p: Path) -> str:
    """libonedal_core.so.4 -> libonedal_core ; libfoo-1.2.so.0.0 -> libfoo-1.2."""
    name = p.name
    name = re.sub(r"\.so.*$", "", name)
    return name


def find_libs(root: str) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for p in Path(root).rglob("*.so*"):
        if p.is_file():
            out.setdefault(soname_stem(p), p)
    return out


def run_compare(old: Path, new: Path, tag: str, extra: list[str] | None = None) -> dict:
    out_json = REPORTS / f"{tag}.json"
    cmd = [
        "abicheck", "compare", str(old), str(new),
        "--format", "json", "-o", str(out_json),
    ] + (extra or [])
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.time() - t0
    rec: dict = {
        "tag": tag,
        "old": str(old),
        "new": str(new),
        "rc": proc.returncode,
        "elapsed_s": round(elapsed, 2),
        "cmd": " ".join(cmd),
    }
    # capture distinctive stderr warnings (dedup)
    warns = sorted({ln.strip() for ln in proc.stderr.splitlines()
                    if "Warning" in ln or "warning" in ln or "Error" in ln})
    rec["warnings"] = warns
    if out_json.exists():
        try:
            d = json.loads(out_json.read_text())
            rec["verdict"] = d.get("verdict")
            rec["summary"] = d.get("summary")
            kinds = Counter(c.get("kind") for c in d.get("changes", []))
            rec["kind_histogram"] = dict(kinds)
            rec["surface_scope"] = {k: d.get("surface_scope", {}).get(k)
                                     for k in ("enabled", "confidence")}
            rec["release_recommendation"] = d.get("release_recommendation")
        except Exception as e:  # noqa: BLE001
            rec["parse_error"] = repr(e)
    else:
        rec["stderr_tail"] = proc.stderr.splitlines()[-5:]
    return rec


def main() -> None:
    versions = {
        "2024.7.0": "/tmp/val/work/daal-2024.7.0-py2.py3-none-manylinux1_x86_64",
        "2025.11.0": "/tmp/val/work/daal-2025.11.0-py2.py3-none-manylinux_2_28_x86_64",
        "2026.0.0": "/tmp/val/work/daal-2026.0.0-py2.py3-none-manylinux_2_28_x86_64",
    }
    libs = {v: find_libs(root) for v, root in versions.items()}
    for v, m in libs.items():
        print(f"# {v}: {sorted(m)}", file=sys.stderr)

    pairs = [
        ("2025.11.0", "2026.0.0", "adjacent"),   # .so.3 -> .so.4
        ("2024.7.0", "2026.0.0", "far"),         # .so.2 -> .so.4
        ("2024.7.0", "2025.11.0", "mid"),        # .so.2 -> .so.3
    ]
    results = []
    for old_v, new_v, label in pairs:
        common = sorted(set(libs[old_v]) & set(libs[new_v]))
        for stem in common:
            tag = f"onedal_{label}_{stem}"
            rec = run_compare(libs[old_v][stem], libs[new_v][stem], tag)
            rec["pair"] = f"{old_v}->{new_v}"
            rec["stem"] = stem
            results.append(rec)
            print(f"{tag}: verdict={rec.get('verdict')} "
                  f"changes={rec.get('summary',{}).get('total_changes')} "
                  f"t={rec['elapsed_s']}s", file=sys.stderr)
        # report removed libs
        removed = sorted(set(libs[old_v]) - set(libs[new_v]))
        added = sorted(set(libs[new_v]) - set(libs[old_v]))
        results.append({"tag": f"onedal_{label}_inventory", "pair": f"{old_v}->{new_v}",
                        "removed_libs": removed, "added_libs": added})

    out = REPORTS / "onedal_results.jsonl"
    with out.open("w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")
    print(f"\nWrote {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
