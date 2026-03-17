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

"""Unified TypeMetadataSource protocol for all debug format readers.

All debug format metadata classes (DwarfMetadata, BtfMetadata, CtfMetadata)
implement this protocol so the checker's detectors can consume type
information without knowing the source format.

See ADR-007 for design rationale.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .dwarf_metadata import EnumInfo, StructLayout


@runtime_checkable
class TypeMetadataSource(Protocol):
    """Common interface for all debug format readers.

    Implemented by: DwarfMetadata, BtfMetadata, CtfMetadata.
    The checker's detectors accept this protocol instead of a concrete class.
    """

    def get_struct_layout(self, name: str) -> StructLayout | None:
        """Look up a struct/union layout by name."""
        ...

    def get_enum_info(self, name: str) -> EnumInfo | None:
        """Look up an enum type by name."""
        ...

    @property
    def has_data(self) -> bool:
        """Whether this source has any type data available."""
        ...


def resolve_debug_metadata(
    *,
    dwarf: object | None = None,
    btf: object | None = None,
    ctf: object | None = None,
    prefer_btf: bool = False,
) -> TypeMetadataSource | None:
    """Select the best available debug metadata source.

    Priority (userspace, default):  DWARF > BTF > CTF
    Priority (kernel, prefer_btf):  BTF > DWARF > CTF

    Returns None if no source has data.
    """
    sources: list[object]
    if prefer_btf:
        sources = [btf, dwarf, ctf]
    else:
        sources = [dwarf, btf, ctf]

    for src in sources:
        if src is not None and isinstance(src, TypeMetadataSource) and src.has_data:
            return src

    return None
