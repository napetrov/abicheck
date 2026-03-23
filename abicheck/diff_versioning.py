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

"""ELF symbol-version policy checks.

Extends the existing L0 detector pattern (ADR-011) with version-node graph
diffing, SONAME bump recommendations, and version-script-missing detection.
"""
from __future__ import annotations

from .checker_policy import ChangeKind, Verdict
from .checker_types import Change
from .elf_metadata import ElfMetadata


def detect_version_node_changes(
    old_elf: ElfMetadata, new_elf: ElfMetadata,
) -> list[Change]:
    """Compare ELF symbol version definition graphs.

    Builds a version_node → set[symbol_name] mapping for both old and new,
    then detects:
      - Removed version nodes (all symbols in that node gone)
      - Symbols migrated between version nodes
      - New version nodes added (informational, no change emitted here —
        already covered by SYMBOL_VERSION_DEFINED_ADDED)
    """
    old_node_syms = _build_version_node_map(old_elf)
    new_node_syms = _build_version_node_map(new_elf)

    changes: list[Change] = []

    # Detect removed version nodes (node existed in old, gone in new)
    for node in sorted(set(old_node_syms) - set(new_node_syms)):
        sym_names = sorted(old_node_syms[node])
        sample = ", ".join(sym_names[:5])
        suffix = f" (+{len(sym_names) - 5} more)" if len(sym_names) > 5 else ""
        changes.append(Change(
            kind=ChangeKind.SYMBOL_VERSION_NODE_REMOVED,
            symbol=node,
            description=(
                f"Version node {node} was entirely removed from the version script. "
                f"Symbols previously under this node: {sample}{suffix}. "
                f"Applications linked against {node} will get unresolved symbol errors."
            ),
            old_value=node,
        ))

    # Detect symbols that moved between version nodes
    old_sym_to_node = _build_sym_to_node_map(old_node_syms)
    new_sym_to_node = _build_sym_to_node_map(new_node_syms)

    for sym_name in sorted(set(old_sym_to_node) & set(new_sym_to_node)):
        old_node = old_sym_to_node[sym_name]
        new_node = new_sym_to_node[sym_name]
        if old_node != new_node:
            changes.append(Change(
                kind=ChangeKind.SYMBOL_MOVED_VERSION_NODE,
                symbol=sym_name,
                description=(
                    f"Symbol {sym_name} moved from version node {old_node} to "
                    f"{new_node}. Applications linked against {old_node} will not "
                    f"find this symbol at the expected version. This is typically "
                    f"intentional during a major release."
                ),
                old_value=old_node,
                new_value=new_node,
            ))

    return changes


def detect_version_script_missing(
    old_elf: ElfMetadata, new_elf: ElfMetadata,
) -> list[Change]:
    """Check whether a library exports symbols without a version script.

    Emits VERSION_SCRIPT_MISSING when:
      - The library has exported symbols
      - None of them carry a version tag
      - No version definitions exist
    """
    changes: list[Change] = []

    for label, elf in [("old", old_elf), ("new", new_elf)]:
        if not elf.symbols:
            continue
        if elf.versions_defined:
            continue
        has_any_version = any(s.version for s in elf.symbols)
        if has_any_version:
            continue
        changes.append(Change(
            kind=ChangeKind.VERSION_SCRIPT_MISSING,
            symbol="<version-script>",
            description=(
                f"The {label} library exports {len(elf.symbols)} symbol(s) without "
                f"a version script. This is a common oversight that prevents "
                f"fine-grained symbol versioning and makes future ABI evolution "
                f"harder to manage. Consider adding a version script "
                f"(--version-script=libfoo.map)."
            ),
        ))

    return changes


def check_soname_bump_policy(
    changes: list[Change],
    old_elf: ElfMetadata,
    new_elf: ElfMetadata,
) -> list[Change]:
    """Check whether SONAME bump is appropriate given detected changes.

    This is a post-detection check that runs after all detectors, since it
    needs the full change list to make its recommendation.

    Rules:
      - Breaking changes detected but SONAME not bumped → SONAME_BUMP_RECOMMENDED
      - No breaking changes but SONAME bumped → SONAME_BUMP_UNNECESSARY
    """
    from .checker_policy import BREAKING_KINDS

    breaking_kinds = BREAKING_KINDS
    has_breaking = any(c.kind in breaking_kinds for c in changes)
    soname_changed = (
        old_elf.soname != new_elf.soname
        and bool(old_elf.soname)
        and bool(new_elf.soname)
    )

    result: list[Change] = []

    if has_breaking and not soname_changed and old_elf.soname:
        breaking_count = sum(1 for c in changes if c.kind in breaking_kinds)
        result.append(Change(
            kind=ChangeKind.SONAME_BUMP_RECOMMENDED,
            symbol="DT_SONAME",
            description=(
                f"{breaking_count} binary-incompatible change(s) detected but "
                f"SONAME remains {old_elf.soname!r}. Consumers linked against "
                f"{old_elf.soname!r} will encounter runtime failures. "
                f"Recommended: bump SONAME to signal the ABI break."
            ),
            old_value=old_elf.soname,
            new_value=new_elf.soname or old_elf.soname,
        ))

    if not has_breaking and soname_changed:
        result.append(Change(
            kind=ChangeKind.SONAME_BUMP_UNNECESSARY,
            symbol="DT_SONAME",
            description=(
                f"SONAME changed from {old_elf.soname!r} to {new_elf.soname!r} "
                f"but no binary-incompatible changes were detected. This forces "
                f"all consumers to relink unnecessarily. Consider whether the "
                f"bump was intentional."
            ),
            old_value=old_elf.soname,
            new_value=new_elf.soname,
        ))

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_version_node_map(elf: ElfMetadata) -> dict[str, set[str]]:
    """Build a mapping from version node name → set of symbol names."""
    node_map: dict[str, set[str]] = {}
    for sym in elf.symbols:
        if sym.version and sym.version in elf.versions_defined:
            node_map.setdefault(sym.version, set()).add(sym.name)
    return node_map


def _build_sym_to_node_map(node_map: dict[str, set[str]]) -> dict[str, str]:
    """Invert node_map: symbol_name → version_node (first wins)."""
    result: dict[str, str] = {}
    for node, syms in node_map.items():
        for sym in syms:
            if sym not in result:
                result[sym] = node
    return result
