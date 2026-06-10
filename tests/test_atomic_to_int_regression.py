"""Regression: a pimpl member changing std::atomic<int> → int is detectable.

Background: in the oneTBB ABI swarm review, case101 was proposed as a new
detector (atomic → non-atomic refcount). DWARF preserves the full type name
of `std::atomic<int>` as a distinct DW_TAG_class_type rather than collapsing
it to its underlying integer, so the *existing* TYPE_FIELD_TYPE_CHANGED
detector fires for this pattern with no new code required. This test pins
that behavior so a future "smart" canonicalization doesn't silently demote
the change to NO_CHANGE.
"""

from abicheck.checker import compare
from abicheck.checker_policy import BREAKING_KINDS, ChangeKind, Verdict
from abicheck.model import AbiSnapshot, RecordType, TypeField


def _snap_with_record(version: str, record: RecordType) -> AbiSnapshot:
    return AbiSnapshot(
        library="libtest.so.1",
        version=version,
        functions=[],
        variables=[],
        types=[record],
    )


def _pimpl_record(refcount_type: str) -> RecordType:
    return RecordType(
        name="task_handle_impl",
        kind="struct",
        size_bits=32,
        alignment_bits=32,
        fields=[
            TypeField(name="refcount", type=refcount_type, offset_bits=0),
        ],
    )


def test_atomic_int_to_int_is_breaking() -> None:
    old = _snap_with_record("1.0", _pimpl_record("std::atomic<int>"))
    new = _snap_with_record("2.0", _pimpl_record("int"))
    r = compare(old, new)
    assert r.verdict == Verdict.BREAKING
    assert any(c.kind == ChangeKind.TYPE_FIELD_TYPE_CHANGED for c in r.changes)
    assert ChangeKind.TYPE_FIELD_TYPE_CHANGED in BREAKING_KINDS


def test_int_to_atomic_int_is_breaking() -> None:
    """The symmetric case — adding atomicity to an existing refcount field —
    is equally an ABI break (the same offset now holds a richer type)."""
    old = _snap_with_record("1.0", _pimpl_record("int"))
    new = _snap_with_record("2.0", _pimpl_record("std::atomic<int>"))
    r = compare(old, new)
    assert r.verdict == Verdict.BREAKING
    assert any(c.kind == ChangeKind.TYPE_FIELD_TYPE_CHANGED for c in r.changes)
