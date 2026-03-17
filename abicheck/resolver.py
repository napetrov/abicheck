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

"""Transitive ELF dependency resolution with loader-accurate search order.

Implements the dynamic linker's search algorithm for DT_NEEDED resolution:
  1. DT_RPATH (only if DT_RUNPATH is absent in the *requesting* object)
  2. LD_LIBRARY_PATH
  3. DT_RUNPATH (only for *direct* DT_NEEDED of the requesting object)
  4. Default directories (/lib, /usr/lib, and platform-specific lib dirs)

Key correctness rule: DT_RUNPATH applies only to direct dependencies of the
object that declares it, **not** to transitive dependencies.  DT_RPATH, when
used (no DT_RUNPATH present), propagates through the entire dependency tree.

See ld.so(8) and ``man 8 ld-linux`` for the full specification.
"""
from __future__ import annotations

import logging
import os
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from .elf_metadata import ElfMetadata, parse_elf_metadata

log = logging.getLogger(__name__)


@dataclass
class ResolvedDSO:
    """A single resolved shared object in the dependency graph."""
    path: Path                    # Resolved filesystem path
    soname: str                   # DT_SONAME (or basename if missing)
    needed: list[str]             # DT_NEEDED entries (raw soname strings)
    rpath: str                    # DT_RPATH
    runpath: str                  # DT_RUNPATH
    resolution_reason: str        # Why resolved here (rpath/runpath/ld_library_path/default/root)
    depth: int                    # Distance from root binary (0 = root)
    elf_metadata: ElfMetadata | None = None  # Full parsed metadata


@dataclass
class DependencyGraph:
    """The resolved transitive dependency closure of a root binary."""
    root: str                     # Root binary path
    nodes: dict[str, ResolvedDSO] = field(default_factory=dict)  # resolved_path → info
    edges: list[tuple[str, str]] = field(default_factory=list)   # (consumer_path, provider_path)
    unresolved: list[tuple[str, str]] = field(default_factory=list)  # (consumer_path, missing_soname)

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def resolved_paths(self) -> list[str]:
        return sorted(self.nodes.keys())


# ---------------------------------------------------------------------------
# Default search directories (Linux x86_64)
# ---------------------------------------------------------------------------

_DEFAULT_DIRS: list[str] = [
    "/lib/x86_64-linux-gnu",
    "/usr/lib/x86_64-linux-gnu",
    "/lib64",
    "/usr/lib64",
    "/lib",
    "/usr/lib",
]


def resolve_dependencies(
    binary: Path,
    search_paths: list[Path] | None = None,
    sysroot: Path | None = None,
    ld_library_path: str = "",
) -> DependencyGraph:
    """Resolve the transitive closure of DT_NEEDED dependencies.

    Args:
        binary: Path to the root ELF binary or shared library.
        search_paths: Additional directories to search (appended after defaults).
        sysroot: Prefix prepended to all search paths (for cross/container analysis).
        ld_library_path: Colon-separated list of directories (simulates $LD_LIBRARY_PATH).

    Returns:
        A DependencyGraph with all resolved and unresolved dependencies.
    """
    graph = DependencyGraph(root=str(binary))
    extra_dirs = [str(p) for p in (search_paths or [])]
    ld_dirs = [d for d in ld_library_path.split(":") if d]
    prefix = str(sysroot) if sysroot else ""

    # Track visited sonames to avoid cycles.
    visited_sonames: set[str] = set()

    # BFS queue: (soname_or_path, requesting_dso_path, depth)
    queue: deque[tuple[str, str | None, int]] = deque()

    # Seed with the root binary.
    root_path = binary.resolve()
    if not root_path.exists():
        log.warning("resolve_dependencies: root binary not found: %s", binary)
        return graph

    root_meta = parse_elf_metadata(root_path)
    root_key = str(root_path)
    root_soname = root_meta.soname or root_path.name

    graph.nodes[root_key] = ResolvedDSO(
        path=root_path,
        soname=root_soname,
        needed=list(root_meta.needed),
        rpath=root_meta.rpath,
        runpath=root_meta.runpath,
        resolution_reason="root",
        depth=0,
        elf_metadata=root_meta,
    )
    visited_sonames.add(root_soname)
    visited_sonames.add(root_path.name)

    for needed in root_meta.needed:
        queue.append((needed, root_key, 1))

    # Propagated RPATHs from ancestor DSOs (only when DT_RUNPATH is absent).
    # Key: requesting DSO path → collected RPATHs.
    propagated_rpaths: dict[str, list[str]] = {}
    if root_meta.rpath and not root_meta.runpath:
        propagated_rpaths[root_key] = _expand_rpath(
            root_meta.rpath, root_path.parent, prefix,
        )

    while queue:
        soname, requester_path, depth = queue.popleft()

        if soname in visited_sonames:
            # Already resolved — just record the edge.
            resolved_key = _find_resolved_key(graph, soname)
            if resolved_key and requester_path:
                graph.edges.append((requester_path, resolved_key))
            continue

        visited_sonames.add(soname)

        # Build search paths for this resolution.
        requester_node = graph.nodes.get(requester_path) if requester_path else None
        requester_dir = Path(requester_path).parent if requester_path else root_path.parent

        search = _build_search_order(
            soname=soname,
            requester_node=requester_node,
            requester_dir=requester_dir,
            propagated_rpaths=propagated_rpaths.get(requester_path or "", []),
            ld_dirs=ld_dirs,
            extra_dirs=extra_dirs,
            prefix=prefix,
        )

        resolved = _search_library(soname, search)
        if resolved is None:
            graph.unresolved.append((requester_path or root_key, soname))
            continue

        resolved_path = resolved[0]
        reason = resolved[1]
        resolved_key = str(resolved_path)

        # Avoid re-processing the same file by resolved path.
        if resolved_key in graph.nodes:
            if requester_path:
                graph.edges.append((requester_path, resolved_key))
            continue

        meta = parse_elf_metadata(resolved_path)
        node = ResolvedDSO(
            path=resolved_path,
            soname=meta.soname or soname,
            needed=list(meta.needed),
            rpath=meta.rpath,
            runpath=meta.runpath,
            resolution_reason=reason,
            depth=depth,
            elf_metadata=meta,
        )
        graph.nodes[resolved_key] = node
        if requester_path:
            graph.edges.append((requester_path, resolved_key))

        # Propagate RPATH (only if this DSO has DT_RPATH and no DT_RUNPATH).
        if meta.rpath and not meta.runpath:
            propagated_rpaths[resolved_key] = _expand_rpath(
                meta.rpath, resolved_path.parent, prefix,
            )

        for needed_child in meta.needed:
            if needed_child not in visited_sonames:
                queue.append((needed_child, resolved_key, depth + 1))

    return graph


# ---------------------------------------------------------------------------
# Search order construction
# ---------------------------------------------------------------------------

def _build_search_order(
    soname: str,
    requester_node: ResolvedDSO | None,
    requester_dir: Path,
    propagated_rpaths: list[str],
    ld_dirs: list[str],
    extra_dirs: list[str],
    prefix: str,
) -> list[tuple[str, str]]:
    """Build the ordered list of (directory, reason) to search for *soname*.

    Implements the ld.so search order:
      1. DT_RPATH of requester (only if requester has no DT_RUNPATH)
      2. LD_LIBRARY_PATH
      3. DT_RUNPATH of requester (only for *direct* deps of requester)
      4. Default directories + extra search paths
    """
    search: list[tuple[str, str]] = []

    if requester_node is not None:
        # Step 1: DT_RPATH — only if no DT_RUNPATH is present.
        if requester_node.rpath and not requester_node.runpath:
            for d in _expand_rpath(requester_node.rpath, requester_dir, prefix):
                search.append((d, "rpath"))
        # Also propagated RPATHs from ancestors.
        for d in propagated_rpaths:
            search.append((d, "rpath_propagated"))

    # Step 2: LD_LIBRARY_PATH.
    for d in ld_dirs:
        full = os.path.join(prefix, d.lstrip("/")) if prefix else d
        search.append((full, "ld_library_path"))

    # Step 3: DT_RUNPATH — only for direct DT_NEEDED.
    if requester_node is not None and requester_node.runpath:
        for d in _expand_rpath(requester_node.runpath, requester_dir, prefix):
            search.append((d, "runpath"))

    # Step 4: Default directories.
    for d in _DEFAULT_DIRS:
        full = os.path.join(prefix, d.lstrip("/")) if prefix else d
        search.append((full, "default"))

    # Extra user-specified search paths.
    for d in extra_dirs:
        full = os.path.join(prefix, d.lstrip("/")) if prefix else d
        search.append((full, "search_path"))

    return search


def _search_library(
    soname: str, search: list[tuple[str, str]],
) -> tuple[Path, str] | None:
    """Search for *soname* in the ordered directory list.

    Returns (resolved_path, reason) or None if not found.
    """
    for directory, reason in search:
        candidate = Path(directory) / soname
        if candidate.is_file():
            return candidate.resolve(), reason
    return None


# ---------------------------------------------------------------------------
# RPATH/RUNPATH expansion
# ---------------------------------------------------------------------------

def _expand_rpath(rpath: str, origin_dir: Path, prefix: str) -> list[str]:
    """Expand an RPATH/RUNPATH string into a list of directories.

    Handles:
      - Colon-separated paths
      - $ORIGIN / ${ORIGIN} → directory containing the DSO
      - $LIB / ${LIB} → "lib" or "lib/x86_64-linux-gnu" (best-effort)
      - $PLATFORM / ${PLATFORM} → "x86_64" (best-effort default)
      - Sysroot prefix
    """
    dirs: list[str] = []
    origin = str(origin_dir)
    for entry in rpath.split(":"):
        if not entry:
            continue
        expanded = entry
        expanded = expanded.replace("${ORIGIN}", origin).replace("$ORIGIN", origin)
        expanded = expanded.replace("${LIB}", "lib").replace("$LIB", "lib")
        expanded = expanded.replace("${PLATFORM}", "x86_64").replace("$PLATFORM", "x86_64")
        if prefix:
            expanded = os.path.join(prefix, expanded.lstrip("/"))
        dirs.append(expanded)
    return dirs


def _find_resolved_key(graph: DependencyGraph, soname: str) -> str | None:
    """Find the resolved path key for a given soname in the graph."""
    for key, node in graph.nodes.items():
        if node.soname == soname or Path(key).name == soname:
            return key
    return None
