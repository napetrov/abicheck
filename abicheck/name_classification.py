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

"""Single source of truth for mangled-symbol name classification.

Before this module, the Itanium-ABI prefix knowledge used to answer "is this
symbol an RTTI artifact?" / "does it live in an internal namespace?" was
re-encoded as private tuples in several modules (``report_summary``,
``diff_platform``, ``diff_symbols``, …) — and the copies had begun to drift.
Concentrating the *semantically identical* tables here keeps that knowledge in
one place, so a new compiler convention is added once rather than hunted across
the tree.

Distinct concepts are kept as distinct, clearly-named constants — they are NOT
interchangeable:

* :data:`ITANIUM_RTTI_PREFIXES` — generic RTTI artifacts (vtables, VTT,
  typeinfo objects/names, virtual/covariant thunks). Used to classify a
  symbol's *origin* for reporting.
* :data:`RTTI_DATA_PREFIXES` — the vtable / typeinfo-object / typeinfo-name
  data objects (``_ZTV`` / ``_ZTI`` / ``_ZTS``) whose *size* is owned by their
  type. Thunks are excluded because they carry no size signal.
* :data:`LOCAL_RTTI_PREFIXES` — RTTI for *function-local* types (the Itanium
  ``Z <encoding> E`` local-name production). Such types can never be named in a
  public header, so their typeinfo is build-dependent churn.
* :data:`INTERNAL_NAMESPACE_COMPONENTS` — length-prefixed Itanium namespace
  components (``<len><name>``) for the conventional internal namespaces.

The stdlib-/runtime-specific RTTI skip sets (in ``elf_symbol_filter``,
``diff_elf_layout`` and ``elf_metadata``) are deliberately *not* unified here:
their memberships differ and feed ``startswith`` filters whose results would
change if merged. Unifying them safely needs per-call behaviour-equivalence
checks and is left as a follow-up.
"""

from __future__ import annotations

# Generic RTTI artifact prefixes (Itanium ABI): vtables, VTT, typeinfo
# objects/names, and virtual/covariant thunks. Churn in these mirrors churn in
# their owning type rather than representing independent public-API breaks.
ITANIUM_RTTI_PREFIXES: tuple[str, ...] = (
    "_ZTV",  # vtable
    "_ZTT",  # VTT (construction vtable table)
    "_ZTI",  # typeinfo object
    "_ZTS",  # typeinfo name
    "_ZTc",  # covariant-return thunk
    "_ZTh",  # virtual thunk (non-covariant, this-adjusting)
    "_ZTv",  # virtual thunk (vcall-offset)
)

# RTTI *data* objects whose size is owned by their type: vtable, typeinfo
# object, typeinfo name. Thunks carry no size signal, so they are excluded.
RTTI_DATA_PREFIXES: tuple[str, ...] = ("_ZTV", "_ZTI", "_ZTS")

# RTTI for function-local types. ``_ZT[IVST]`` is followed immediately by ``Z``
# — the Itanium "local-name" production ``Z <encoding> E``. The owning type
# (a lambda closure, or any class declared inside a function body) can never be
# named in a public header, so the presence/absence of its typeinfo is
# build-dependent churn, not a public-ABI break.
LOCAL_RTTI_PREFIXES: tuple[str, ...] = ("_ZTIZ", "_ZTSZ", "_ZTVZ", "_ZTTZ")

# Length-prefixed Itanium namespace components (``<len><name>``) for the
# conventional internal namespaces. Matching the length prefix avoids false
# hits on unrelated identifiers that merely contain the substring.
INTERNAL_NAMESPACE_COMPONENTS: tuple[str, ...] = (
    "8internal",
    "6detail",
    "4impl",
    "8__detail",
    "5_impl",
)


def is_rtti_symbol(name: str) -> bool:
    """Return True if *name* is a generic Itanium RTTI artifact."""
    return name.startswith(ITANIUM_RTTI_PREFIXES)


def is_local_rtti_symbol(name: str) -> bool:
    """Return True if *name* is RTTI for a function-local (unnameable) type."""
    return name.startswith(LOCAL_RTTI_PREFIXES)


def has_internal_namespace_component(name: str) -> bool:
    """Return True if *name* contains a conventional internal-namespace component."""
    return any(comp in name for comp in INTERNAL_NAMESPACE_COMPONENTS)


def symbol_origin(symbol: str) -> str:
    """Best-effort origin of a (usually mangled) symbol.

    Returns ``"rtti"``, ``"internal"`` or ``"public"``. RTTI is checked first:
    an RTTI symbol for an internal type (e.g. ``_ZTIN4daal8internal3FooE``)
    classifies as ``"rtti"``, mirroring the historical behaviour.

    Used to explain why a large C++ ``breaking`` count is dominated by churn in
    RTTI artifacts or internal-namespace symbols rather than genuine public-API
    breaks (a common pattern in libraries built without ``-fvisibility=hidden``).
    """
    if is_rtti_symbol(symbol):
        return "rtti"
    if has_internal_namespace_component(symbol):
        return "internal"
    return "public"
