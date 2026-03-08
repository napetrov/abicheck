"""Dumper — headers + .so → AbiSnapshot via castxml."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import warnings
from pathlib import Path
from typing import Any, cast
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as DefusedET

from .model import (
    AbiSnapshot,
    EnumMember,
    EnumType,
    Function,
    Param,
    RecordType,
    TypeField,
    Variable,
    Visibility,
)


def _castxml_available() -> bool:
    return shutil.which("castxml") is not None


_HIDDEN_VIS = frozenset({"STV_HIDDEN", "STV_INTERNAL"})


def _pyelftools_exported_symbols(so_path: Path) -> tuple[set[str], set[str]]:
    """Return (exported_dynamic, exported_static) sets of mangled symbol names.

    Uses pyelftools (pure Python) instead of shelling out to readelf.
    - exported_dynamic: symbols from .dynsym, truly exported via ELF
    - exported_static: symbols from .symtab (all symbols including static)
    """
    from elftools.common.exceptions import ELFError
    from elftools.elf.elffile import ELFFile
    from elftools.elf.sections import SymbolTableSection

    def _extract_symbols(elf: Any, section_name: str) -> set[str]:
        syms: set[str] = set()
        section = elf.get_section_by_name(section_name)
        if section is None or not isinstance(section, SymbolTableSection):
            return syms
        for sym in section.iter_symbols():
            if sym.entry.st_shndx == "SHN_UNDEF":
                continue
            bind = sym.entry.st_info.bind
            vis = sym.entry.st_other.visibility
            if bind in ("STB_GLOBAL", "STB_WEAK") and vis not in _HIDDEN_VIS:
                name = sym.name
                if name:
                    syms.add(name)
        return syms

    try:
        with open(so_path, "rb") as f:
            elf: Any = ELFFile(f)  # type: ignore[no-untyped-call]
            exported_dynamic = _extract_symbols(elf, ".dynsym")
            try:
                exported_static = _extract_symbols(elf, ".symtab")
            except (ELFError, OSError):
                exported_static = set(exported_dynamic)
            return exported_dynamic, exported_static
    except (ELFError, OSError) as exc:
        raise RuntimeError(f"Failed to parse ELF file {so_path}: {exc}") from exc


def _cache_key(headers: list[Path], extra_includes: list[Path], compiler: str) -> str:
    h = hashlib.sha256()
    for p in sorted(str(x.resolve()) for x in headers):
        h.update(p.encode())
        try:
            h.update(str(os.path.getmtime(p)).encode())
        except OSError:
            pass
    # Also hash mtimes of files in extra_include dirs (catches most transitive changes)
    for inc_dir in sorted(str(x) for x in extra_includes):
        inc_path = Path(inc_dir)
        h.update(inc_dir.encode())
        if inc_path.is_dir():
            for f in sorted(inc_path.rglob("*.h")) + sorted(inc_path.rglob("*.hpp")):
                try:
                    h.update(str(f).encode())
                    h.update(str(f.stat().st_mtime).encode())
                except OSError:
                    pass
    h.update(compiler.encode())
    return h.hexdigest()


def _cache_path(key: str) -> Path:
    cache_dir = Path.home() / ".cache" / "abi_check" / "castxml"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{key}.xml"


def _castxml_dump(headers: list[Path], extra_includes: list[Path],
                  compiler: str = "c++") -> Element:
    """Run castxml on headers and return parsed XML root.

    Args:
        compiler: "c++" (maps to g++) or "cc" (maps to gcc).
    """
    if not _castxml_available():
        raise RuntimeError(
            "castxml not found in PATH. Install with: apt install castxml  "
            "or  conda install -c conda-forge castxml"
        )

    # Check disk cache
    key = _cache_key(headers, extra_includes, compiler)
    cached = _cache_path(key)
    if cached.exists():
        return cast(Element, DefusedET.parse(str(cached)).getroot())

    # Map logical compiler name → castxml cc flag
    _cc_map = {"c++": "g++", "cc": "gcc", "g++": "g++", "gcc": "gcc",
               "clang++": "clang++", "clang": "clang"}
    cc_bin = _cc_map.get(compiler, compiler)
    # Determine GNU vs MSVC dialect
    cc_id = "gnu" if "cl" not in cc_bin else "msvc"

    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tmp:
        out_xml = Path(tmp.name)

    # Aggregate header: use .hpp to force C++ mode in castxml
    with tempfile.NamedTemporaryFile(suffix=".hpp", mode="w", delete=False) as agg:
        for h in headers:
            agg.write(f'#include "{h.resolve()}"\n')
        agg_path = Path(agg.name)

    cmd = ["castxml", "--castxml-output=1",
           f"--castxml-cc-{cc_id}", cc_bin]
    for inc in extra_includes:
        cmd += ["-I", str(inc)]
    cmd += ["-o", str(out_xml), str(agg_path)]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(
                f"castxml failed (exit {result.returncode}):\n{result.stderr[:2000]}"
            )
        # Save to cache
        shutil.copy2(str(out_xml), str(cached))
        return cast(Element, DefusedET.parse(str(out_xml)).getroot())
    finally:
        agg_path.unlink(missing_ok=True)
        out_xml.unlink(missing_ok=True)


def _parse_vtable_index(vi_str: str | None) -> int | None:
    """Parse vtable_index attribute, returning None for missing/invalid values."""
    if vi_str is None:
        return None
    stripped = vi_str.lstrip("-")
    return int(vi_str) if stripped.isdigit() else None


def _vt_sort_key(item: tuple[int | None, str]) -> tuple[int, int]:
    vi, _ = item
    return (0, vi) if vi is not None else (1, 0)


class _CastxmlParser:
    """Parse castxml XML into ABI model objects."""

    def __init__(self, root: Element, exported_dynamic: set[str],
                 exported_static: set[str]):
        self._root = root
        self._exported_dynamic = exported_dynamic
        self._exported_static = exported_static
        self._id_map: dict[str, Element] = {}
        self._virtual_methods_by_class: dict[str, list[Element]] = {}
        self._build_id_map()

    def _build_id_map(self) -> None:
        for el in self._root:
            eid = el.get("id")
            if eid:
                self._id_map[eid] = el
        # Build class_id → list of virtual Method/Destructor elements
        # In castxml output, methods are top-level elements with a "context" attribute
        for el in self._root:
            if el.tag in ("Method", "Destructor") and el.get("virtual") == "1":
                ctx = el.get("context")
                if ctx:
                    self._virtual_methods_by_class.setdefault(ctx, []).append(el)

    def _resolve(self, id_: str) -> Element | None:
        return self._id_map.get(id_)

    def _type_name(self, id_: str, depth: int = 0) -> str:
        if depth > 10:
            return "?"
        el = self._resolve(id_)
        if el is None:
            return "?"
        tag = el.tag
        if tag in ("FundamentalType", "Enumeration"):
            return el.get("name", "?")
        if tag == "PointerType":
            return self._type_name(el.get("type", ""), depth + 1) + "*"
        if tag == "ReferenceType":
            return self._type_name(el.get("type", ""), depth + 1) + "&"
        if tag == "RValueReferenceType":
            return self._type_name(el.get("type", ""), depth + 1) + "&&"
        if tag == "CvQualifiedType":
            base = self._type_name(el.get("type", ""), depth + 1)
            const = "const " if el.get("const") == "1" else ""
            return f"{const}{base}"
        if tag in ("Struct", "Class", "Union"):
            return el.get("name", "?")
        if tag == "Typedef":
            return el.get("name", "?")
        if tag == "ArrayType":
            max_ = el.get("max", "")
            base = self._type_name(el.get("type", ""), depth + 1)
            return f"{base}[{max_}]" if max_ else f"{base}[]"
        return el.get("name", tag)

    def _visibility(self, mangled: str, name: str = "") -> Visibility:
        """Determine visibility based on ELF symbol tables."""
        # Check dynamic symbols (.dynsym) — truly exported
        if mangled and mangled in self._exported_dynamic:
            return Visibility.PUBLIC
        if name and name in self._exported_dynamic:
            return Visibility.PUBLIC
        # Check all symbols (.symtab) — present in ELF but not exported
        if mangled and mangled in self._exported_static:
            return Visibility.ELF_ONLY
        if name and name in self._exported_static:
            return Visibility.ELF_ONLY
        return Visibility.HIDDEN

    def parse_functions(self) -> list[Function]:
        funcs = []
        for el in self._root:
            if el.tag not in ("Function", "Method", "Constructor", "Destructor"):
                continue
            name = el.get("name", "")
            if not name:
                continue
            mangled = el.get("mangled", "") or name  # C functions: use plain name
            ret_id = el.get("returns", "")
            ret_type = self._type_name(ret_id) if ret_id else "void"

            params = []
            for arg in el:
                if arg.tag == "Argument":
                    p_name = arg.get("name", "")
                    p_type = self._type_name(arg.get("type", ""))
                    params.append(Param(name=p_name, type=p_type))

            vis = self._visibility(el.get("mangled", ""), name)
            is_virtual = el.get("virtual") == "1"
            noexcept_re = re.search(r"noexcept", el.get("attributes", ""))
            vtable_index = _parse_vtable_index(el.get("vtable_index")) if is_virtual else None

            # Detect extern "C": explicit extern attribute OR no mangled name (C linkage)
            raw_mangled = el.get("mangled", "")
            is_extern_c = (
                el.get("extern") == "1"
                or not raw_mangled  # C functions have no mangled name
            )

            loc_id = el.get("location", "")
            loc_el = self._id_map.get(loc_id)
            source_loc = None
            if loc_el is not None:
                file_id = loc_el.get("file", "")
                file_el = self._id_map.get(file_id)
                fname = file_el.get("name", "") if file_el is not None else ""
                line = loc_el.get("line", "")
                source_loc = f"{fname}:{line}" if fname else None

            is_static = el.get("static") == "1"
            is_const = el.get("const") == "1"
            is_volatile = el.get("volatile") == "1"
            is_pure_virtual = el.get("pure_virtual") == "1"

            funcs.append(Function(
                name=name,
                mangled=mangled,
                return_type=ret_type,
                params=params,
                visibility=vis,
                is_virtual=is_virtual,
                is_noexcept=bool(noexcept_re),
                is_extern_c=is_extern_c,
                vtable_index=vtable_index,
                source_location=source_loc,
                is_static=is_static,
                is_const=is_const,
                is_volatile=is_volatile,
                is_pure_virtual=is_pure_virtual,
            ))
        return funcs

    def parse_variables(self) -> list[Variable]:
        variables = []
        for el in self._root:
            if el.tag != "Variable":
                continue
            mangled = el.get("mangled", "")
            if not mangled:
                continue
            name = el.get("name", mangled)
            type_name = self._type_name(el.get("type", ""))
            vis = self._visibility(mangled)
            variables.append(Variable(
                name=name, mangled=mangled, type=type_name, visibility=vis,
            ))
        return variables

    def parse_types(self) -> list[RecordType]:
        types = []
        for el in self._root:
            if not self._is_public_record_type(el):
                continue
            types.append(self._build_record_type(el))
        return types

    def _is_public_record_type(self, el: Any) -> bool:
        if el.tag not in ("Struct", "Class", "Union"):
            return False
        name = el.get("name", "")
        if not name or el.get("incomplete") == "1" or el.get("artificial") == "1":
            return False
        return not name.startswith("__")

    def _build_record_type(self, el: Any) -> RecordType:
        name = el.get("name", "")
        return RecordType(
            name=name,
            kind=el.tag.lower(),
            size_bits=self._optional_int_attr(el, "size"),
            alignment_bits=self._optional_int_attr(el, "align"),
            fields=self._parse_record_fields(el),
            bases=[
                self._type_name(b.get("type", ""))
                for b in el if b.tag == "Base" and b.get("virtual") != "1"
            ],
            virtual_bases=[
                self._type_name(b.get("type", ""))
                for b in el if b.tag == "Base" and b.get("virtual") == "1"
            ],
            vtable=self._build_vtable(el.get("id", "")),
            is_union=el.tag == "Union",
        )

    def _optional_int_attr(self, el: Any, attr: str) -> int | None:
        raw = el.get(attr)
        return int(raw) if raw and raw.isdigit() else None

    def _parse_record_fields(self, el: Any) -> list[TypeField]:
        fields: list[TypeField] = []
        for child in el:
            if child.tag != "Field":
                continue
            bitfield_bits, is_bitfield = self._parse_bitfield_bits(child.get("bits"))
            fields.append(TypeField(
                name=child.get("name", ""),
                type=self._type_name(child.get("type", "")),
                offset_bits=self._optional_int_attr(child, "offset"),
                is_bitfield=is_bitfield,
                bitfield_bits=bitfield_bits,
            ))
        return fields

    @staticmethod
    def _parse_bitfield_bits(bits_raw: str | None) -> tuple[int | None, bool]:
        try:
            bitfield_bits = int(bits_raw) if bits_raw is not None else None
        except ValueError:
            return (None, False)
        return (bitfield_bits, bitfield_bits is not None)

    def _build_vtable(self, class_id: str) -> list[str]:
        virtual_methods = self._collect_virtual_methods(class_id)
        virtual_methods.sort(key=_vt_sort_key)
        return [m for _, m in virtual_methods]

    def _collect_virtual_methods(
        self, cid: str, seen: set[str] | None = None,
    ) -> list[tuple[int | None, str]]:
        if seen is None:
            seen = set()
        if cid in seen:
            return []
        seen.add(cid)
        class_el = self._id_map.get(cid)
        if class_el is None:
            return []

        # Use a dict keyed by vtable_index so derived methods overwrite base entries,
        # preventing duplicate slots when a derived class overrides a virtual method.
        slots: dict[int | None, str] = {}
        for base in class_el:
            if base.tag != "Base":
                continue
            base_type_el = self._resolve(base.get("type", ""))
            if base_type_el is not None:
                for idx, name in self._collect_virtual_methods(base_type_el.get("id", ""), seen):
                    slots[idx] = name

        for method_el in self._virtual_methods_by_class.get(cid, []):
            mangled_name = method_el.get("mangled", "")
            if not mangled_name:
                continue
            idx = _parse_vtable_index(method_el.get("vtable_index"))
            slots[idx] = mangled_name

        return list(slots.items())


    def parse_enums(self) -> list[EnumType]:
        enums = []
        for el in self._root:
            if el.tag != "Enumeration":
                continue
            name = el.get("name", "")
            if not name or name.startswith("__"):
                continue
            members = []
            for child in el:
                if child.tag == "EnumValue":
                    m_name = child.get("name", "")
                    m_val_str = child.get("init", "0")
                    try:
                        m_val = int(m_val_str)
                    except ValueError:
                        m_val = 0
                    members.append(EnumMember(name=m_name, value=m_val))
            enums.append(EnumType(name=name, members=members))
        return enums

    def _underlying_type_name(self, id_: str, depth: int = 0) -> str:
        """Follow typedef chains to the concrete base type name."""
        if depth > 20:
            return "?"
        el = self._resolve(id_)
        if el is None:
            return "?"
        if el.tag == "Typedef":
            return self._underlying_type_name(el.get("type", ""), depth + 1)
        return self._type_name(id_)

    def parse_typedefs(self) -> dict[str, str]:
        typedefs: dict[str, str] = {}
        for el in self._root:
            if el.tag != "Typedef":
                continue
            name = el.get("name", "")
            if not name:
                continue
            type_id = el.get("type", "")
            # Flatten typedef chains: alias → alias2 → int  stored as  alias → int
            underlying = self._underlying_type_name(type_id) if type_id else "?"
            typedefs[name] = underlying
        return typedefs


def dump(
    so_path: Path,
    headers: list[Path],
    extra_includes: list[Path] | None = None,
    version: str = "unknown",
    compiler: str = "c++",
) -> AbiSnapshot:
    """Create an AbiSnapshot from a .so + headers.

    Args:
        so_path: Path to the shared library (.so).
        headers: List of public header files to parse.
        extra_includes: Additional -I include directories for castxml.
        version: Version string for the snapshot (e.g. "1.2.3").
        compiler: Compiler frontend for castxml ("c++" or "cc").

    Returns:
        AbiSnapshot with functions, variables, and types populated.
    """
    extra_includes = extra_includes or []
    exported_dynamic, exported_static = _pyelftools_exported_symbols(so_path)

    from .dwarf_unified import parse_dwarf
    from .elf_metadata import parse_elf_metadata

    elf_meta = parse_elf_metadata(so_path)
    dwarf_meta, dwarf_adv = parse_dwarf(so_path)

    if not headers:
        warnings.warn(
            "No headers provided — only ELF-exported symbols will be captured; "
            "type information will be missing.",
            UserWarning,
            stacklevel=2,
        )
        snapshot = AbiSnapshot(
            library=so_path.name,
            version=version,
            functions=[
                Function(name=sym, mangled=sym, return_type="?",
                         visibility=Visibility.ELF_ONLY)
                for sym in sorted(exported_dynamic)
            ],
            elf=elf_meta,
            dwarf=dwarf_meta,
            dwarf_advanced=dwarf_adv,
        )
        return snapshot

    xml_root = _castxml_dump(headers, extra_includes, compiler=compiler)
    parser = _CastxmlParser(xml_root, exported_dynamic, exported_static)

    snapshot = AbiSnapshot(
        library=so_path.name,
        version=version,
        functions=parser.parse_functions(),
        variables=parser.parse_variables(),
        types=parser.parse_types(),
        enums=parser.parse_enums(),
        typedefs=parser.parse_typedefs(),
        elf=elf_meta,
        dwarf=dwarf_meta,
        dwarf_advanced=dwarf_adv,
    )
    return snapshot
