from __future__ import annotations

from abicheck.core.corpus import CorpusBuilder, Normalizer
from abicheck.core.diff import diff_symbols, diff_type_layouts
from abicheck.core.model import ChangeKind, ChangeSeverity
from abicheck.model import (
    AbiSnapshot,
    Function,
    RecordType,
    TypeField,
    Variable,
    Visibility,
)


def _snap(
    *,
    funcs: list[Function] | None = None,
    vars_: list[Variable] | None = None,
    types: list[RecordType] | None = None,
    version: str = "v1",
) -> AbiSnapshot:
    return AbiSnapshot(
        library="libfoo.so",
        version=version,
        functions=funcs or [],
        variables=vars_ or [],
        types=types or [],
    )


class TestNormalizer:
    def test_intern_and_deduplicate_functions_public_wins(self) -> None:
        normalizer = Normalizer()

        # Same mangled symbol twice: ELF_ONLY and PUBLIC; PUBLIC must win
        f_elf = Function(
            name="foo",
            mangled="_Z3foov",
            return_type="int",
            visibility=Visibility.ELF_ONLY,
        )
        f_pub = Function(
            name="foo",
            mangled="_Z3foov",
            return_type="int",
            visibility=Visibility.PUBLIC,
        )
        s = _snap(funcs=[f_elf, f_pub])

        n = normalizer.normalize(s)
        assert len(n.functions) == 1
        assert n.functions[0].visibility == Visibility.PUBLIC

    def test_intern_strings_identity(self) -> None:
        normalizer = Normalizer()
        # Two functions sharing the same return_type string value
        f1 = Function(name="foo", mangled="_Z3foov", return_type="int")
        f2 = Function(name="bar", mangled="_Z3barv", return_type="int")

        n = normalizer.normalize(_snap(funcs=[f1, f2]))
        # After interning, same-value strings should be identical by identity
        assert n.functions[0].return_type is n.functions[1].return_type


class TestCorpusBuilder:
    def test_integer_keyed_maps_and_public_exports(self) -> None:
        normalizer = Normalizer()
        builder = CorpusBuilder()

        s = _snap(funcs=[
            Function(name="a", mangled="_Za", return_type="int", visibility=Visibility.PUBLIC),
            Function(name="b", mangled="_Zb", return_type="int", visibility=Visibility.HIDDEN),
        ], types=[
            RecordType(name="T1", kind="struct", size_bits=64),
            RecordType(name="T2", kind="struct", size_bits=128),
        ])

        n = normalizer.normalize(s)
        c = builder.build(n)

        assert all(isinstance(k, int) for k in c.reachable_types.keys())
        assert all(isinstance(k, int) for k in c.binary_exports.keys())
        assert list(c.public_interfaces.keys()) == ["_Za"]
        assert c.corpus_version == "v1"


class TestSymbolDiff:
    def test_detect_added_removed_changed_function(self) -> None:
        normalizer = Normalizer()

        before = _snap(funcs=[
            Function(name="old_only", mangled="_Z7oldonlyv", return_type="int", visibility=Visibility.PUBLIC),
            Function(name="same", mangled="_Z4samev", return_type="int", visibility=Visibility.PUBLIC),
        ])
        after = _snap(funcs=[
            Function(name="new_only", mangled="_Z7newonlyv", return_type="int", visibility=Visibility.PUBLIC),
            Function(name="same", mangled="_Z4samev", return_type="void", visibility=Visibility.PUBLIC),
        ], version="v2")

        b = normalizer.normalize(before)
        a = normalizer.normalize(after)
        changes = diff_symbols(b, a)

        # removed + added + return-type change
        assert len(changes) == 3
        severities = {c.severity for c in changes}
        assert ChangeSeverity.BREAK in severities
        assert ChangeSeverity.COMPATIBLE_EXTENSION in severities

    def test_single_function_pair_emits_multiple_changes(self) -> None:
        """elif→if: return type AND parameter change simultaneously → two Change objects."""
        normalizer = Normalizer()
        from abicheck.model import Param

        f_old = Function(
            name="f", mangled="_Z1f", return_type="int", visibility=Visibility.PUBLIC,
            params=[Param(name="x", type="int")],
        )
        f_new = Function(
            name="f", mangled="_Z1f", return_type="void", visibility=Visibility.PUBLIC,
            params=[Param(name="x", type="long")],  # both return type and param changed
        )

        b = normalizer.normalize(_snap(funcs=[f_old]))
        a = normalizer.normalize(_snap(funcs=[f_new], version="v2"))
        changes = diff_symbols(b, a)

        # return type change + param type change = 2 independent Change objects for same function
        func_changes = [c for c in changes if c.entity_name == "f"]
        assert len(func_changes) == 2, (
            f"Expected 2 changes for simultaneous return+param diff, got {len(func_changes)}"
        )
        assert all(c.severity == ChangeSeverity.BREAK for c in func_changes)

    def test_detect_variable_type_change(self) -> None:
        normalizer = Normalizer()
        b = normalizer.normalize(_snap(vars_=[
            Variable(name="g", mangled="g", type="int", visibility=Visibility.PUBLIC),
        ]))
        a = normalizer.normalize(_snap(vars_=[
            Variable(name="g", mangled="g", type="long", visibility=Visibility.PUBLIC),
        ], version="v2"))

        changes = diff_symbols(b, a)
        assert len(changes) == 1
        assert changes[0].entity_type == "variable"
        assert changes[0].severity == ChangeSeverity.BREAK


class TestTypeLayoutDiff:
    def test_detect_size_and_field_changes(self) -> None:
        normalizer = Normalizer()

        t_old = RecordType(
            name="Point",
            kind="struct",
            size_bits=64,
            fields=[TypeField(name="x", type="int", offset_bits=0)],
        )
        t_new = RecordType(
            name="Point",
            kind="struct",
            size_bits=96,
            fields=[
                TypeField(name="x", type="long", offset_bits=0),
                TypeField(name="y", type="int", offset_bits=64),
            ],
        )

        b = normalizer.normalize(_snap(types=[t_old]))
        a = normalizer.normalize(_snap(types=[t_new], version="v2"))

        changes = diff_type_layouts(b, a)

        kinds = {c.change_kind for c in changes}
        assert ChangeKind.SIZE_CHANGE in kinds
        assert ChangeKind.TYPE_LAYOUT in kinds
        assert any(c.entity_name == "Point::x" for c in changes)

    def test_alignment_change_detected(self) -> None:
        """alignment_bits change without size change must be detected (ABI-breaking on ARM)."""
        normalizer = Normalizer()

        t_old = RecordType(name="Foo", kind="struct", size_bits=64, alignment_bits=64,
                           fields=[TypeField(name="x", type="int", offset_bits=0)])
        t_new = RecordType(name="Foo", kind="struct", size_bits=64, alignment_bits=128,
                           fields=[TypeField(name="x", type="int", offset_bits=0)])

        b = normalizer.normalize(_snap(types=[t_old]))
        a = normalizer.normalize(_snap(types=[t_new], version="v2"))

        changes = diff_type_layouts(b, a)
        assert any("alignment" in c.before.entity_repr for c in changes)

    def test_added_type_is_compatible_extension(self) -> None:
        normalizer = Normalizer()
        b = normalizer.normalize(_snap(types=[]))
        a = normalizer.normalize(_snap(types=[RecordType(name="A", kind="struct", size_bits=32)], version="v2"))

        changes = diff_type_layouts(b, a)
        assert len(changes) == 1
        assert changes[0].entity_name == "A"
        assert changes[0].severity == ChangeSeverity.COMPATIBLE_EXTENSION
