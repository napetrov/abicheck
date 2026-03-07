"""ABI data model — shared across dumper, checker and reporter."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


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
    default: Optional[str] = None  # has default value (value not preserved)


@dataclass
class Function:
    name: str                        # demangled
    mangled: str                     # mangled symbol name
    return_type: str
    params: List[Param] = field(default_factory=list)
    visibility: Visibility = Visibility.PUBLIC
    is_virtual: bool = False
    is_noexcept: bool = False
    vtable_index: Optional[int] = None
    source_location: Optional[str] = None  # "header.h:42"


@dataclass
class Variable:
    name: str
    mangled: str
    type: str
    visibility: Visibility = Visibility.PUBLIC
    source_location: Optional[str] = None


@dataclass
class TypeField:
    name: str
    type: str
    offset_bits: Optional[int] = None


@dataclass
class RecordType:
    """struct / class / union."""
    name: str
    kind: str  # "struct" | "class" | "union"
    size_bits: Optional[int] = None
    fields: List[TypeField] = field(default_factory=list)
    bases: List[str] = field(default_factory=list)       # base class names
    virtual_bases: List[str] = field(default_factory=list)
    vtable: List[str] = field(default_factory=list)      # ordered vtable entries (mangled)
    source_location: Optional[str] = None


@dataclass
class AbiSnapshot:
    """Complete ABI snapshot of one version of a library."""
    library: str                   # e.g. "libfoo.so.1"
    version: str                   # e.g. "1.2.3"
    functions: List[Function] = field(default_factory=list)
    variables: List[Variable] = field(default_factory=list)
    types: List[RecordType] = field(default_factory=list)

    # Indexes (built lazily)
    _func_by_mangled: Optional[dict] = field(default=None, repr=False)
    _var_by_mangled: Optional[dict] = field(default=None, repr=False)
    _type_by_name: Optional[dict] = field(default=None, repr=False)

    def index(self) -> None:
        self._func_by_mangled = {f.mangled: f for f in self.functions}
        self._var_by_mangled = {v.mangled: v for v in self.variables}
        self._type_by_name = {t.name: t for t in self.types}

    def func_by_mangled(self, mangled: str) -> Optional[Function]:
        if self._func_by_mangled is None:
            self.index()
        return self._func_by_mangled.get(mangled)

    def var_by_mangled(self, mangled: str) -> Optional[Variable]:
        if self._var_by_mangled is None:
            self.index()
        return self._var_by_mangled.get(mangled)

    def type_by_name(self, name: str) -> Optional[RecordType]:
        if self._type_by_name is None:
            self.index()
        return self._type_by_name.get(name)
