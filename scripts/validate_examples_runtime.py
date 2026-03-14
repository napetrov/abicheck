#!/usr/bin/env python3
"""
abicheck examples runtime validation via LD_PRELOAD.

For each case in examples/:
  1. Build libv1.so / libv2.so / app_v1 via make
  2. Run abicheck dump+compare (with optional header files)
  3. Run app_v1 with LD_PRELOAD=libv2.so to detect real ABI breaks at runtime
  4. Compare abicheck verdict vs runtime result vs README expected verdict

Usage:
    python scripts/validate_examples_runtime.py [--examples examples/] [--output docs/]

Options:
    --examples  Path to examples directory (default: examples/)
    --output    Directory for JSON/Markdown reports (default: docs/)
"""
import argparse, os, re, json, subprocess
from pathlib import Path

parser = argparse.ArgumentParser(description="abicheck examples runtime validation")
parser.add_argument("--examples", default="examples", help="Path to examples directory")
parser.add_argument("--output",   default="docs",     help="Output directory for reports")
args = parser.parse_args()

root   = Path(args.examples)
outdir = Path(args.output)
outdir.mkdir(parents=True, exist_ok=True)

cases = sorted(
    [p for p in root.iterdir() if p.is_dir() and p.name.startswith("case")],
    key=lambda p: p.name,
)


def sh(cmd, cwd=None):
    p = subprocess.run(cmd, shell=True, cwd=cwd, text=True, capture_output=True)
    return p.returncode, p.stdout, p.stderr


def readme_verdict(case_dir: Path):
    p = case_dir / "README.md"
    if not p.exists():
        return None
    t = p.read_text(errors="ignore")
    m = re.search(r"\*\*Verdict:\*\*\s*([^\n]+)", t)
    if not m:
        m = re.search(r"\*\*Category:\*\*[^\n]*\*\*Verdict:\*\*\s*([^\n]+)", t)
    return m.group(1).strip() if m else None


def pick_headers(case_dir: Path):
    h1 = h2 = None
    for c in ("v1.h", "v1.hpp"):
        p = case_dir / c
        if p.exists():
            h1 = p
            break
    for c in ("v2.h", "v2.hpp"):
        p = case_dir / c
        if p.exists():
            h2 = p
            break
    if not h1 and (case_dir / "old").exists():
        olds = sorted((case_dir / "old").glob("*.h"))
        if olds:
            h1 = olds[0]
    if not h2 and (case_dir / "new").exists():
        news = sorted((case_dir / "new").glob("*.h"))
        if news:
            h2 = news[0]
    return h1, h2


def abicheck_verdict(case_dir: Path):
    lib1 = case_dir / "libv1.so"
    lib2 = case_dir / "libv2.so"
    if not lib1.exists() or not lib2.exists():
        return "NO_LIB", ""

    h1, h2 = pick_headers(case_dir)
    name = case_dir.name
    cmd1 = f"python3 -m abicheck.cli dump {lib1}" + (f" -H {h1}" if h1 else "") + f" -o /tmp/{name}_v1.json"
    cmd2 = f"python3 -m abicheck.cli dump {lib2}" + (f" -H {h2}" if h2 else "") + f" -o /tmp/{name}_v2.json"

    rc, so, se = sh(cmd1)
    if rc != 0:
        return "DUMP_FAIL", (so + se)[:500]
    rc, so, se = sh(cmd2)
    if rc != 0:
        return "DUMP_FAIL", (so + se)[:500]

    rc, so, se = sh(f"python3 -m abicheck.cli compare /tmp/{name}_v1.json /tmp/{name}_v2.json")
    text = so + se
    m = re.search(r"\*\*Verdict\*\* \| [^`]*`([^`]+)`", text)
    verdict = m.group(1) if m else ("COMPARE_FAIL" if rc != 0 else "UNKNOWN")
    return verdict, text[:1500]


def runtime_run(case_dir: Path):
    app = case_dir / "app_v1"
    if not app.exists():
        alt = case_dir / "app_test"
        app = alt if alt.exists() else None
    if not app:
        return "no_app", 0, ""

    env = os.environ.copy()
    lib2 = case_dir / "libv2.so"
    if lib2.exists():
        env["LD_PRELOAD"] = str(lib2.resolve())

    p = subprocess.run([str(app.resolve())], cwd=case_dir, text=True, capture_output=True, env=env)
    out = (p.stdout or "") + (p.stderr or "")
    bad_markers = [
        "segmentation fault", "aborted", "symbol lookup error",
        "corruption", "abi break confirmed", "terminate called",
    ]
    cls = "BREAKING" if (p.returncode != 0 or any(k in out.lower() for k in bad_markers)) else "NOT_BREAKING"
    return cls, p.returncode, out[:1200]


rows = []
for c in cases:
    sh(f"make -C {c.name} clean", cwd=root)
    sh(f"make -C {c.name}",       cwd=root)

    rv        = readme_verdict(c)
    av, ad    = abicheck_verdict(c)
    rr, rc, o = runtime_run(c)

    rows.append({
        "case":             c.name,
        "readme_verdict":   rv,
        "abicheck_verdict": av,
        "runtime_result":   rr,
        "runtime_rc":       rc,
        "runtime_excerpt":  o,
        "abicheck_excerpt": ad,
    })
    print(f"{c.name:20} readme={rv or '-':25} abicheck={av:20} runtime={rr} rc={rc}")

(outdir / "full_validation_preload.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False))

md_lines = ["# Full validation (LD_PRELOAD libv2)", "",
            "| case | readme | abicheck | runtime | rc |",
            "|---|---|---|---|---|"]
for r in rows:
    md_lines.append(f"| {r['case']} | {r['readme_verdict'] or '-'} | {r['abicheck_verdict']} | {r['runtime_result']} | {r['runtime_rc']} |")
(outdir / "full_validation_preload.md").write_text("\n".join(md_lines) + "\n")

print(f"\n✅ Saved {outdir}/full_validation_preload.{{json,md}}")
print(f"   Total cases:    {len(rows)}")
print(f"   Runtime BREAKING: {sum(1 for r in rows if r['runtime_result'] == 'BREAKING')}")
