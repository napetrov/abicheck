from abicheck.checker import compare
from abicheck.dwarf_advanced import AdvancedDwarfMetadata
from abicheck.model import AbiSnapshot


def test_advanced_dwarf_detector_reports_coverage_gap_when_unsupported() -> None:
    old = AbiSnapshot(library="libx.so", version="1.0")
    new = AbiSnapshot(library="libx.so", version="2.0")

    result = compare(old, new)
    adv = next(d for d in result.detector_results if d.name == "advanced_dwarf")
    assert adv.enabled is False
    assert adv.coverage_gap == "missing DWARF advanced metadata"


def test_advanced_dwarf_detector_requires_both_sides() -> None:
    old = AbiSnapshot(
        library="libx.so",
        version="1.0",
        dwarf_advanced=AdvancedDwarfMetadata(has_dwarf=True),
    )
    new = AbiSnapshot(library="libx.so", version="2.0")

    result = compare(old, new)
    adv = next(d for d in result.detector_results if d.name == "advanced_dwarf")
    assert adv.enabled is False
    assert adv.coverage_gap == "missing DWARF advanced metadata"
