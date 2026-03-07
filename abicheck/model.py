"""ABI data model — shared across dumper, checker and reporter."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Visibility(str, Enum):
    PUBLIC = "public"       # default visibility / exported
    HIDDEN = "hidden"       # __attribute__((visibility("hidden")))
    ELF_ONLY = "elf_only"   # present in ELF symbol table, not in headers


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


@dataclass
class Variable:
    name: str
    mangled: str
    type: str
    visibility: Visibility = Visibility.PUBLIC
    source_location: str | None = None


@dataclass
class TypeField:
    name: str
    type: str
    offset_bits: int | None = None


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


@dataclass
class AbiSnapshot:
    """Complete ABI snapshot of one version of a library."""
    library: str                   # e.g. "libfoo.so.1"
    version: str                   # e.g. "1.2.3"
    functions: list[Function] = field(default_factory=list)
    variables: list[Variable] = field(default_factory=list)
    types: list[RecordType] = field(default_factory=list)

    # Indexes (built lazily)
    _func_by_mangled: dict | None = field(default=None, repr=False, compare=False)
    _var_by_mangled: dict | None = field(default=None, repr=False, compare=False)
    _type_by_name: dict | None = field(default=None, repr=False, compare=False)

    def index(self) -> None:
        self._func_by_mangled = {f.mangled: f for f in self.functions}
        self._var_by_mangled = {v.mangled: v for v in self.variables}
        self._type_by_name = {t.name: t for t in self.types}

    @property
    def function_map(self) -> dict:
        if self._func_by_mangled is None:
            self.index()
        return self._func_by_mangled

    @property
    def variable_map(self) -> dict:
        if self._var_by_mangled is None:
            self.index()
        return self._var_by_mangled

    def func_by_mangled(self, mangled: str) -> Function | None:
        return self.function_map.get(mangled)

    def var_by_mangled(self, mangled: str) -> Variable | None:
        return self.variable_map.get(mangled)

    def type_by_name(self, name: str) -> RecordType | None:
        if self._type_by_name is None:
            self.index()
        return self._type_by_name.get(name)
