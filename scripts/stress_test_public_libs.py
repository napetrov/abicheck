#!/usr/bin/env python3
"""
abicheck stress test — 40+ public library pairs.

Tests two code paths:
  A) dump+compare  (abicheck dump → abicheck compare --format json)
  B) compat        (ABICC drop-in XML descriptor)

Categories:
  PATCH  → expect COMPATIBLE (zero false positives)
  MINOR  → informational (UNKNOWN expected)
  MAJOR  → expect BREAKING detection

Usage:
    # Download packages first (conda / apt / dnf):
    #   see scripts/fetch_public_libs.sh
    python scripts/stress_test_public_libs.py [--base /path/to/libs] [--abicheck /path/to/abicheck]

Options:
    --base      Directory with unpacked library trees (default: /tmp/ac_run)
    --abicheck  Path to abicheck binary (default: auto-detected via PATH / pipx)
    --output    Path for Markdown report (default: <base>/stress_test.md)
"""
import argparse, subprocess, json, sys, shutil
from pathlib import Path

def _resolve_abicheck() -> str:
    found = shutil.which("abicheck")
    if found:
        return found
    # common pipx/local install paths
    for p in [Path.home() / ".local/bin/abicheck", Path("/usr/local/bin/abicheck")]:
        if p.exists():
            return str(p)
    raise RuntimeError("abicheck not found in PATH; pass --abicheck /path/to/abicheck")

parser = argparse.ArgumentParser(description="abicheck public library stress test")
parser.add_argument("--base",     default="/tmp/ac_run", help="Root dir with unpacked .so trees")
parser.add_argument("--abicheck", default=None,          help="Path to abicheck binary")
parser.add_argument("--output",   default=None,          help="Output Markdown report path")
args = parser.parse_args()

BASE     = Path(args.base)
ABICHECK = args.abicheck or _resolve_abicheck()
OUT_MD   = Path(args.output) if args.output else BASE / "stress_test.md"

def find_so(pkg_ver, stem):
    """Find the primary .so for a stem — prefer shortest name to avoid demux/decoder."""
    p = BASE / pkg_ver / "lib"
    if not p.exists(): return None
    cands = sorted(
        [x for x in p.glob(f"{stem}*.so*") if x.is_file() and not x.is_symlink()],
        key=lambda x: len(x.name)          # shortest = most specific match
    )
    return cands[0] if cands else None

def dump_compare(so1, so2, v1, v2, tag):
    d = BASE / f"dc_{tag}"; d.mkdir(exist_ok=True)
    s1, s2 = d/"old.json", d/"new.json"
    r1 = subprocess.run([ABICHECK,"dump",str(so1),"--version",v1,"-o",str(s1)],
                        capture_output=True, timeout=90)
    r2 = subprocess.run([ABICHECK,"dump",str(so2),"--version",v2,"-o",str(s2)],
                        capture_output=True, timeout=90)
    if r1.returncode or r2.returncode:
        return "DUMP_ERR", 0, 0
    r = subprocess.run([ABICHECK,"compare",str(s1),str(s2),"--format","json"],
                       capture_output=True, text=True, timeout=90)
    try:
        data    = json.loads(r.stdout)
        verdict = data["verdict"].upper()
        chgs    = data.get("changes", [])
        rem = len([c for c in chgs if "remov" in c.get("kind","").lower()])
        add = len([c for c in chgs if "add"   in c.get("kind","").lower()])
        return verdict, rem, add
    except:
        return "PARSE_ERR", 0, 0

def run_compat(so1, so2, v1, v2, lname, tag):
    d = BASE / f"cp_{tag}"; d.mkdir(exist_ok=True)
    x1, x2 = d/"old.xml", d/"new.xml"
    x1.write_text(f"<descriptor>\n  <version>{v1}</version>\n  <libs>{so1}</libs>\n</descriptor>")
    x2.write_text(f"<descriptor>\n  <version>{v2}</version>\n  <libs>{so2}</libs>\n</descriptor>")
    r = subprocess.run([ABICHECK,"compat","-lib",lname,"-old",str(x1),"-new",str(x2)],
                       capture_output=True, text=True, timeout=120)
    return {0:"COMPATIBLE", 1:"BREAKING", 2:"API_BREAK"}.get(r.returncode, f"ERR({r.returncode})")

# (dir1, dir2, so_stem, lib_name, expected, note)
PAIRS = [
    # ═══ PATCH — все должны быть COMPATIBLE ══════════════════════════════
    ("libabseil_20240116.0", "libabseil_20240116.1", "libabsl_base",  "libabsl_base",  "COMPATIBLE", "abseil patch"),
    ("libabseil_20240116.1", "libabseil_20240116.2", "libabsl_base",  "libabsl_base",  "COMPATIBLE", "abseil patch"),
    ("libabseil_20230802.0", "libabseil_20230802.1", "libabsl_base",  "libabsl_base",  "COMPATIBLE", "abseil patch"),
    ("libabseil_20230125.2", "libabseil_20230125.3", "libabsl_base",  "libabsl_base",  "COMPATIBLE", "abseil patch"),
    ("libabseil_20250512.0", "libabseil_20250512.1", "libabsl_base",  "libabsl_base",  "COMPATIBLE", "abseil patch"),
    ("openssl_3.3.1",        "openssl_3.3.2",        "libssl",        "libssl",        "COMPATIBLE", "openssl patch"),
    ("openssl_3.4.0",        "openssl_3.4.1",        "libssl",        "libssl",        "COMPATIBLE", "openssl patch"),
    ("openssl_3.5.0",        "openssl_3.5.1",        "libssl",        "libssl",        "COMPATIBLE", "openssl patch"),
    ("openssl_3.5.1",        "openssl_3.5.2",        "libssl",        "libssl",        "COMPATIBLE", "openssl patch"),
    ("openssl_1.1.1s",       "openssl_1.1.1t",       "libssl",        "libssl",        "COMPATIBLE", "openssl 1.x patch"),
    ("openssl_3.3.1",        "openssl_3.3.2",        "libcrypto",     "libcrypto",     "COMPATIBLE", "openssl crypto patch"),
    ("openssl_3.5.0",        "openssl_3.5.1",        "libcrypto",     "libcrypto",     "COMPATIBLE", "openssl crypto patch"),
    ("libcurl_8.14.0",       "libcurl_8.14.1",       "libcurl",       "libcurl",       "COMPATIBLE", "libcurl patch"),
    ("libpng_1.6.43",        "libpng_1.6.44",        "libpng16",      "libpng",        "COMPATIBLE", "libpng patch"),
    ("zlib_1.3.0",           "zlib_1.3.1",           "libz",          "libz",          "COMPATIBLE", "zlib patch"),
    ("libxml2_2.13.4",       "libxml2_2.13.5",       "libxml2",       "libxml2",       "COMPATIBLE", "libxml2 patch"),
    ("libxml2_2.12.6",       "libxml2_2.12.7",       "libxml2",       "libxml2",       "COMPATIBLE", "libxml2 patch"),
    ("zstd_1.5.5",           "zstd_1.5.6",           "libzstd",       "libzstd",       "COMPATIBLE", "zstd patch"),
    ("snappy_1.2.0",         "snappy_1.2.1",         "libsnappy",     "libsnappy",     "COMPATIBLE", "snappy patch"),
    ("libjpeg-turbo_3.0.0",  "libjpeg-turbo_3.1.0",  "libjpeg",       "libjpeg",       "COMPATIBLE", "jpeg-turbo patch"),
    ("libwebp_1.3.0",        "libwebp_1.4.0",        "libwebp",       "libwebp",       "COMPATIBLE", "webp minor (ABI compat)"),
    ("libwebp_1.4.0",        "libwebp_1.5.0",        "libwebp",       "libwebp",       "COMPATIBLE", "webp minor (ABI compat)"),

    # ═══ MINOR — информационные ═══════════════════════════════════════════
    ("libabseil_20230125.3", "libabseil_20230802.0", "libabsl_base",  "libabsl_base",  "UNKNOWN",    "abseil minor"),
    ("libabseil_20240116.2", "libabseil_20240722.0", "libabsl_base",  "libabsl_base",  "UNKNOWN",    "abseil minor"),
    ("libabseil_20240722.0", "libabseil_20250127.0", "libabsl_base",  "libabsl_base",  "UNKNOWN",    "abseil minor"),
    ("libcurl_8.11.1",       "libcurl_8.12.0",       "libcurl",       "libcurl",       "UNKNOWN",    "libcurl minor"),
    ("libcurl_8.12.0",       "libcurl_8.13.0",       "libcurl",       "libcurl",       "UNKNOWN",    "libcurl minor"),
    ("libcurl_8.17.0",       "libcurl_8.18.0",       "libcurl",       "libcurl",       "UNKNOWN",    "libcurl minor"),
    ("libsqlite_3.46.0",     "libsqlite_3.47.0",     "libsqlite3",    "libsqlite3",    "UNKNOWN",    "sqlite minor"),
    ("libsqlite_3.47.0",     "libsqlite_3.48.0",     "libsqlite3",    "libsqlite3",    "UNKNOWN",    "sqlite minor"),
    ("libopenblas_0.3.28",   "libopenblas_0.3.29",   "libopenblas",   "libopenblas",   "UNKNOWN",    "openblas minor"),
    ("libopenblas_0.3.29",   "libopenblas_0.3.30",   "libopenblas",   "libopenblas",   "UNKNOWN",    "openblas minor"),
    ("re2_2023.09.01",       "re2_2024.07.02",       "libre2",        "libre2",        "UNKNOWN",    "re2 minor"),
    ("libevent_2.1.10",      "libevent_2.1.12",      "libevent-2.1",  "libevent",      "UNKNOWN",    "libevent minor"),
    ("snappy_1.1.9",         "snappy_1.2.0",         "libsnappy",     "libsnappy",     "UNKNOWN",    "snappy minor"),
    ("gmp_6.2.1",            "gmp_6.3.0",            "libgmp",        "libgmp",        "UNKNOWN",    "gmp minor"),

    # ═══ MAJOR — должны детектировать BREAKING ════════════════════════════
    ("openssl_1.1.1t",       "openssl_3.3.1",        "libssl",        "libssl",        "BREAKING",   "openssl 1→3 ★"),
    ("openssl_1.1.1t",       "openssl_3.3.1",        "libcrypto",     "libcrypto",     "BREAKING",   "openssl crypto 1→3 ★"),
    ("openssl_1.1.1t",       "openssl_3.5.2",        "libssl",        "libssl",        "BREAKING",   "openssl 1→3.5 ★"),
    ("libabseil_20220623.0", "libabseil_20230802.0", "libabsl_base",  "libabsl_base",  "BREAKING",   "abseil year jump 22→23 ★"),
    ("libabseil_20220623.0", "libabseil_20250127.0", "libabsl_base",  "libabsl_base",  "BREAKING",   "abseil year jump 22→25 ★"),
    ("libjpeg-turbo_2.1.5",  "libjpeg-turbo_3.0.0",  "libjpeg",       "libjpeg",       "BREAKING",   "jpeg-turbo 2→3 ★"),
    ("libcurl_7.88.1",       "libcurl_8.0.1",        "libcurl",       "libcurl",       "BREAKING",   "libcurl 7→8 (FN expected)"),
    ("libxml2_2.12.0",       "libxml2_2.13.4",       "libxml2",       "libxml2",       "BREAKING",   "libxml2 2.12→2.13 ★"),
]

ok=fp=fn=skip=info=discord=0; rows=[]

W = 16, 32, 11, 12, 12, 9
hdr = f"{'library':{W[0]}} {'v1→v2':{W[1]}} {'exp':{W[2]}} {'dump+cmp':{W[3]}} {'compat':{W[4]}} {'Δ-+':{W[5]}} result"
print(hdr); print("─"*len(hdr))

for d1,d2,lib,lname,exp,note in PAIRS:
    so1 = find_so(d1, lib); so2 = find_so(d2, lib)
    v1  = d1.split("_",1)[1]; v2 = d2.split("_",1)[1]
    ver = f"{v1}→{v2}"
    if not so1 or not so2:
        print(f"  {lib:{W[0]}} {ver:{W[1]}} {exp:{W[2]}} {'SKIP':{W[3]}} {'SKIP':{W[4]}} {'':9} ⚠ SKIP ({so1 and 'so2?' or 'so1?'})")
        skip+=1; rows.append((lib,ver,exp,"SKIP","SKIP","","SKIP","")); continue

    tag = f"{lib}_{v1}_{v2}"
    va,rem,add = dump_compare(so1,so2,v1,v2,tag)
    vb         = run_compat(so1,so2,v1,v2,lname,tag)
    delta      = f"-{rem}+{add}"

    if exp=="UNKNOWN":
        cls="ℹ INFO"; info+=1
    elif exp=="COMPATIBLE":
        if va in ("COMPATIBLE","NO_CHANGE"): cls="✅ OK"; ok+=1
        elif va=="BREAKING":                 cls="❌ FP"; fp+=1
        else:                                cls=f"?{va}"; skip+=1
    elif exp=="BREAKING":
        if va=="BREAKING":                   cls="✅ OK"; ok+=1
        elif va in ("COMPATIBLE","NO_CHANGE"):cls="⚠ FN"; fn+=1
        else:                                cls=f"?{va}"; skip+=1
    else:
        cls="?"; skip+=1

    va_n = "COMPATIBLE" if va in ("COMPATIBLE","NO_CHANGE") else va
    vb_n = "COMPATIBLE" if vb in ("COMPATIBLE","NO_CHANGE") else vb
    disc = ""
    if va_n!=vb_n and "ERR" not in vb and vb!="API_BREAK":
        disc=f"⚡disco(cp={vb})"; discord+=1

    print(f"  {lib:{W[0]}} {ver:{W[1]}} {exp:{W[2]}} {va:{W[3]}} {vb:{W[4]}} {delta:{W[5]}} {cls}  {disc}")
    rows.append((lib,ver,exp,va,vb,delta,cls,disc))

print(f"\n{'═'*72}")
total = len(PAIRS)-skip
print(f"  ✅ Correct:          {ok}/{total}")
print(f"  ❌ False Positives:  {fp}   ← patch→BREAKING (must be 0)")
print(f"  ⚠  False Negatives:  {fn}   ← major missed as compatible")
print(f"  ⚡ Path discords:    {discord}   ← dump+cmp vs compat disagree")
print(f"  ℹ  Informational:   {info}")
print(f"  ⚠  Skipped:         {skip}")
print(f"{'═'*72}")

if fp:
    print("\n❌ FALSE POSITIVES:")
    for r in rows:
        if "FP" in r[6]: print(f"    {r[0]:16} {r[1]:32} → {r[3]}")
if fn:
    print("\n⚠ FALSE NEGATIVES:")
    for r in rows:
        if "FN" in r[6]: print(f"    {r[0]:16} {r[1]:32} → {r[3]}")
if discord:
    print("\n⚡ PATH DISCORDS:")
    for r in rows:
        if r[7]: print(f"    {r[0]:16} {r[1]:32} dc={r[3]}  cp={r[4]}")

md = ["# abicheck Stress Test v3\n",
      f"**{len(PAIRS)} pairs** | ✅ {ok} OK | ❌ {fp} FP | ⚠️ {fn} FN | ⚡ {discord} discord | ℹ️ {info} | ⚠️ {skip} skip\n",
      "| Library | v1→v2 | Expected | dump+cmp | compat | Δ | Class | Discord |",
      "|---------|-------|----------|----------|--------|---|-------|---------|"]
for r in rows:
    md.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]} | {r[6]} | {r[7]} |")
OUT_MD.parent.mkdir(parents=True, exist_ok=True)
OUT_MD.write_text("\n".join(md))
print(f"\n📄 {OUT_MD}")
sys.exit(1 if fp else 0)
