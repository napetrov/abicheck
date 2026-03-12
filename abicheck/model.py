"""ABI data model — shared across dumper, checker and reporter."""
from __future__ import annotations

import logging as _logging
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .dwarf_advanced import AdvancedDwarfMetadata
    from .dwarf_metadata import DwarfMetadata
    from .elf_metadata import ElfMetadata

_model_log = _logging.getLogger(__name__)


class Visibility(str, Enum):
    PUBLIC = "public"       # default visibility / exported
    HIDDEN = "hidden"       # __attribute__((visibility("hidden")))
    ELF_ONLY = "elf_only"   # present in ELF symbol table, not in headers


class AccessLevel(str, Enum):
    PUBLIC = "public"
    PROTECTED = "protected"
    PRIVATE = "private"


class ParamKind(str, Enum):
    VALUE = "value"
    POINTER = "pointer"
    REFERENCE = "reference"
    RVALUE_REF = "rvalue_ref"


@dataclass
class Param:
    name: str
    type: str
    kind: ParamKind = ParamKind.VALUE
    default: str | None = None  # has default value (value not preserved)
    pointer_depth: int = 0      # nesting: T=0, T*=1, T**=2
    is_restrict: bool = False   # restrict-qualified pointer parameter
    is_va_list: bool = False    # parameter is va_list (variadic argument list)


@dataclass
class Function:
    name: str                        # demangled
    mangled: str                     # mangled symbol name
    return_type: str
    params: list[Param] = field(default_factory=list)
    visibility: Visibility = Visibility.PUBLIC
    is_virtual: bool = False
    is_noexcept: bool = False
    is_extern_c: bool = False
    vtable_index: int | None = None
    source_location: str | None = None  # "header.h:42"
    is_static: bool = False
    is_const: bool = False        # const qualifier on this
    is_volatile: bool = False     # volatile qualifier on this
    is_pure_virtual: bool = False
    is_deleted: bool = False      # = delete; previously callable → BREAKING
    is_inline: bool = False       # inline keyword / attribute in header
    access: AccessLevel = AccessLevel.PUBLIC  # public/protected/private
    return_pointer_depth: int = 0  # T=0, T*=1, T**=2


@dataclass
class Variable:
    name: str
    mangled: str
    type: str
    visibility: Visibility = Visibility.PUBLIC
    source_location: str | None = None
    is_const: bool = False         # const-qualified type (write → SIGSEGV)
    value: str | None = None       # initial value (compile-time constant, if known)
    access: AccessLevel = AccessLevel.PUBLIC  # public/protected/private


@dataclass
class TypeField:
    name: str
    type: str
    offset_bits: int | None = None
    is_bitfield: bool = False
    bitfield_bits: int | None = None
    is_const: bool = False
    is_volatile: bool = False
    is_mutable: bool = False
    access: AccessLevel = AccessLevel.PUBLIC


@dataclass
class RecordType:
    """struct / class / union."""
    name: str
    kind: str  # "struct" | "class" | "union"
    size_bits: int | None = None
    alignment_bits: int | None = None
    fields: list[TypeField] = field(default_factory=list)
    bases: list[str] = field(default_factory=list)       # base class names
    virtual_bases: list[str] = field(default_factory=list)
    vtable: list[str] = field(default_factory=list)      # ordered vtable entries (mangled)
    source_location: str | None = None
    is_union: bool = False
    is_opaque: bool = False       # incomplete type (forward-decl only; was complete → BREAKING)


@dataclass
class EnumMember:
    name: str
    value: int


@dataclass
class EnumType:
    name: str
    members: list[EnumMember] = field(default_factory=list)
    underlying_type: str = "int"


@dataclass
class AbiSnapshot:
    """Complete ABI snapshot of one version of a library."""
    library: str                   # e.g. "libfoo.so.1"
    version: str                   # e.g. "1.2.3"
    functions: list[Function] = field(default_factory=list)
    variables: list[Variable] = field(default_factory=list)
    types: list[RecordType] = field(default_factory=list)
    elf: ElfMetadata | None = field(default=None)    # ELF dynamic/symbol metadata (Sprint 2)
    dwarf: DwarfMetadata | None = field(default=None)           # DWARF layout metadata (Sprint 3)
    dwarf_advanced: AdvancedDwarfMetadata | None = field(default=None)  # Sprint 4
    enums: list[EnumType] = field(default_factory=list)
    typedefs: dict[str, str] = field(default_factory=dict)  # alias -> underlying type name
    constants: dict[str, str] = field(default_factory=dict)  # #define / constexpr name -> value string
    elf_only_mode: bool = False  # True when dumped without headers (all functions are ELF_ONLY provenance)

    # Phase 3: binary format platform — detected from ELF/PE/MachO metadata.
    # None = unknown / not yet detected.
    # Populated by detect_platform() in pipeline or by the dumper.
    platform: str | None = None   # "elf" | "pe" | "macho" | None

    # Phase 4: language profile — detected from symbol mangling / extern "C" annotations.
    # None = unknown / mixed / not yet detected.
    # Populated by detect_profile() in pipeline or by the dumper.
    language_profile: str | None = None  # "c" | "cpp" | "sycl" | None

    # Indexes (built lazily)
    _func_by_mangled: dict[str, Function] | None = field(default=None, repr=False, compare=False)
    _var_by_mangled: dict[str, Variable] | None = field(default=None, repr=False, compare=False)
    _type_by_name: dict[str, RecordType] | None = field(default=None, repr=False, compare=False)

    def index(self) -> None:
        """Build lookup indexes. Uses first-wins for duplicate mangled names."""
        func_map: dict[str, Function] = {}
        for f in self.functions:
            if f.mangled in func_map:
                _model_log.warning(
                    "Duplicate mangled symbol skipped (first-wins): %s in %s@%s",
                    f.mangled, self.library, self.version,
                )
            else:
                func_map[f.mangled] = f
        self._func_by_mangled = func_map

        var_map: dict[str, Variable] = {}
        for v in self.variables:
            if v.mangled in var_map:
                _model_log.warning(
                    "Duplicate mangled variable skipped (first-wins): %s in %s@%s",
                    v.mangled, self.library, self.version,
                )
            else:
                var_map[v.mangled] = v
        self._var_by_mangled = var_map

        type_map: dict[str, RecordType] = {}
        for t in self.types:
            if t.name not in type_map:
                type_map[t.name] = t
        self._type_by_name = type_map

    @property
    def function_map(self) -> dict[str, Function]:
        if self._func_by_mangled is None:
            self.index()
        assert self._func_by_mangled is not None
        return self._func_by_mangled

    @property
    def variable_map(self) -> dict[str, Variable]:
        if self._var_by_mangled is None:
            self.index()
        assert self._var_by_mangled is not None
        return self._var_by_mangled

    def func_by_mangled(self, mangled: str) -> Function | None:
        return self.function_map.get(mangled)

    def var_by_mangled(self, mangled: str) -> Variable | None:
        return self.variable_map.get(mangled)

    def type_by_name(self, name: str) -> RecordType | None:
        if self._type_by_name is None:
            self.index()
        assert self._type_by_name is not None
        return self._type_by_name.get(name)
