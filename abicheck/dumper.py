# Copyright 2026 Nikolay Petrov
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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
    AccessLevel,
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

# ---------------------------------------------------------------------------
# ELF-only mode: ABI-relevance filter
# ---------------------------------------------------------------------------
# Prefixes that identify GCC/compiler-internal symbols which may leak into
# .dynsym through statically-linked runtime (e.g. libgcc_s, SVML).
_GCC_INTERNAL_PREFIXES = (
    "ix86_",
    "x86_64_",
    "__cpu_model",
    "__cpu_features",
    "_ZGV",          # GCC SIMD vector variants (e.g. _ZGVbN2v_sin)
    "__svml_",       # Intel Short Vector Math Library
    "__libm_sse2_",
    "__libm_avx_",
)

# Prefixes that identify transitive C++ standard-library symbols which may
# appear in .dynsym via weak linkage (libstdc++ / libc++).
_STDLIB_PREFIXES = (
    "_ZNSt",              # std:: namespace members (libstdc++)
    "_ZNKSt",             # const std:: methods
    "_ZNSt3__1",          # libc++ inline-namespace __1
    "_ZdlPv",             # operator delete(void*)
    "_ZnwSt",             # operator new(std::size_t)
    "_ZnaSt",             # operator new[](std::size_t)
    "_ZdaPv",             # operator delete[](void*)
    "_ZTVN10__cxxabiv",   # vtables for RTTI (typeinfo infrastructure)
    "_ZTI",               # typeinfo objects
    "_ZTS",               # typeinfo strings
    "_ZSt",               # std:: global symbols (e.g. _ZSt4cout)
)


def _is_abi_relevant_symbol(name: str) -> bool:
    """Return False for symbols that are NOT part of the library's public ABI.

    Filters out (in ELF-only mode):
    1. GCC/compiler internal symbols (``ix86_*``, ``_ZGV*``, ``__svml_*`` …)
       that leak into ``.dynsym`` through a statically-linked runtime.
    2. Transitive C++ stdlib symbols (``_ZNSt*``, ``_ZTI*`` …) that appear
       in ``.dynsym`` via weak linkage from libstdc++ / libc++.
    3. Private C symbols that use ``__`` as a namespace separator
       (e.g. ``H5C__flush``, ``MPI__send``).  These follow an internal
       naming convention and are *not* part of the public API, even though
       they may have global ELF visibility.
    """
    if not name:
        return False

    # GCC/compiler internals
    for prefix in _GCC_INTERNAL_PREFIXES:
        if name.startswith(prefix):
            return False

    # Transitive libstdc++/libc++ symbols
    for prefix in _STDLIB_PREFIXES:
        if name.startswith(prefix):
            return False

    # Private C symbols with __ as a namespace separator
    # (e.g. H5C__flush_marked_entries, MPI__send).
    # Exclusions:
    #   • C++ mangled names start with _Z — handled separately by demangler.
    #   • System symbols start with __ or _ followed by an uppercase letter
    #     (POSIX/C reserved) — they are already excluded because they start
    #     with __ which would be caught if we checked name[0:2], but we want
    #     to be precise: we only filter names that have __ *after* the first
    #     two characters, meaning the library itself added the separator.
    if not name.startswith("_Z") and "__" in name[2:]:
        return False

    return True


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
            shndx = sym.entry.st_shndx
            if shndx in ("SHN_UNDEF", "SHN_ABS"):
                continue
            bind = sym.entry.st_info.bind
            vis = sym.entry.st_other.visibility
            if bind in ("STB_GLOBAL", "STB_WEAK") and vis not in _HIDDEN_VIS:
                name = sym.name
                if name and _is_abi_relevant_symbol(name):
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


def _cache_key(
    headers: list[Path],
    extra_includes: list[Path],
    compiler: str,
    *,
    gcc_path: str | None = None,
    gcc_prefix: str | None = None,
    gcc_options: str | None = None,
    sysroot: Path | None = None,
    nostdinc: bool = False,
    lang: str | None = None,
) -> str:
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
    # Include toolchain parameters so different cross-compilation configs
    # produce distinct cache entries
    h.update(f"gcc_path={gcc_path or ''}".encode())
    h.update(f"gcc_prefix={gcc_prefix or ''}".encode())
    h.update(f"gcc_options={gcc_options or ''}".encode())
    h.update(f"sysroot={sysroot or ''}".encode())
    h.update(f"nostdinc={nostdinc}".encode())
    h.update(f"lang={lang or ''}".encode())
    return h.hexdigest()


def _cache_path(key: str) -> Path:
    cache_dir = Path.home() / ".cache" / "abi_check" / "castxml"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{key}.xml"


def _castxml_dump(
    headers: list[Path],
    extra_includes: list[Path],
    compiler: str = "c++",
    *,
    gcc_path: str | None = None,
    gcc_prefix: str | None = None,
    gcc_options: str | None = None,
    sysroot: Path | None = None,
    nostdinc: bool = False,
    lang: str | None = None,
) -> Element:
    """Run castxml on headers and return parsed XML root.

    Args:
        compiler: "c++" (maps to g++) or "cc" (maps to gcc).
        gcc_path: Explicit path to a GCC/G++ cross-compiler binary.
        gcc_prefix: Cross-toolchain prefix (e.g. "aarch64-linux-gnu-").
        gcc_options: Extra compiler flags passed through to castxml.
        sysroot: Alternative system root directory.
        nostdinc: If True, do not search standard system include paths.
        lang: Force language ("C" or "C++").  If "C", aggregated header uses .h extension.
    """
    if not _castxml_available():
        raise RuntimeError(
            "castxml not found in PATH. Install with: apt install castxml  "
            "or  conda install -c conda-forge castxml"
        )

    # Check disk cache
    key = _cache_key(
        headers, extra_includes, compiler,
        gcc_path=gcc_path, gcc_prefix=gcc_prefix, gcc_options=gcc_options,
        sysroot=sysroot, nostdinc=nostdinc, lang=lang,
    )
    cached = _cache_path(key)
    if cached.exists():
        try:
            _cached_root = DefusedET.parse(str(cached)).getroot()
        except Exception:
            _cached_root = None
        if _cached_root is None:
            # Corrupt/unparseable cache entry — remove and re-run castxml
            cached.unlink(missing_ok=True)
        else:
            return cast(Element, _cached_root)

    # Map logical compiler name → castxml cc flag
    _cc_map = {"c++": "g++", "cc": "gcc", "g++": "g++", "gcc": "gcc",
               "clang++": "clang++", "clang": "clang"}

    # Determine the compiler binary to use
    if gcc_path:
        cc_bin = gcc_path
    elif gcc_prefix:
        # e.g. gcc_prefix="aarch64-linux-gnu-" → "aarch64-linux-gnu-g++" or "aarch64-linux-gnu-gcc"
        suffix = "g++" if compiler in ("c++", "g++", "clang++") else "gcc"
        cc_bin = f"{gcc_prefix}{suffix}"
    else:
        cc_bin = _cc_map.get(compiler, compiler)

    # Determine GNU vs MSVC dialect (inspect executable name, not substring,
    # to avoid misclassifying paths like "/opt/local/bin/g++")
    exe_name = Path(cc_bin).name
    cc_id = "msvc" if exe_name in ("cl", "cl.exe") else "gnu"

    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tmp:
        out_xml = Path(tmp.name)

    # Determine aggregate header extension: .h for C-only, .hpp for C++
    force_c = lang and lang.upper() == "C"
    agg_ext = ".h" if force_c else ".hpp"

    with tempfile.NamedTemporaryFile(suffix=agg_ext, mode="w", delete=False) as agg:
        for h in headers:
            agg.write(f'#include "{h.resolve()}"\n')
        agg_path = Path(agg.name)

    cmd = ["castxml", "--castxml-output=1",
           f"--castxml-cc-{cc_id}", cc_bin]
    for inc in extra_includes:
        cmd += ["-I", str(inc)]

    # Cross-compilation / toolchain flags
    if sysroot:
        cmd += [f"--sysroot={sysroot}"]
    if nostdinc:
        cmd += ["-nostdinc"]
    if gcc_options:
        # Split on whitespace, just like ABICC does
        cmd += gcc_options.split()

    # Workaround: castxml with --castxml-cc-gnu gcc auto-injects -std=gnu++17
    # which is rejected when parsing a .h file in C mode. Force explicit C
    # language and standard so castxml passes these to the compiler instead.
    if force_c and cc_id == "gnu":
        cmd += ["-x", "c", "-std=gnu11"]

    cmd += ["-o", str(out_xml), str(agg_path)]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(
                f"castxml failed (exit {result.returncode}):\n{result.stderr[:2000]}"
            )
        # Guard against castxml exiting 0 but not writing an output file,
        # or writing an empty/truncated file (happens with some header errors).
        if not out_xml.exists() or out_xml.stat().st_size == 0:
            stderr_snippet = result.stderr[:1000].strip()
            detail = f"\ncastxml stderr: {stderr_snippet}" if stderr_snippet else ""
            raise RuntimeError(
                f"castxml exited 0 but produced no output file (or empty file).{detail}"
            )
        # Parse the XML; propagate parse errors as RuntimeError with context.
        try:
            root = cast(Element, DefusedET.parse(str(out_xml)).getroot())
        except Exception as xml_exc:
            stderr_snippet = result.stderr[:1000].strip()
            detail = f"\ncastxml stderr: {stderr_snippet}" if stderr_snippet else ""
            raise RuntimeError(
                f"castxml produced invalid XML: {xml_exc}{detail}"
            ) from xml_exc
        # castxml may exit 0 but emit an empty root element when the header
        # fails to parse (no children = no type/function declarations captured).
        # This is a silent failure that would yield a false COMPATIBLE verdict.
        if len(root) == 0:
            stderr_snippet = result.stderr[:1000].strip()
            detail = f"\ncastxml stderr: {stderr_snippet}" if stderr_snippet else ""
            raise RuntimeError(
                f"castxml produced an empty XML document (no declarations found). "
                f"Check that the header paths are correct and the compiler can "
                f"parse them.{detail}"
            )
        # Save to cache
        shutil.copy2(str(out_xml), str(cached))
        return root
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

    def _pointer_depth(self, id_: str, depth: int = 0) -> int:
        """Count pointer nesting depth: T=0, T*=1, T**=2, etc."""
        if depth > 10:
            return 0
        el = self._resolve(id_)
        if el is None:
            return 0
        if el.tag == "PointerType":
            return 1 + self._pointer_depth(el.get("type", ""), depth + 1)
        if el.tag in ("CvQualifiedType", "Typedef"):
            return self._pointer_depth(el.get("type", ""), depth + 1)
        return 0

    @staticmethod
    def _access_level(el: Element) -> AccessLevel:
        """Map castxml 'access' attribute to AccessLevel enum."""
        raw = el.get("access", "public")
        if raw == "protected":
            return AccessLevel.PROTECTED
        if raw == "private":
            return AccessLevel.PRIVATE
        return AccessLevel.PUBLIC

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

    def _is_builtin_element(self, el: Element) -> bool:
        """Return True if element originates from a compiler built-in pseudo-file.

        Real castxml output: elements carry a ``file`` attribute (e.g. ``file="f0"``)
        pointing directly to a ``File`` element in the id-map — NOT via a separate
        ``Location`` element.  The compound ``location`` attribute (``"f0:0"``) is
        informational only and is NOT a map key.

        Known built-in file names emitted by castxml:
        - ``<builtin>``       (clang/castxml built-in declarations)
        - ``<built-in>``      (older castxml / GCC)
        - ``<command-line>``  (preprocessor command-line defines)
        """
        file_id = el.get("file", "")
        if not file_id:
            return False
        file_el = self._id_map.get(file_id)
        if file_el is None:
            return False
        fname = file_el.get("name", "")
        return fname in ("<builtin>", "<built-in>", "<command-line>")

    def parse_functions(self) -> list[Function]:
        funcs = []
        for el in self._root:
            if el.tag not in ("Function", "Method", "Constructor", "Destructor"):
                continue
            name = el.get("name", "")
            if not name:
                continue
            # Skip compiler built-ins and command-line synthetic declarations
            if self._is_builtin_element(el):
                continue
            mangled = el.get("mangled", "") or name  # C functions: use plain name
            ret_id = el.get("returns", "")
            ret_type = self._type_name(ret_id) if ret_id else "void"
            ret_ptr_depth = self._pointer_depth(ret_id) if ret_id else 0

            params = []
            for arg in el:
                if arg.tag == "Argument":
                    p_name = arg.get("name", "")
                    p_type_id = arg.get("type", "")
                    p_type = self._type_name(p_type_id)
                    p_depth = self._pointer_depth(p_type_id)
                    params.append(Param(name=p_name, type=p_type, pointer_depth=p_depth))

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
            is_deleted = el.get("deleted") == "1"
            # castxml emits inline="1" for inline functions/methods
            is_inline = el.get("inline") == "1"

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
                is_deleted=is_deleted,
                is_inline=is_inline,
                access=self._access_level(el),
                return_pointer_depth=ret_ptr_depth,
            ))
        return funcs

    def parse_variables(self) -> list[Variable]:
        variables = []
        for el in self._root:
            if el.tag != "Variable":
                continue
            name = el.get("name", "")
            # C-mode castxml does not emit a mangled attribute for C-linkage variables
            # (C has no name mangling); fall back to plain name as the symbol key,
            # mirroring the same pattern in parse_functions().
            mangled = el.get("mangled", "") or name
            if not mangled:
                continue
            # Skip compiler built-ins and command-line synthetic declarations
            if self._is_builtin_element(el):
                continue
            type_name = self._type_name(el.get("type", ""))
            # Use castxml structured attribute first; fall back to word-boundary
            # regex on type_name to avoid false positives on names like
            # "constructor_t", "const_iterator", "myconstant".
            is_const = (
                el.get("const") == "1"
                or bool(re.search(r"\bconst\b", type_name))
            )
            vis = self._visibility(mangled, name)
            variables.append(Variable(
                name=name, mangled=mangled, type=type_name, visibility=vis,
                is_const=is_const,
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
        if not name or el.get("artificial") == "1":
            return False
        if name.startswith("__"):
            return False
        # Skip compiler built-ins and command-line synthetic types
        if self._is_builtin_element(el):
            return False
        return True

    def _build_record_type(self, el: Any) -> RecordType:
        name = el.get("name", "")
        is_opaque = el.get("incomplete") == "1"
        return RecordType(
            name=name,
            kind=el.tag.lower(),
            size_bits=self._optional_int_attr(el, "size"),
            alignment_bits=self._optional_int_attr(el, "align"),
            fields=[] if is_opaque else self._parse_record_fields(el),
            bases=[] if is_opaque else [
                self._type_name(b.get("type", ""))
                for b in el if b.tag == "Base" and b.get("virtual") != "1"
            ],
            virtual_bases=[] if is_opaque else [
                self._type_name(b.get("type", ""))
                for b in el if b.tag == "Base" and b.get("virtual") == "1"
            ],
            vtable=[] if is_opaque else self._build_vtable(el.get("id", "")),
            is_union=el.tag == "Union",
            is_opaque=is_opaque,
        )

    def _optional_int_attr(self, el: Any, attr: str) -> int | None:
        raw = el.get(attr)
        return int(raw) if raw and raw.isdigit() else None

    def _parse_record_fields(self, el: Any) -> list[TypeField]:
        """Parse struct/class/union fields.

        castxml uses two layouts depending on version / output mode:
        - Inline children: ``<Struct><Field .../></Struct>``
        - Members attribute: ``<Struct members="_14 _15 _16 ..."/>`` (IDs resolved via id_map)

        We support both: first scan inline children, then fall back to the
        ``members`` attribute so we never miss fields in either format.
        """
        fields: list[TypeField] = []

        # Collect Field elements: inline children first
        field_elements: list[Any] = [c for c in el if c.tag == "Field"]

        # Fallback: resolve via space-separated "members" attribute
        if not field_elements:
            for mid in el.get("members", "").split():
                member_el = self._id_map.get(mid)
                if member_el is not None and member_el.tag == "Field":
                    field_elements.append(member_el)

        for child in field_elements:
            child_name = child.get("name", "")
            if not child_name:
                # Anonymous struct/union member — flatten its fields into parent
                fields.extend(self._expand_anonymous_field(child))
                continue
            bitfield_bits, is_bitfield = self._parse_bitfield_bits(child.get("bits"))
            fields.append(TypeField(
                name=child_name,
                type=self._type_name(child.get("type", "")),
                offset_bits=self._optional_int_attr(child, "offset"),
                is_bitfield=is_bitfield,
                bitfield_bits=bitfield_bits,
                access=self._access_level(child),
            ))
        return fields

    def _expand_anonymous_field(
        self, field_el: Any, _depth: int = 0, _outer_offset: int = 0
    ) -> list[TypeField]:
        """Flatten anonymous struct/union field into the parent's field list.

        In castxml output, anonymous unions/structs inside a struct appear as
        ``Field`` elements with ``name=""`` pointing to a ``Union`` or ``Struct``
        element.  We inline their named fields at the correct offset to prevent
        false ``TYPE_FIELD_REMOVED`` reports when a named field moves into an
        anonymous union (issue #58).

        ``_depth`` guards against malformed/cyclic XML (max nesting: 16).
        ``_outer_offset`` carries the accumulated offset from outer anonymous
        members so doubly-nested fields get correct absolute ``offset_bits``.
        """
        if _depth > 16:
            return []
        type_id = field_el.get("type", "")
        type_el = self._resolve(type_id)
        if type_el is None or type_el.tag not in ("Union", "Struct"):
            return []

        this_offset = _outer_offset + (self._optional_int_attr(field_el, "offset") or 0)
        result: list[TypeField] = []

        # Collect inner Field elements (inline children or members attribute)
        inner_fields: list[Any] = [c for c in type_el if c.tag == "Field"]
        if not inner_fields:
            for mid in type_el.get("members", "").split():
                member_el = self._id_map.get(mid)
                if member_el is not None and member_el.tag == "Field":
                    inner_fields.append(member_el)

        for inner in inner_fields:
            inner_name = inner.get("name", "")
            if not inner_name:
                # Doubly-nested anonymous member — recurse, passing accumulated offset
                result.extend(self._expand_anonymous_field(
                    inner, _depth + 1, _outer_offset=this_offset,
                ))
                continue
            inner_offset = self._optional_int_attr(inner, "offset") or 0
            bitfield_bits, is_bitfield = self._parse_bitfield_bits(inner.get("bits"))
            result.append(TypeField(
                name=inner_name,
                type=self._type_name(inner.get("type", "")),
                offset_bits=this_offset + inner_offset,
                is_bitfield=is_bitfield,
                bitfield_bits=bitfield_bits,
                access=self._access_level(inner),
            ))
        return result

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
            if self._is_builtin_element(el):
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
            if self._is_builtin_element(el):
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
    *,
    gcc_path: str | None = None,
    gcc_prefix: str | None = None,
    gcc_options: str | None = None,
    sysroot: Path | None = None,
    nostdinc: bool = False,
    lang: str | None = None,
) -> AbiSnapshot:
    """Create an AbiSnapshot from a .so + headers.

    Args:
        so_path: Path to the shared library (.so).
        headers: List of public header files to parse.
        extra_includes: Additional -I include directories for castxml.
        version: Version string for the snapshot (e.g. "1.2.3").
        compiler: Compiler frontend for castxml ("c++" or "cc").
        gcc_path: Explicit path to a GCC/G++ cross-compiler binary.
        gcc_prefix: Cross-toolchain prefix (e.g. "aarch64-linux-gnu-").
        gcc_options: Extra compiler flags passed through to castxml.
        sysroot: Alternative system root directory.
        nostdinc: If True, do not search standard system include paths.
        lang: Force language ("C" or "C++").

    Returns:
        AbiSnapshot with functions, variables, and types populated.
    """
    extra_includes = extra_includes or []
    exported_dynamic, exported_static = _pyelftools_exported_symbols(so_path)

    from .dwarf_unified import parse_dwarf
    from .elf_metadata import SymbolType, parse_elf_metadata

    elf_meta = parse_elf_metadata(so_path)
    # Use filtered ELF metadata symbols as authoritative surface for no-header mode.
    # This excludes version-definition aux symbols like LIBFOO_1.0.
    # Split into two sets: function-like symbols (for Function builder) and
    # object symbols (globals) — merged for CastxmlParser visibility check.
    # Split into func-like (for Function builder) and object (globals) sets.
    # Fall back to pyelftools set when elf_meta is unavailable.
    exported_dynamic_funcs: set[str] = exported_dynamic  # fallback
    exported_dynamic_objects: set[str] = set()
    if elf_meta is not None and elf_meta.symbols:
        exported_dynamic_funcs = {
            sym.name for sym in elf_meta.symbols
            if sym.sym_type in (SymbolType.FUNC, SymbolType.IFUNC, SymbolType.NOTYPE)
        }
        exported_dynamic_objects = {
            sym.name for sym in elf_meta.symbols
            if sym.sym_type == SymbolType.OBJECT
        }
        # Full set for CastxmlParser: determines PUBLIC vs ELF_ONLY visibility
        exported_dynamic = exported_dynamic_funcs | exported_dynamic_objects
    dwarf_meta, dwarf_adv = parse_dwarf(so_path)

    profile_hint: str | None = None
    if lang is not None:
        lu = lang.upper()
        if lu == "C":
            profile_hint = "c"
        elif lu in ("C++", "CPP"):
            profile_hint = "cpp"

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
                Function(
                    name=sym,
                    mangled=sym,
                    return_type="?",
                    visibility=Visibility.ELF_ONLY,
                    # Absence of Itanium _Z prefix is strong evidence of C linkage
                    is_extern_c=not sym.startswith("_Z"),
                )
                for sym in sorted(exported_dynamic_funcs)
            ],
            elf=elf_meta,
            dwarf=dwarf_meta,
            dwarf_advanced=dwarf_adv,
            elf_only_mode=True,
            platform="elf",
            language_profile=profile_hint,
        )
        return snapshot

    xml_root = _castxml_dump(
        headers, extra_includes, compiler=compiler,
        gcc_path=gcc_path, gcc_prefix=gcc_prefix, gcc_options=gcc_options,
        sysroot=sysroot, nostdinc=nostdinc, lang=lang,
    )
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
        platform="elf",
        language_profile=profile_hint,
    )
    return snapshot
