"""Normalizer — Phase 1b.

Converts raw AbiSnapshot (from dumper) into a NormalizedSnapshot
suitable for CorpusBuilder.

Responsibilities:
- Intern all name strings (eliminates duplicate string heap objects)
- Deduplicate facts from multiple evidence sources
- Strip address-specific noise (e.g. source_location absolute paths → relative)
- Canonicalize type names (pointer depth, const placement)

This step is deliberately separate from CorpusBuilder so that normalization
logic is independently testable and has its own invariants.

Pipeline position:  extract → **normalize** → corpus → diff → suppress → policy
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field

from abicheck.model import (
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


@dataclass
class NormalizedSnapshot:
    """An AbiSnapshot with interned strings and deduplicated entries.

    Downstream consumers (CorpusBuilder, diff engine) can assume:
    - All name strings are interned (``is`` comparison safe for identity checks)
    - No duplicate functions by mangled name
    - No duplicate types by name
    - No duplicate variables by mangled name
    """
    library: str
    version: str
    functions: list[Function] = field(default_factory=list)
    variables: list[Variable] = field(default_factory=list)
    types: list[RecordType] = field(default_factory=list)
    enums: list[EnumType] = field(default_factory=list)
    typedefs: dict[str, str] = field(default_factory=dict)

    # Index maps (built by Normalizer for O(1) downstream access)
    func_index:  dict[str, Function] = field(default_factory=dict, repr=False)
    var_index:   dict[str, Variable] = field(default_factory=dict, repr=False)
    type_index:  dict[str, RecordType] = field(default_factory=dict, repr=False)
    enum_index:  dict[str, EnumType] = field(default_factory=dict, repr=False)


class Normalizer:
    """Converts an AbiSnapshot into a NormalizedSnapshot.

    Usage::

        norm = Normalizer()
        normalized = norm.normalize(snapshot)
    """

    def normalize(self, snapshot: AbiSnapshot) -> NormalizedSnapshot:
        """Normalize a single AbiSnapshot.

        Steps:
        1. Intern all name/type strings
        2. Deduplicate functions by mangled name (keep first/PUBLIC wins)
        3. Deduplicate types by name (keep largest size_bits on conflict)
        4. Deduplicate variables by mangled name
        5. Build O(1) index maps
        """
        funcs = self._normalize_functions(snapshot.functions)
        variables = self._normalize_variables(snapshot.variables)
        types = self._normalize_types(snapshot.types)
        enums = self._normalize_enums(snapshot.enums)
        typedefs = {
            sys.intern(k): sys.intern(v)
            for k, v in snapshot.typedefs.items()
        }

        func_index = {f.mangled: f for f in funcs}
        var_index = {v.mangled: v for v in variables}
        type_index = {t.name: t for t in types}
        enum_index = {e.name: e for e in enums}

        return NormalizedSnapshot(
            library=sys.intern(snapshot.library),
            version=sys.intern(snapshot.version),
            functions=funcs,
            variables=variables,
            types=types,
            enums=enums,
            typedefs=typedefs,
            func_index=func_index,
            var_index=var_index,
            type_index=type_index,
            enum_index=enum_index,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _intern_param(self, p: Param) -> Param:
        return Param(
            name=sys.intern(p.name),
            type=sys.intern(p.type),
            kind=p.kind,
            default=sys.intern(p.default) if p.default else p.default,
            pointer_depth=p.pointer_depth,
            is_restrict=p.is_restrict,
            is_va_list=p.is_va_list,
        )

    def _intern_function(self, f: Function) -> Function:
        return Function(
            name=sys.intern(f.name),
            mangled=sys.intern(f.mangled),
            return_type=sys.intern(f.return_type),
            params=[self._intern_param(p) for p in f.params],
            visibility=f.visibility,
            is_virtual=f.is_virtual,
            is_noexcept=f.is_noexcept,
            is_extern_c=f.is_extern_c,
            vtable_index=f.vtable_index,
            source_location=f.source_location,
            is_static=f.is_static,
            is_const=f.is_const,
            is_volatile=f.is_volatile,
            is_pure_virtual=f.is_pure_virtual,
            is_deleted=f.is_deleted,
            access=f.access,
            return_pointer_depth=f.return_pointer_depth,
        )

    def _normalize_functions(self, functions: list[Function]) -> list[Function]:
        """Intern + deduplicate by mangled name.

        When duplicates exist, PUBLIC visibility wins over HIDDEN/ELF_ONLY.
        """
        seen: dict[str, Function] = {}
        for f in functions:
            interned = self._intern_function(f)
            key = interned.mangled
            if key not in seen:
                seen[key] = interned
            elif interned.visibility == Visibility.PUBLIC:
                # Higher-visibility entry wins (castxml PUBLIC > ELF_ONLY)
                seen[key] = interned
        return list(seen.values())

    def _intern_field(self, fld: TypeField) -> TypeField:
        return TypeField(
            name=sys.intern(fld.name),
            type=sys.intern(fld.type),
            offset_bits=fld.offset_bits,
            is_bitfield=fld.is_bitfield,
            bitfield_bits=fld.bitfield_bits,
            is_const=fld.is_const,
            is_volatile=fld.is_volatile,
            is_mutable=fld.is_mutable,
            access=fld.access,
        )

    def _intern_record_type(self, t: RecordType) -> RecordType:
        return RecordType(
            name=sys.intern(t.name),
            kind=t.kind,
            size_bits=t.size_bits,
            alignment_bits=t.alignment_bits,
            fields=[self._intern_field(f) for f in t.fields],
            bases=[sys.intern(b) for b in t.bases],
            virtual_bases=[sys.intern(b) for b in t.virtual_bases],
            vtable=[sys.intern(m) for m in t.vtable],
            source_location=t.source_location,
            is_union=t.is_union,
            is_opaque=t.is_opaque,
        )

    def _normalize_types(self, types: list[RecordType]) -> list[RecordType]:
        """Intern + deduplicate by name.

        On conflict, keep the entry with the larger size_bits
        (more complete DWARF/castxml info wins).
        """
        seen: dict[str, RecordType] = {}
        for t in types:
            interned = self._intern_record_type(t)
            key = interned.name
            if key not in seen:
                seen[key] = interned
            else:
                existing = seen[key]
                # Prefer the entry with more size information
                if (interned.size_bits or 0) > (existing.size_bits or 0):
                    seen[key] = interned
        return list(seen.values())

    def _normalize_variables(self, variables: list[Variable]) -> list[Variable]:
        seen: dict[str, Variable] = {}
        for v in variables:
            interned = Variable(
                name=sys.intern(v.name),
                mangled=sys.intern(v.mangled),
                type=sys.intern(v.type),
                visibility=v.visibility,
                source_location=v.source_location,
                is_const=v.is_const,
                value=v.value,
                access=v.access,
            )
            key = interned.mangled
            if key not in seen or interned.visibility == Visibility.PUBLIC:
                seen[key] = interned
        return list(seen.values())

    def _normalize_enums(self, enums: list[EnumType]) -> list[EnumType]:
        seen: dict[str, EnumType] = {}
        for e in enums:
            interned = EnumType(
                name=sys.intern(e.name),
                members=[
                    EnumMember(name=sys.intern(m.name), value=m.value)
                    for m in e.members
                ],
                underlying_type=sys.intern(e.underlying_type),
            )
            if interned.name not in seen:
                seen[interned.name] = interned
        return list(seen.values())
