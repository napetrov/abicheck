from __future__ import annotations

import json
from pathlib import Path

import pytest

from abicheck.dumper import dump
from abicheck.serialization import snapshot_to_dict


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _actual_digest(so_path: Path, header: Path, compiler: str) -> dict:
    snap = dump(so_path, [header], version="golden", compiler=compiler)
    d = snapshot_to_dict(snap)
    return {
        "function_count": len(d.get("functions", [])),
        "variable_count": len(d.get("variables", [])),
        "type_count": len(d.get("types", [])),
        "enum_count": len(d.get("enums", [])),
        "public_functions": sorted(
            [
                {"name": f["name"], "return_type": f["return_type"]}
                for f in d.get("functions", [])
                if f.get("visibility") == "public"
            ],
            key=lambda x: x["name"],
        ),
        "public_types": sorted(
            [
                {
                    "name": t["name"],
                    "kind": t["kind"],
                    "size_bits": t.get("size_bits"),
                }
                for t in d.get("types", [])
            ],
            key=lambda x: x["name"],
        ),
    }


@pytest.mark.parametrize("fixture_path", sorted(FIXTURES_DIR.glob("*.json")), ids=lambda p: p.stem)
def test_dumper_golden_fixture(fixture_path: Path) -> None:
    fixture = json.loads(fixture_path.read_text())
    so_path = Path(fixture["source"])
    header = Path(fixture["header"])
    compiler = fixture.get("compiler", "c++")

    assert so_path.exists(), f"missing shared object: {so_path}"
    assert header.exists(), f"missing header/source: {header}"

    expected = {
        "function_count": fixture["function_count"],
        "variable_count": fixture["variable_count"],
        "type_count": fixture["type_count"],
        "enum_count": fixture["enum_count"],
        "public_functions": fixture["public_functions"],
        "public_types": fixture["public_types"],
    }
    assert _actual_digest(so_path, header, compiler) == expected
