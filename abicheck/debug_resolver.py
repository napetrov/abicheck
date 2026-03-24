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

"""Debug Artifact Resolution subsystem (ADR-021).

Locates debug artifacts (DWARF, PDB, dSYM) for binaries using a pluggable
resolver chain.  The resolver chain tries strategies in order and returns
the first successful match:

1. Embedded DWARF (binary itself has .debug_info)
2. Split DWARF (.dwo files or .dwp package)
3. Build-id tree (/usr/lib/debug/.build-id/<ab>/<cdef...>.debug)
4. Path mirror (<debug_root>/<original_path>.debug)
5. dSYM bundle (macOS: <binary>.dSYM/Contents/Resources/DWARF/<name>)
6. PDB (Windows: PE debug directory reference)
7. debuginfod (opt-in, network: query by build-id)

Usage::

    from abicheck.debug_resolver import resolve_debug_info, DebugArtifact

    artifact = resolve_debug_info(
        binary_path=Path("/usr/lib/libfoo.so"),
        debug_roots=[Path("/usr/lib/debug")],
    )
    if artifact and artifact.dwarf_path:
        # Parse DWARF from the resolved path
        ...
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

_logger = logging.getLogger(__name__)

# Default debug root directories searched on Linux
_DEFAULT_DEBUG_ROOTS = [
    Path("/usr/lib/debug"),
    Path("/usr/lib/debug/usr"),
]

# Strict hex pattern for build-id validation
_BUILD_ID_RE = re.compile(r"^[0-9a-f]+$")

# Maximum size for debuginfod downloads (512 MiB)
_MAX_DEBUGINFOD_SIZE = 512 * 1024 * 1024


@dataclass
class DebugArtifact:
    """Resolved debug artifact location (ADR-021)."""

    dwarf_path: Path | None = None
    dwp_path: Path | None = None
    dwo_dir: Path | None = None
    pdb_path: Path | None = None
    dsym_path: Path | None = None
    source: str = ""

    @property
    def has_dwarf(self) -> bool:
        return self.dwarf_path is not None

    @property
    def has_pdb(self) -> bool:
        return self.pdb_path is not None

    @property
    def has_dsym(self) -> bool:
        return self.dsym_path is not None

    @property
    def has_split_dwarf(self) -> bool:
        return self.dwp_path is not None or self.dwo_dir is not None

    @property
    def description(self) -> str:
        """Human-readable summary of what was found."""
        parts: list[str] = []
        if self.dwarf_path:
            parts.append(f"DWARF from {self.dwarf_path}")
        if self.dwp_path:
            parts.append(f"DWP from {self.dwp_path}")
        if self.dwo_dir:
            parts.append(f"DWO files in {self.dwo_dir}")
        if self.pdb_path:
            parts.append(f"PDB from {self.pdb_path}")
        if self.dsym_path:
            parts.append(f"dSYM from {self.dsym_path}")
        if not parts:
            return "no debug info found"
        return "; ".join(parts)


class DebugResolverBackend(Protocol):
    """Protocol for a single debug resolution strategy."""

    def resolve(
        self,
        binary_path: Path,
        build_id: str | None = None,
        debug_roots: list[Path] | None = None,
    ) -> DebugArtifact | None:
        """Attempt to find debug info for the given binary.

        Returns a DebugArtifact if found, None otherwise.
        """
        ...


def _is_valid_build_id(build_id: str | None) -> bool:
    """Validate that a build-id is a strict lowercase hex string."""
    return build_id is not None and bool(_BUILD_ID_RE.fullmatch(build_id))


# ---------------------------------------------------------------------------
# Build-id extraction
# ---------------------------------------------------------------------------

def extract_build_id(binary_path: Path) -> str | None:
    """Extract the build-id from an ELF binary's .note.gnu.build-id section.

    Returns the build-id as a lowercase hex string, or None if not found.
    """
    try:
        from elftools.common.exceptions import ELFError
        from elftools.elf.elffile import ELFFile
        from elftools.elf.sections import NoteSection
    except ImportError:
        _logger.debug("pyelftools not available; cannot extract build-id")
        return None

    try:
        with open(binary_path, "rb") as f:
            elf = ELFFile(f)  # type: ignore[no-untyped-call]
            for section in elf.iter_sections():
                if not isinstance(section, NoteSection):
                    continue
                for note in section.iter_notes():
                    if note["n_type"] == "NT_GNU_BUILD_ID":
                        desc = note["n_desc"]
                        if isinstance(desc, str):
                            return desc.lower()
                        if isinstance(desc, bytes):
                            return desc.hex().lower()
                        return str(desc).lower()
    except (OSError, ValueError, KeyError, ELFError) as exc:
        _logger.debug("Failed to extract build-id from %s: %s", binary_path, exc)

    return None


# ---------------------------------------------------------------------------
# Resolver backends
# ---------------------------------------------------------------------------

class EmbeddedDwarfResolver:
    """Check if the binary itself contains DWARF debug sections."""

    def resolve(
        self,
        binary_path: Path,
        build_id: str | None = None,
        debug_roots: list[Path] | None = None,
    ) -> DebugArtifact | None:
        try:
            from elftools.common.exceptions import ELFError
            from elftools.elf.elffile import ELFFile
        except ImportError:
            return None

        try:
            with open(binary_path, "rb") as f:
                elf = ELFFile(f)  # type: ignore[no-untyped-call]
                debug_info = elf.get_section_by_name(".debug_info")
                if debug_info is not None and debug_info.data_size > 0:
                    _logger.debug("Embedded DWARF found in %s", binary_path)
                    return DebugArtifact(
                        dwarf_path=binary_path,
                        source="embedded DWARF",
                    )
        except (OSError, ValueError, ELFError) as exc:
            _logger.debug("Cannot check embedded DWARF in %s: %s", binary_path, exc)

        return None


class SplitDwarfResolver:
    """Look for split DWARF (.dwo files or .dwp package)."""

    def resolve(
        self,
        binary_path: Path,
        build_id: str | None = None,
        debug_roots: list[Path] | None = None,
    ) -> DebugArtifact | None:
        # Check for .dwp (DWARF package) alongside the binary
        dwp_candidates = [
            binary_path.with_suffix(".dwp"),
            # For multi-extension names like libfoo.so.1 → libfoo.so.1.dwp
            binary_path.parent / (binary_path.name + ".dwp"),
        ]
        for dwp in dwp_candidates:
            if dwp.exists():
                _logger.debug("Found DWP file: %s", dwp)
                return DebugArtifact(dwp_path=dwp, source="split DWARF (.dwp)")

        # Check debug roots for .dwp
        for root in (debug_roots or []):
            dwp = root / (binary_path.name + ".dwp")
            if dwp.exists():
                _logger.debug("Found DWP file in debug root: %s", dwp)
                return DebugArtifact(dwp_path=dwp, source="split DWARF (.dwp) in debug root")

        # Look for .dwo files referenced in the binary
        try:
            from elftools.common.exceptions import ELFError
            from elftools.elf.elffile import ELFFile
        except ImportError:
            return None

        dwo_names: list[str] = []
        comp_dirs: set[str] = set()
        try:
            with open(binary_path, "rb") as f:
                elf = ELFFile(f)  # type: ignore[no-untyped-call]
                if not elf.has_dwarf_info():
                    return None
                dwarf = elf.get_dwarf_info()  # type: ignore[no-untyped-call]
                for cu in dwarf.iter_CUs():
                    top_die = cu.get_top_DIE()
                    # Check for DW_AT_GNU_dwo_name or DW_AT_dwo_name
                    for attr_name in ("DW_AT_GNU_dwo_name", "DW_AT_dwo_name"):
                        if attr_name in top_die.attributes:
                            val = top_die.attributes[attr_name].value
                            if isinstance(val, bytes):
                                val = val.decode("utf-8", errors="replace")
                            dwo_names.append(val)
                    # Get comp_dir for path resolution (deduplicated)
                    if "DW_AT_comp_dir" in top_die.attributes:
                        val = top_die.attributes["DW_AT_comp_dir"].value
                        if isinstance(val, bytes):
                            val = val.decode("utf-8", errors="replace")
                        comp_dirs.add(val)
        except (OSError, ValueError, KeyError, ELFError) as exc:
            _logger.debug("Cannot check split DWARF in %s: %s", binary_path, exc)
            return None

        if not dwo_names:
            return None

        # Try to find a directory containing ALL (or most) .dwo files
        search_dirs = [binary_path.parent]
        for comp_dir in comp_dirs:
            p = Path(comp_dir)
            if p.is_absolute() and p.is_dir():
                search_dirs.append(p)
        for root in (debug_roots or []):
            search_dirs.append(root)

        total = len(dwo_names)
        # Require at least ceiling-half of .dwo files to be present
        min_required = max(1, (total + 1) // 2)
        for search_dir in search_dirs:
            found_count = sum(
                1 for name in dwo_names
                if (search_dir / name).exists()
            )
            if found_count >= min_required:
                if found_count < total:
                    _logger.warning(
                        "Partial split DWARF: found %d/%d .dwo files in %s",
                        found_count, total, search_dir,
                    )
                else:
                    _logger.debug(
                        "Found all %d .dwo files in %s", total, search_dir,
                    )
                return DebugArtifact(
                    dwo_dir=search_dir,
                    source=f"split DWARF ({found_count}/{total} .dwo files)",
                )

        return None


class BuildIdTreeResolver:
    """Search build-id tree directories for separate debug files."""

    def resolve(
        self,
        binary_path: Path,
        build_id: str | None = None,
        debug_roots: list[Path] | None = None,
    ) -> DebugArtifact | None:
        if not _is_valid_build_id(build_id) or not build_id or len(build_id) < 3:
            return None

        prefix = build_id[:2]
        suffix = build_id[2:]

        roots = list(debug_roots or []) + _DEFAULT_DEBUG_ROOTS
        for root in roots:
            debug_file = root / ".build-id" / prefix / f"{suffix}.debug"
            if debug_file.exists():
                _logger.debug("Found debug file via build-id: %s", debug_file)
                return DebugArtifact(
                    dwarf_path=debug_file,
                    source=f"build-id tree ({root})",
                )

        return None


class PathMirrorResolver:
    """Search path-mirror locations (distro convention).

    Example: /usr/lib/debug/usr/lib64/libfoo.so.1.debug
    """

    def resolve(
        self,
        binary_path: Path,
        build_id: str | None = None,
        debug_roots: list[Path] | None = None,
    ) -> DebugArtifact | None:
        binary_abs = binary_path.resolve()
        roots = list(debug_roots or []) + _DEFAULT_DEBUG_ROOTS

        for root in roots:
            # Standard path mirror: <root>/<absolute_path>.debug
            mirror = root / str(binary_abs).lstrip("/")
            debug_with_ext = mirror.parent / (mirror.name + ".debug")
            if debug_with_ext.exists():
                _logger.debug("Found debug file via path mirror: %s", debug_with_ext)
                return DebugArtifact(
                    dwarf_path=debug_with_ext,
                    source=f"path mirror ({root})",
                )

            # Also try replacing suffix with .debug
            debug_replaced = mirror.with_suffix(".debug")
            if debug_replaced.exists() and debug_replaced != debug_with_ext:
                _logger.debug("Found debug file via path mirror: %s", debug_replaced)
                return DebugArtifact(
                    dwarf_path=debug_replaced,
                    source=f"path mirror ({root})",
                )

        return None


class DSYMResolver:
    """Locate dSYM bundles for macOS binaries (ADR-021)."""

    def resolve(
        self,
        binary_path: Path,
        build_id: str | None = None,
        debug_roots: list[Path] | None = None,
    ) -> DebugArtifact | None:
        binary_name = binary_path.name

        # Strategy 1: Adjacent to binary
        dsym = binary_path.parent / f"{binary_name}.dSYM"
        dwarf_file = self._dsym_dwarf_path(dsym, binary_name)
        if dwarf_file and dwarf_file.exists():
            _logger.debug("Found dSYM bundle: %s", dsym)
            return DebugArtifact(
                dwarf_path=dwarf_file, dsym_path=dsym,
                source="dSYM bundle (adjacent)",
            )

        # Strategy 2: Framework bundle
        if ".framework" in str(binary_path):
            framework_root = self._find_framework_root(binary_path)
            if framework_root:
                dsym = framework_root.parent / f"{framework_root.name}.dSYM"
                dwarf_file = self._dsym_dwarf_path(dsym, binary_name)
                if dwarf_file and dwarf_file.exists():
                    _logger.debug("Found dSYM bundle (framework): %s", dsym)
                    return DebugArtifact(
                        dwarf_path=dwarf_file, dsym_path=dsym,
                        source="dSYM bundle (framework)",
                    )

        # Strategy 3: User-specified debug roots
        for root in (debug_roots or []):
            dsym = root / f"{binary_name}.dSYM"
            dwarf_file = self._dsym_dwarf_path(dsym, binary_name)
            if dwarf_file and dwarf_file.exists():
                _logger.debug("Found dSYM bundle in debug root: %s", dsym)
                return DebugArtifact(
                    dwarf_path=dwarf_file, dsym_path=dsym,
                    source=f"dSYM bundle ({root})",
                )

        return None

    @staticmethod
    def _dsym_dwarf_path(dsym_bundle: Path, binary_name: str) -> Path | None:
        """Get the DWARF file path within a dSYM bundle."""
        if not dsym_bundle.is_dir():
            return None
        return dsym_bundle / "Contents" / "Resources" / "DWARF" / binary_name

    @staticmethod
    def _find_framework_root(binary_path: Path) -> Path | None:
        """Find the .framework directory containing this binary."""
        for parent in binary_path.parents:
            if parent.suffix == ".framework":
                return parent
        return None


class PDBResolver:
    """Locate PDB files for Windows PE binaries."""

    def resolve(
        self,
        binary_path: Path,
        build_id: str | None = None,
        debug_roots: list[Path] | None = None,
    ) -> DebugArtifact | None:
        # Try adjacent PDB with same stem
        pdb_adjacent = binary_path.with_suffix(".pdb")
        if pdb_adjacent.exists():
            _logger.debug("Found PDB adjacent to binary: %s", pdb_adjacent)
            return DebugArtifact(pdb_path=pdb_adjacent, source="adjacent PDB")

        # Try debug roots
        for root in (debug_roots or []):
            pdb_in_root = root / f"{binary_path.stem}.pdb"
            if pdb_in_root.exists():
                _logger.debug("Found PDB in debug root: %s", pdb_in_root)
                return DebugArtifact(
                    pdb_path=pdb_in_root,
                    source=f"PDB in debug root ({root})",
                )

        # Try _NT_SYMBOL_PATH
        symbol_path = os.environ.get("_NT_SYMBOL_PATH", "")
        if symbol_path:
            for sp in symbol_path.split(";"):
                sp = sp.strip()
                if not sp:
                    continue
                pdb_in_sp = Path(sp) / f"{binary_path.stem}.pdb"
                if pdb_in_sp.exists():
                    _logger.debug("Found PDB via _NT_SYMBOL_PATH: %s", pdb_in_sp)
                    return DebugArtifact(
                        pdb_path=pdb_in_sp,
                        source="_NT_SYMBOL_PATH",
                    )

        return None


class DebuginfodResolver:
    """Fetch debug info from a debuginfod server by build-id (opt-in).

    debuginfod is the elfutils standard for serving debug artifacts over
    HTTP, indexed by build-id.  This resolver is only activated when
    explicitly enabled (never implicit network access).
    """

    def __init__(
        self,
        server_urls: list[str] | None = None,
        cache_dir: Path | None = None,
        allow_insecure: bool = False,
    ) -> None:
        self._urls = server_urls or self._default_urls()
        self._cache_dir = cache_dir or self._default_cache()
        self._allow_insecure = allow_insecure

    @staticmethod
    def _default_urls() -> list[str]:
        env = os.environ.get("DEBUGINFOD_URLS", "")
        return [u.strip() for u in env.split() if u.strip()]

    @staticmethod
    def _default_cache() -> Path:
        xdg = os.environ.get("XDG_CACHE_HOME", "")
        if xdg:
            return Path(xdg) / "abicheck" / "debuginfod"
        return Path.home() / ".cache" / "abicheck" / "debuginfod"

    def resolve(
        self,
        binary_path: Path,
        build_id: str | None = None,
        debug_roots: list[Path] | None = None,
    ) -> DebugArtifact | None:
        if not build_id:
            return None
        # Validate build-id is strictly hex to prevent URL injection
        if not _is_valid_build_id(build_id):
            _logger.warning("Invalid build-id (not hex): %r", build_id)
            return None
        if not self._urls:
            _logger.debug("No debuginfod URLs configured")
            return None

        # Check local cache first
        cached = self._cache_dir / build_id[:2] / f"{build_id[2:]}.debug"
        if cached.exists():
            _logger.debug("debuginfod cache hit: %s", cached)
            return DebugArtifact(dwarf_path=cached, source="debuginfod (cached)")

        # Fetch from server
        for url in self._urls:
            url = url.rstrip("/")
            scheme = urlparse(url).scheme.lower()
            if scheme == "https":
                pass  # always allowed
            elif scheme == "http" and self._allow_insecure:
                pass  # allowed with explicit opt-in
            else:
                _logger.warning(
                    "Skipping debuginfod URL %s (scheme %r not allowed; "
                    "only https is accepted by default, use "
                    "--debuginfod-allow-insecure to also allow http)",
                    url, scheme,
                )
                continue

            fetch_url = f"{url}/buildid/{build_id}/debuginfo"
            _logger.info("Fetching debug info from %s", fetch_url)

            try:
                import urllib.request

                req = urllib.request.Request(fetch_url)
                req.add_header("User-Agent", "abicheck-debuginfod-client")
                with urllib.request.urlopen(req, timeout=30) as resp:
                    if resp.status != 200:
                        continue
                    # Read with size limit to prevent memory exhaustion
                    data = resp.read(_MAX_DEBUGINFOD_SIZE + 1)
                    if len(data) > _MAX_DEBUGINFOD_SIZE:
                        _logger.warning(
                            "Debuginfod response exceeds %d MiB limit, skipping",
                            _MAX_DEBUGINFOD_SIZE // (1024 * 1024),
                        )
                        continue

                # Validate ELF magic
                if len(data) < 16 or data[:4] != b"\x7fELF":
                    _logger.warning("Downloaded file is not valid ELF: %s", fetch_url)
                    continue

                # Atomic cache write: write to temp file then replace
                cached.parent.mkdir(parents=True, exist_ok=True)
                fd, tmp_path = tempfile.mkstemp(dir=cached.parent)
                try:
                    os.write(fd, data)
                    os.close(fd)
                    fd = -1  # mark as closed
                    os.replace(tmp_path, str(cached))
                except BaseException:
                    if fd >= 0:
                        os.close(fd)
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                    raise

                _logger.info("Downloaded and cached debug info: %s", cached)
                return DebugArtifact(
                    dwarf_path=cached,
                    source=f"debuginfod ({url})",
                )
            except (OSError, urllib.error.URLError) as exc:
                _logger.debug("debuginfod fetch failed from %s: %s", url, exc)
                continue

        return None


# ---------------------------------------------------------------------------
# Main resolution function
# ---------------------------------------------------------------------------

# Default resolver chain (ordered, first-match wins)
_DEFAULT_RESOLVERS: list[DebugResolverBackend] = [
    SplitDwarfResolver(),
    EmbeddedDwarfResolver(),
    BuildIdTreeResolver(),
    PathMirrorResolver(),
    DSYMResolver(),
    PDBResolver(),
]


def resolve_debug_info(
    binary_path: Path,
    *,
    debug_roots: list[Path] | None = None,
    build_id: str | None = None,
    enable_debuginfod: bool = False,
    debuginfod_urls: list[str] | None = None,
    debuginfod_cache_dir: Path | None = None,
    debuginfod_allow_insecure: bool = False,
) -> DebugArtifact | None:
    """Resolve debug artifacts for a binary using the resolver chain (ADR-021).

    Tries each resolver in order and returns the first successful match.
    Returns None if no debug info is found (symbols-only mode fallback).
    """
    if build_id is None:
        build_id = extract_build_id(binary_path)

    resolvers: list[DebugResolverBackend] = list(_DEFAULT_RESOLVERS)
    if enable_debuginfod:
        resolvers.append(
            DebuginfodResolver(
                server_urls=debuginfod_urls,
                cache_dir=debuginfod_cache_dir,
                allow_insecure=debuginfod_allow_insecure,
            )
        )

    for resolver in resolvers:
        result = resolver.resolve(binary_path, build_id=build_id, debug_roots=debug_roots)
        if result is not None:
            _logger.info(
                "Debug info resolved for %s: %s",
                binary_path.name, result.source,
            )
            return result

    _logger.info("No debug info found for %s", binary_path.name)
    return None


def format_data_sources(
    binary_path: Path,
    artifact: DebugArtifact | None,
    has_headers: bool,
) -> str:
    """Format debug resolution results for --show-data-sources output."""
    lines = [f"Data sources for {binary_path.name}:"]

    if artifact:
        lines.append(f"  Debug info: {artifact.description}")
        lines.append(f"  Resolution: {artifact.source}")
    else:
        lines.append("  Debug info: not found (symbols-only mode)")

    lines.append(f"  Headers:    {'available' if has_headers else 'not provided'}")

    return "\n".join(lines)
