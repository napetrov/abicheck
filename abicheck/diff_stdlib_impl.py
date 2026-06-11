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

"""Cross-implementation standard-library compatibility diff (D-stdlib).

ABI compatibility has a third axis beyond backward/forward: compatibility
*between different standard-library implementations*. The C++ standard never
guarantees it. A class that embeds a ``std::`` container/string **by value**
gets a different layout under libstdc++ vs libc++ vs the MSVC STL (different
``sizeof``, different member offsets), so the same source linked against a
mismatched runtime is silently ABI-incompatible — exactly the
``class A { std::vector<T> v; };`` trap.

This detector compares the normalized :class:`~abicheck.build_mode.BuildMode`
captured on each snapshot and emits a RISK finding when the standard-library
implementation (or the libc++ ABI version) differs. It is deliberately
conservative:

* It is **quiet when evidence is missing.** If either side lacks a build-mode
  capture, or the stdlib family is ``UNKNOWN``, it emits nothing — it does not
  guess and it does not escalate. The absence of debug/build evidence is a
  reason to stay silent, not to raise an alarm.
* It defaults to **RISK, never BREAKING.** When an embedded stdlib type's
  layout actually differs and that type is on the public surface, the type
  diff (size/offset) emits the BREAKING finding separately; this kind explains
  and localizes the root cause. The companion change in
  :func:`abicheck.model.stdlib_namespaces_excluded` is what lets that layout
  diff *see* embedded stdlib types in the cross-implementation case (they are
  filtered out of the ordinary same-toolchain comparison as noise).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .build_mode import StdlibFamily
from .checker_policy import ChangeKind
from .checker_types import Change
from .detector_registry import registry

if TYPE_CHECKING:
    from .build_mode import BuildMode
    from .model import AbiSnapshot

#: Marker symbol used for the synthetic build-mode findings (they are not tied
#: to a single exported symbol). Mirrors ``__glibcxx_dual_abi`` in diff_platform.
_STDLIB_IMPL_MARKER = "__stdlib_implementation"

#: Human-readable label per stdlib family for finding descriptions.
_STDLIB_LABEL: dict[StdlibFamily, str] = {
    StdlibFamily.LIBSTDCXX: "libstdc++ (GNU)",
    StdlibFamily.LIBCXX: "libc++ (LLVM)",
    StdlibFamily.MSVC_STL: "MSVC STL",
}


def _public_type_embeds_stdlib_by_value(snap: AbiSnapshot) -> bool:
    """Return True if any record type embeds a ``std::`` field by value.

    A by-value field whose type names a standard-library namespace is what
    makes a public type's layout implementation-dependent. Pointers/references
    to stdlib types are layout-neutral (just a ``void*``), so this only looks
    at the field's spelled type — pointer/reference spellings are skipped.
    """
    from .model import is_non_abi_surface_type

    for rec in snap.types:
        for fld in rec.fields:
            tname = fld.type or ""
            if "*" in tname or "&" in tname:
                continue  # pointer/reference: layout-neutral
            # is_non_abi_surface_type() is True for std::/__gnu_cxx:: etc. We
            # reuse it as the single source of truth for "is a stdlib type".
            if is_non_abi_surface_type(tname.replace("const ", "").strip()):
                return True
    return False


def _layout_evidence_present(snap: AbiSnapshot) -> bool:
    """Return True if the snapshot carries type-layout evidence (DWARF/headers).

    When absent, we cannot verify whether an embedded stdlib type's layout
    actually diverged; the finding then notes the gap calmly instead of
    claiming a clean bill of health.
    """
    return any(rec.size_bits is not None for rec in snap.types)


def _describe(old_bm: BuildMode, new_bm: BuildMode) -> str:
    old_lbl = _STDLIB_LABEL.get(old_bm.stdlib, old_bm.stdlib.value)
    new_lbl = _STDLIB_LABEL.get(new_bm.stdlib, new_bm.stdlib.value)
    return f"{old_lbl} → {new_lbl}"


@registry.detector("stdlib_impl")
def _diff_stdlib_implementation(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    """Detect a change of C++ standard-library implementation between snapshots.

    Emits at most one ``STDLIB_IMPLEMENTATION_CHANGED`` and/or one
    ``LIBCPP_ABI_VERSION_CHANGED`` finding (both RISK). Stays silent when
    build-mode evidence is missing or inconclusive.
    """
    changes: list[Change] = []
    old_bm = old.build_mode
    new_bm = new.build_mode

    # Quiet when evidence is absent: no build-mode on either side means we have
    # no basis to claim an implementation change. Do not guess, do not escalate.
    if old_bm is None or new_bm is None:
        return changes

    # ── Standard-library implementation changed (libstdc++ ↔ libc++ ↔ MSVC) ──
    both_known = (
        old_bm.stdlib is not StdlibFamily.UNKNOWN
        and new_bm.stdlib is not StdlibFamily.UNKNOWN
    )
    if both_known and old_bm.stdlib != new_bm.stdlib:
        embeds = _public_type_embeds_stdlib_by_value(new) or (
            _public_type_embeds_stdlib_by_value(old)
        )
        have_layout = _layout_evidence_present(old) and _layout_evidence_present(new)
        desc = (
            "C++ standard-library implementation changed "
            f"({_describe(old_bm, new_bm)}). The standard does not guarantee ABI "
            "compatibility across implementations: any public type embedding a "
            "std:: container/string by value is laid out differently, and inline "
            "std:: code can ODR-conflict."
        )
        if embeds and have_layout:
            desc += (
                " A public type embeds a std:: type by value; the type diff "
                "reports the concrete layout change separately."
            )
        elif embeds and not have_layout:
            # Calm, non-escalating note that we could not fully verify layout.
            desc += (
                " A public type embeds a std:: type by value, but no layout "
                "evidence (debug info/headers) is available to confirm the exact "
                "divergence — pin the implementation or rebuild against the "
                "matching runtime to be safe."
            )
        changes.append(Change(
            kind=ChangeKind.STDLIB_IMPLEMENTATION_CHANGED,
            symbol=_STDLIB_IMPL_MARKER,
            description=desc,
            old_value=old_bm.stdlib.value,
            new_value=new_bm.stdlib.value,
        ))

    # ── libc++ ABI version changed (_LIBCPP_ABI_VERSION 1 ↔ 2) ───────────────
    old_v = old_bm.libcpp_abi_version
    new_v = new_bm.libcpp_abi_version
    if old_v is not None and new_v is not None and old_v != new_v:
        changes.append(Change(
            kind=ChangeKind.LIBCPP_ABI_VERSION_CHANGED,
            symbol=_STDLIB_IMPL_MARKER,
            description=(
                f"libc++ ABI version changed ({old_v} → {new_v}). libc++ selects "
                "incompatible internal layouts for std:: types via an inline "
                f"namespace (std::__{old_v} vs std::__{new_v}); types embedding "
                "them by value are laid out differently. Rebuild consumers against "
                "the matching libc++ ABI version."
            ),
            old_value=str(old_v),
            new_value=str(new_v),
        ))

    return changes
