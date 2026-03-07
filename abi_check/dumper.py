"""Dumper — headers + .so → AbiSnapshot via castxml."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import warnings
from pathlib import Path
from typing import List, Optional
from xml.etree import ElementTree as ET

from .model import (
    AbiSnapshot, Function, Param, ParamKind, RecordType,
    TypeField, Variable, Visibility,
)


def _castxml_available() -> bool:
    return shutil.which("castxml") is not None


def _readelf_exported_symbols(so_path: Path) -> set[str]:
    """Return set of exported (globally visible) mangled symbol names from .so.

    Includes STV_DEFAULT and STV_PROTECTED symbols (both are exported and
    ABI-relevant). Raises RuntimeError on readelf failure to prevent silent
    empty-set bugs that would cause every symbol to appear removed.
    """
    result = subprocess.run(
        ["readelf", "--wide", "--dyn-syms", str(so_path)],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"readelf failed (exit {result.returncode}) on {so_path}:\n"
            f"{result.stderr[:1000]}"
        )
    exported: set[str] = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        # readelf --dyn-syms output: Num Value Size Type Bind Vis Ndx Name
        if len(parts) < 8:
            continue
        bind = parts[4]
        vis = parts[5]
        ndx = parts[6]
        name = parts[7].split("@")[0]  # strip version suffix (e.g. GLIBC_2.17)
        # Include DEFAULT and PROTECTED — both are exported and ABI-relevant
        if bind in ("GLOBAL", "WEAK") and vis in ("DEFAULT", "PROTECTED") and ndx != "UND":
            exported.add(name)
    return exported


def _castxml_dump(headers: List[Path], extra_includes: List[Path],
                  compiler: str = "c++") -> ET.Element:
    """Run castxml on headers and return parsed XML root.

    Args:
        compiler: "c++" (maps to g++) or "cc" (maps to gcc).
    """
    if not _castxml_available():
        raise RuntimeError(
            "castxml not found in PATH. Install with: apt install castxml  "
            "or  conda install -c conda-forge castxml"
        )

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
        return ET.parse(str(out_xml)).getroot()
    finally:
        agg_path.unlink(missing_ok=True)
        out_xml.unlink(missing_ok=True)


class _CastxmlParser:
    """Parse castxml XML into ABI model objects."""

    def __init__(self, root: ET.Element, exported_symbols: set[str]):
        self._root = root
        self._exported = exported_symbols
        self._id_map: dict[str, ET.Element] = {}
        self._build_id_map()

    def _build_id_map(self) -> None:
        for el in self._root:
            eid = el.get("id")
            if eid:
                self._id_map[eid] = el

    def _resolve(self, id_: str) -> Optional[ET.Element]:
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
            min_ = el.get("min", "0")
            max_ = el.get("max", "")
            base = self._type_name(el.get("type", ""), depth + 1)
            return f"{base}[{max_}]" if max_ else f"{base}[]"
        return el.get("name", tag)

    def _visibility(self, mangled: str, name: str = "") -> Visibility:
        """Check if symbol is exported: try mangled first, then plain name."""
        if mangled and mangled in self._exported:
            return Visibility.PUBLIC
        if name and name in self._exported:
            return Visibility.PUBLIC
        return Visibility.HIDDEN

    def parse_functions(self) -> List[Function]:
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

            loc_id = el.get("location", "")
            loc_el = self._id_map.get(loc_id)
            source_loc = None
            if loc_el is not None:
                file_id = loc_el.get("file", "")
                file_el = self._id_map.get(file_id)
                fname = file_el.get("name", "") if file_el is not None else ""
                line = loc_el.get("line", "")
                source_loc = f"{fname}:{line}" if fname else None

            funcs.append(Function(
                name=name,
                mangled=mangled,
                return_type=ret_type,
                params=params,
                visibility=vis,
                is_virtual=is_virtual,
                is_noexcept=bool(noexcept_re),
                source_location=source_loc,
            ))
        return funcs

    def parse_variables(self) -> List[Variable]:
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

    def parse_types(self) -> List[RecordType]:
        types = []
        for el in self._root:
            if el.tag not in ("Struct", "Class", "Union"):
                continue
            name = el.get("name", "")
            if not name or name.startswith("_"):
                continue
            size_str = el.get("size")
            size_bits = int(size_str) if size_str and size_str.isdigit() else None

            fields = []
            for child in el:
                if child.tag == "Field":
                    f_name = child.get("name", "")
                    f_type = self._type_name(child.get("type", ""))
                    off_str = child.get("offset")
                    offset = int(off_str) if off_str and off_str.isdigit() else None
                    fields.append(TypeField(name=f_name, type=f_type, offset_bits=offset))

            bases = [
                self._type_name(b.get("type", ""))
                for b in el if b.tag == "Base" and b.get("virtual") != "1"
            ]
            virtual_bases = [
                self._type_name(b.get("type", ""))
                for b in el if b.tag == "Base" and b.get("virtual") == "1"
            ]

            types.append(RecordType(
                name=name,
                kind=el.tag.lower(),
                size_bits=size_bits,
                fields=fields,
                bases=bases,
                virtual_bases=virtual_bases,
            ))
        return types


def dump(
    so_path: Path,
    headers: List[Path],
    extra_includes: Optional[List[Path]] = None,
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
    exported = _readelf_exported_symbols(so_path)

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
                for sym in sorted(exported)
            ],
        )
        return snapshot

    xml_root = _castxml_dump(headers, extra_includes, compiler=compiler)
    parser = _CastxmlParser(xml_root, exported)

    snapshot = AbiSnapshot(
        library=so_path.name,
        version=version,
        functions=parser.parse_functions(),
        variables=parser.parse_variables(),
        types=parser.parse_types(),
    )
    return snapshot
