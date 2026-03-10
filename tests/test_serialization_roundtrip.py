"""tests/test_serialization_roundtrip.py

Unit tests for AbiSnapshot JSON round-trip covering fields added in PR #63:
  - elf_only_mode
  - constants
"""
import json

from abicheck.model import AbiSnapshot
from abicheck.serialization import (
    load_snapshot,
    save_snapshot,
    snapshot_from_dict,
    snapshot_to_json,
)


def _minimal_dict(**overrides) -> dict:
    base = {
        "library": "libtest.so",
        "version": "v1",
        "functions": [],
        "variables": [],
        "types": [],
        "enums": [],
        "typedefs": [],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# elf_only_mode
# ---------------------------------------------------------------------------

def test_elf_only_mode_true_survives_roundtrip():
    """elf_only_mode=True must be preserved through to_json → from_dict."""
    snap = AbiSnapshot(
        library="libfoo.so", version="v1",
        functions=[], variables=[], types=[], enums=[], typedefs=[],
        elf_only_mode=True,
    )
    j = json.loads(snapshot_to_json(snap))
    assert j.get("elf_only_mode") is True, "elf_only_mode must be serialised as True"
    restored = snapshot_from_dict(j)
    assert restored.elf_only_mode is True


def test_elf_only_mode_false_survives_roundtrip():
    """elf_only_mode=False (default) must round-trip correctly."""
    snap = AbiSnapshot(
        library="libfoo.so", version="v1",
        functions=[], variables=[], types=[], enums=[], typedefs=[],
        elf_only_mode=False,
    )
    j = json.loads(snapshot_to_json(snap))
    restored = snapshot_from_dict(j)
    assert restored.elf_only_mode is False


def test_elf_only_mode_defaults_to_false_when_absent():
    """Snapshots produced before PR #63 (no elf_only_mode key) must deserialise to False."""
    d = _minimal_dict()
    assert "elf_only_mode" not in d
    snap = snapshot_from_dict(d)
    assert snap.elf_only_mode is False


def test_elf_only_mode_truthy_string_not_accepted():
    """Truthy non-bool values must still result in bool True (bool() coercion)."""
    d = _minimal_dict(elf_only_mode=1)
    snap = snapshot_from_dict(d)
    assert snap.elf_only_mode is True


# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

def test_constants_roundtrip():
    """constants dict must survive serialisation → deserialisation."""
    snap = AbiSnapshot(
        library="libfoo.so", version="v1",
        functions=[], variables=[], types=[], enums=[], typedefs=[],
        constants={"MAX_SIZE": "256", "VERSION": "3"},
    )
    j = json.loads(snapshot_to_json(snap))
    restored = snapshot_from_dict(j)
    assert restored.constants == {"MAX_SIZE": "256", "VERSION": "3"}


def test_constants_defaults_to_empty_dict_when_absent():
    """Old snapshots without constants key must deserialise to empty dict."""
    d = _minimal_dict()
    snap = snapshot_from_dict(d)
    assert snap.constants == {}


# ---------------------------------------------------------------------------
# file-based round-trip (load_snapshot / save_snapshot)
# ---------------------------------------------------------------------------

def test_elf_only_mode_survives_file_roundtrip(tmp_path):
    snap = AbiSnapshot(
        library="libfoo.so", version="v1",
        functions=[], variables=[], types=[], enums=[], typedefs=[],
        elf_only_mode=True,
        constants={"FOO": "bar"},
    )
    p = tmp_path / "snap.json"
    save_snapshot(snap, p)
    restored = load_snapshot(p)
    assert restored.elf_only_mode is True
    assert restored.constants == {"FOO": "bar"}
