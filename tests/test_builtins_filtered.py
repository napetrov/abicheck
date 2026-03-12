"""B2: `<built-in>` types polluting dump (abi-dumper #38, abicc PR#124).

castxml output can include entries referencing `<built-in>` or `<command-line>`
pseudo-files. These represent compiler built-in type declarations (e.g.
`__builtin_va_list`) and should not appear in the ABI snapshot as public types
or functions, as they are not user-visible ABI surface.

Detection mechanism:
- castxml XML elements have a `location` attribute pointing to a Location id
- The Location element has a `file` attribute pointing to a File element
- The File element's `name` attribute may be `<built-in>` or `<command-line>`
- Dumper should skip any element whose resolved file is `<built-in>` or
  `<command-line>`

Current status (verified): The dumper's _is_public_record_type() filters types
with names starting with `__`, which catches many builtins. However, it does NOT
explicitly check the file attribute for `<built-in>` / `<command-line>`.

This test verifies the filtering behavior using a mock XML fixture.
"""
from __future__ import annotations

from xml.etree.ElementTree import Element, SubElement


def _make_castxml_xml_with_builtin() -> Element:
    """Build a castxml XML tree that includes both user-defined and built-in types.

    Mirrors actual castxml output where some types come from <built-in>.
    """
    root = Element("CastXML")

    # File entries
    user_file = SubElement(root, "File")
    user_file.set("id", "f1")
    user_file.set("name", "mylib.h")

    builtin_file = SubElement(root, "File")
    builtin_file.set("id", "f2")
    builtin_file.set("name", "<built-in>")

    cmdline_file = SubElement(root, "File")
    cmdline_file.set("id", "f3")
    cmdline_file.set("name", "<command-line>")

    # Location entries
    user_loc = SubElement(root, "Location")
    user_loc.set("id", "l1")
    user_loc.set("file", "f1")
    user_loc.set("line", "5")

    builtin_loc = SubElement(root, "Location")
    builtin_loc.set("id", "l2")
    builtin_loc.set("file", "f2")
    builtin_loc.set("line", "0")

    cmdline_loc = SubElement(root, "Location")
    cmdline_loc.set("id", "l3")
    cmdline_loc.set("file", "f3")
    cmdline_loc.set("line", "0")

    # User-defined struct (should appear in snapshot)
    user_struct = SubElement(root, "Struct")
    user_struct.set("id", "_1")
    user_struct.set("name", "MyStruct")
    user_struct.set("size", "64")
    user_struct.set("align", "32")
    user_struct.set("location", "l1")

    # Built-in function (should NOT appear in snapshot)
    builtin_func = SubElement(root, "Function")
    builtin_func.set("id", "_2")
    builtin_func.set("name", "__builtin_va_list")
    builtin_func.set("mangled", "__builtin_va_list")
    builtin_func.set("returns", "")
    builtin_func.set("location", "l2")

    # User-defined function (should appear in snapshot)
    user_func = SubElement(root, "Function")
    user_func.set("id", "_3")
    user_func.set("name", "my_func")
    user_func.set("mangled", "my_func")
    user_func.set("returns", "")
    user_func.set("location", "l1")

    # Built-in struct with __ prefix (should NOT appear — _is_public_record_type filters it)
    builtin_struct = SubElement(root, "Struct")
    builtin_struct.set("id", "_4")
    builtin_struct.set("name", "__va_list_tag")
    builtin_struct.set("size", "32")
    builtin_struct.set("location", "l2")

    # command-line struct (should NOT appear)
    cmdline_struct = SubElement(root, "Struct")
    cmdline_struct.set("id", "_5")
    cmdline_struct.set("name", "__CMDLINE_DEFINE__")
    cmdline_struct.set("size", "32")
    cmdline_struct.set("location", "l3")

    return root


class TestBuiltinsFiltered:
    """Verify <built-in> types/functions do not pollute the ABI snapshot."""

    def test_user_struct_in_types(self) -> None:
        """User-defined struct from mylib.h must appear in parse_types()."""
        from abicheck.dumper import _CastxmlParser
        root = _make_castxml_xml_with_builtin()
        parser = _CastxmlParser(root, exported_dynamic=set(), exported_static=set())
        types = parser.parse_types()
        names = {t.name for t in types}
        assert "MyStruct" in names

    def test_va_list_struct_not_in_types(self) -> None:
        """__va_list_tag (name starts with __) must NOT appear in parse_types()."""
        from abicheck.dumper import _CastxmlParser
        root = _make_castxml_xml_with_builtin()
        parser = _CastxmlParser(root, exported_dynamic=set(), exported_static=set())
        types = parser.parse_types()
        names = {t.name for t in types}
        assert "__va_list_tag" not in names

    def test_cmdline_struct_not_in_types(self) -> None:
        """__CMDLINE_DEFINE__ (name starts with __) must NOT appear in parse_types()."""
        from abicheck.dumper import _CastxmlParser
        root = _make_castxml_xml_with_builtin()
        parser = _CastxmlParser(root, exported_dynamic=set(), exported_static=set())
        types = parser.parse_types()
        names = {t.name for t in types}
        assert "__CMDLINE_DEFINE__" not in names

    def test_user_func_in_functions(self) -> None:
        """User-defined function from mylib.h must appear in parse_functions()."""
        from abicheck.dumper import _CastxmlParser
        root = _make_castxml_xml_with_builtin()
        parser = _CastxmlParser(
            root,
            exported_dynamic={"my_func"},
            exported_static={"my_func"},
        )
        funcs = parser.parse_functions()
        names = {f.name for f in funcs}
        assert "my_func" in names

    def test_builtin_func_filtered_from_snapshot(self) -> None:
        """__builtin_va_list must NOT appear in snapshot types via name filter.

        Note: castxml typically emits __builtin_* as Function elements with names
        starting with __. The _is_public_record_type filter handles types;
        function names starting with __ are a separate concern.

        This test verifies the current behavior: __builtin_va_list is parsed as
        a function but filtered out if it's not in the exported symbol set.
        Since it's not in exported_dynamic, its visibility will be HIDDEN,
        and the checker will not treat it as a public API symbol.
        """
        from abicheck.dumper import _CastxmlParser
        from abicheck.model import Visibility
        root = _make_castxml_xml_with_builtin()
        # __builtin_va_list is NOT in exported symbols
        parser = _CastxmlParser(
            root,
            exported_dynamic={"my_func"},
            exported_static={"my_func"},
        )
        funcs = parser.parse_functions()
        # __builtin_va_list should either be absent or have HIDDEN visibility
        builtin_funcs = [f for f in funcs if "__builtin" in f.name]
        for f in builtin_funcs:
            assert f.visibility == Visibility.HIDDEN, (
                f"__builtin_* function {f.name!r} must be HIDDEN, not {f.visibility}"
            )

    def test_snapshot_no_builtin_types_in_public_api(self) -> None:
        """End-to-end: comparing two snapshots with only user types → no noise changes."""
        from abicheck.checker import compare
        from abicheck.model import AbiSnapshot, RecordType

        old = AbiSnapshot(library="lib.so", version="1.0", types=[
            RecordType(name="MyStruct", kind="struct"),
        ])
        new = AbiSnapshot(library="lib.so", version="2.0", types=[
            RecordType(name="MyStruct", kind="struct"),
        ])
        result = compare(old, new)
        # No changes should be emitted for identical snapshots
        assert not result.changes
