"""Integration: ELF symbol-parse scaling on real compiled ``.so`` files.

The pure-Python scaling harness (``scripts/benchmark_scaling.py``) builds
``AbiSnapshot`` objects directly, so it cannot exercise the snapshot/dump
*parsing* stage. This guards the ELF symbol-table parse (``parse_elf_metadata``)
— the most tractable slice of the dump path that needs only ``gcc`` (no
castxml) — by compiling shared libraries with a growing export count and
checking the parse stays sub-quadratic.

Requires ``gcc`` on Linux (gcc produces Mach-O on macOS, PE on Windows).
"""

from __future__ import annotations

import math
import subprocess
import sys
import time
from pathlib import Path

import pytest

from abicheck.elf_metadata import parse_elf_metadata

pytestmark = pytest.mark.skipif(
    sys.platform != "linux",
    reason="ELF parse scaling requires Linux (gcc produces Mach-O/PE elsewhere)",
)


def _gen_source(n: int) -> str:
    return "\n".join(f"int func_{i}(int x) {{ return x + {i}; }}" for i in range(n))


def _compile_so(src: str, path: Path) -> None:
    res = subprocess.run(
        ["gcc", "-shared", "-fPIC", "-O0", "-o", str(path), "-x", "c", "-"],
        input=src.encode(),
        capture_output=True,
    )
    if res.returncode != 0:
        pytest.skip(f"gcc failed: {res.stderr.decode()[:200]}")


@pytest.mark.integration
def test_elf_parse_scaling_stays_subquadratic(tmp_path: Path) -> None:
    """Parsing a 4x-larger symbol table must not take ~16x longer."""
    timings: list[tuple[int, float]] = []
    for n in (500, 2000):
        so = tmp_path / f"lib{n}.so"
        _compile_so(_gen_source(n), so)
        start = time.monotonic()
        meta = parse_elf_metadata(so)
        timings.append((n, max(time.monotonic() - start, 1e-3)))
        exported = sum(1 for s in meta.symbols if s.name.startswith("func_"))
        assert exported >= n // 2, f"expected ~{n} exports, parsed {exported}"

    (n1, t1), (n2, t2) = timings
    exponent = math.log(t2 / t1) / math.log(n2 / n1)
    # True quadratic would be ~2.0; generous bound catches a real regression
    # without flaking on shared CI runners.
    assert exponent < 1.9, (
        f"ELF parse scaling exponent {exponent:.2f} regressed toward O(n^2)"
    )
