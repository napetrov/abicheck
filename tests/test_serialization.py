"""Tests for abi_check.serialization — roundtrip JSON."""
import tempfile
from pathlib import Path

from abicheck.model import AbiSnapshot, Function, Visibility
from abicheck.serialization import (
    load_snapshot,
    save_snapshot,
    snapshot_from_dict,
    snapshot_to_dict,
)


def _sample_snap() -> AbiSnapshot:
    return AbiSnapshot(
        library="libsample.so.2",
        version="2.3.1",
        functions=[
            Function(
                name="sample_init",
                mangled="_Z11sample_initv",
                return_type="int",
                visibility=Visibility.PUBLIC,
                is_noexcept=True,
            )
        ],
    )


class TestSerialization:
    def test_roundtrip_dict(self):
        snap = _sample_snap()
        d = snapshot_to_dict(snap)
        snap2 = snapshot_from_dict(d)
        assert snap2.library == snap.library
        assert snap2.version == snap.version
        assert len(snap2.functions) == 1
        assert snap2.functions[0].mangled == "_Z11sample_initv"
        assert snap2.functions[0].is_noexcept is True

    def test_roundtrip_file(self):
        snap = _sample_snap()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmp = Path(f.name)
        try:
            save_snapshot(snap, tmp)
            snap2 = load_snapshot(tmp)
            assert snap2.version == snap.version
            assert snap2.functions[0].name == "sample_init"
        finally:
            tmp.unlink(missing_ok=True)

    def test_private_index_fields_not_serialized(self):
        snap = _sample_snap()
        d = snapshot_to_dict(snap)
        assert "_func_by_mangled" not in d
        assert "_var_by_mangled" not in d

    def test_is_inline_roundtrip(self):
        """is_inline=True must survive snapshot_to_dict → snapshot_from_dict roundtrip."""
        snap = AbiSnapshot(
            library="libfoo.so.1",
            version="1.0",
            functions=[
                Function(
                    name="fast",
                    mangled="_Z4fasti",
                    return_type="int",
                    visibility=Visibility.PUBLIC,
                    is_inline=True,
                )
            ],
        )
        d = snapshot_to_dict(snap)
        assert d["functions"][0]["is_inline"] is True
        snap2 = snapshot_from_dict(d)
        assert snap2.functions[0].is_inline is True

    def test_is_inline_false_roundtrip(self):
        """is_inline=False must survive snapshot_to_dict → snapshot_from_dict roundtrip."""
        snap = AbiSnapshot(
            library="libfoo.so.1",
            version="1.0",
            functions=[
                Function(
                    name="compute",
                    mangled="_Z7computei",
                    return_type="int",
                    visibility=Visibility.PUBLIC,
                    is_inline=False,
                )
            ],
        )
        d = snapshot_to_dict(snap)
        assert d["functions"][0]["is_inline"] is False
        snap2 = snapshot_from_dict(d)
        assert snap2.functions[0].is_inline is False
