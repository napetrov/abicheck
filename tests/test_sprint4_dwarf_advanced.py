"""Sprint 4 tests: advanced DWARF detectors (calling convention, packing, toolchain drift)."""
from __future__ import annotations

from abicheck.checker import ChangeKind, Verdict, compare
from abicheck.dwarf_advanced import (
    AdvancedDwarfMetadata,
    ToolchainInfo,
    diff_advanced_dwarf,
)
from abicheck.model import AbiSnapshot
from abicheck.serialization import snapshot_from_dict, snapshot_to_dict


def _snap(adv: AdvancedDwarfMetadata | None) -> AbiSnapshot:
    s = AbiSnapshot(library="libx.so", version="v")
    s.dwarf_advanced = adv  # type: ignore[attr-defined]
    return s


def _adv(
    *,
    has_dwarf: bool = True,
    calling: dict[str, str] | None = None,
    packed: set[str] | None = None,
    flags: set[str] | None = None,
) -> AdvancedDwarfMetadata:
    return AdvancedDwarfMetadata(
        has_dwarf=has_dwarf,
        toolchain=ToolchainInfo(
            producer_string="gcc",
            compiler="GCC",
            version="13.2",
            abi_flags=flags or set(),
        ),
        calling_conventions=calling or {},
        packed_structs=packed or set(),
    )


def test_diff_advanced_dwarf_no_dwarf() -> None:
    old = _adv(has_dwarf=False)
    new = _adv(has_dwarf=True)
    assert diff_advanced_dwarf(old, new) == []


def test_calling_convention_changed() -> None:
    old = _snap(_adv(calling={"foo": "program"}))
    new = _snap(_adv(calling={"foo": "normal"}))
    r = compare(old, new)
    kinds = {c.kind for c in r.changes}
    assert ChangeKind.CALLING_CONVENTION_CHANGED in kinds
    assert r.verdict == Verdict.BREAKING


def test_calling_convention_added_non_default() -> None:
    old = _snap(_adv(calling={}))
    new = _snap(_adv(calling={"foo": "LLVM_vectorcall"}))
    r = compare(old, new)
    assert any(c.kind == ChangeKind.CALLING_CONVENTION_CHANGED for c in r.changes)


def test_struct_packing_changed() -> None:
    old = _snap(_adv(packed=set()))
    new = _snap(_adv(packed={"Ctx"}))
    r = compare(old, new)
    kinds = {c.kind for c in r.changes}
    assert ChangeKind.STRUCT_PACKING_CHANGED in kinds
    assert r.verdict == Verdict.BREAKING


def test_toolchain_flag_drift_warning_compatible() -> None:
    old = _snap(_adv(flags={"-fshort-enums"}))
    new = _snap(_adv(flags={"-fshort-enums", "-mabi=lp64"}))
    r = compare(old, new)
    kinds = {c.kind for c in r.changes}
    assert ChangeKind.TOOLCHAIN_FLAG_DRIFT in kinds
    # informational warning only
    assert r.verdict == Verdict.COMPATIBLE


def test_serialization_roundtrip_dwarf_advanced_sets() -> None:
    snap = _snap(_adv(calling={"foo": "program"}, packed={"A", "B"}, flags={"-fshort-enums"}))
    d = snapshot_to_dict(snap)

    # ensure JSON-safe conversion happened
    assert isinstance(d["dwarf_advanced"]["packed_structs"], list)
    assert isinstance(d["dwarf_advanced"]["toolchain"]["abi_flags"], list)

    snap2 = snapshot_from_dict(d)
    assert snap2.dwarf_advanced is not None
    assert snap2.dwarf_advanced.calling_conventions.get("foo") == "program"
    assert snap2.dwarf_advanced.packed_structs == {"A", "B"}
    assert snap2.dwarf_advanced.toolchain.abi_flags == {"-fshort-enums"}
