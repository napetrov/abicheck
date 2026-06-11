# Copyright 2026 Nikolay Petrov
# SPDX-License-Identifier: Apache-2.0
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

"""C++-specific ABI-rule helpers shared by the symbol/type diff passes.

Kept as a leaf module (depending only on the data model and result types) so
``diff_symbols`` can import it without creating an import cycle.
"""

from __future__ import annotations

from .checker_policy import ChangeKind
from .checker_types import Change
from .model import Function, RecordType


def owner_class_of(display_name: str) -> str | None:
    """The enclosing class/struct of a method, parsed from its demangled name.

    ``Foo::bar`` → ``Foo``; ``ns::Foo::bar`` → ``ns::Foo``; a free function
    (no ``::``) → ``None``. Operator/conversion names never contain ``::`` in
    their trailing component, so a single right-split is safe.
    """
    if "::" not in display_name:
        return None
    return display_name.rsplit("::", 1)[0]


def virtual_method_addition(
    f_new: Function,
    old_types: dict[str, RecordType],
    new_types: dict[str, RecordType],
) -> Change | None:
    """A new *virtual* method on a class that already exists across versions.

    Returns a ``VIRTUAL_METHOD_ADDED`` change, or ``None`` if this added symbol
    is not a virtual added to a pre-existing type. Scoped to the genuine blind
    spot: when the owner's ``vtable`` array is identical on both sides (e.g.
    DWARF/symbol-only snapshots that carry no vtable layout), the per-type
    ``TYPE_VTABLE_CHANGED`` detector cannot see the growth, so this is the only
    signal. When the vtable array *does* differ, ``TYPE_VTABLE_CHANGED`` already
    reports it and we defer to avoid a duplicate finding.
    """
    if not f_new.is_virtual:
        return None
    owner = owner_class_of(f_new.name)
    if owner is None:
        return None
    t_old = old_types.get(owner)
    t_new = new_types.get(owner)
    if t_old is None or t_new is None:
        return None  # brand-new class → adding it (with virtuals) is compatible
    if t_old.vtable != t_new.vtable:
        return None  # TYPE_VTABLE_CHANGED covers this case
    return Change(
        kind=ChangeKind.VIRTUAL_METHOD_ADDED,
        symbol=f_new.mangled,
        description=(
            f"New virtual method added to existing class {owner}: {f_new.name} "
            "— grows/relayouts the vtable, breaking derived classes and old binaries"
        ),
        new_value=f_new.name,
    )
