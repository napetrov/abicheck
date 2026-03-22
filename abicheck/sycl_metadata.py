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

"""SYCL runtime and Plugin Interface (PI) metadata extraction.

Extracts metadata from SYCL distributions for ABI compatibility checking:

- PI plugin inventory (which backend plugins are shipped)
- PI entry points per plugin (exported ``pi*`` symbols)
- PI version detection (from symbol heuristics or runtime probing)
- Plugin search path configuration

Primary target: DPC++ (Intel's SYCL implementation).
See ADR-020 for design rationale.

Static extraction uses ``pyelftools`` to parse plugin ``.so`` files without
requiring the SYCL runtime to be installed or functional.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PI entry point pattern — all DPC++ PI functions start with ``pi``
# and use CamelCase (e.g., piPlatformsGet, piDeviceGetInfo).
# ---------------------------------------------------------------------------
_PI_SYMBOL_RE = re.compile(r"^pi[A-Z]\w+$")

# Known DPC++ plugin library name patterns.
_PLUGIN_NAME_RE = re.compile(r"^libpi_(\w+)\.so")

# Well-known PI entry points that must be present for a valid plugin.
PI_REQUIRED_ENTRYPOINTS: frozenset[str] = frozenset({
    "piPluginInit",
    "piPlatformsGet",
    "piPlatformGetInfo",
    "piDevicesGet",
    "piDeviceGetInfo",
    "piContextCreate",
    "piContextRelease",
    "piQueueCreate",
    "piQueueRelease",
    "piMemBufferCreate",
    "piMemRelease",
    "piProgramCreate",
    "piProgramBuild",
    "piProgramRelease",
    "piKernelCreate",
    "piKernelRelease",
    "piEnqueueKernelLaunch",
    "piEventsWait",
    "piEventRelease",
})

# Backend type detection from plugin library name.
_BACKEND_MAP: dict[str, str] = {
    "level_zero": "level_zero",
    "opencl": "opencl",
    "cuda": "cuda",
    "hip": "hip",
    "esimd_emulator": "esimd_emulator",
    "native_cpu": "native_cpu",
    "unified_runtime": "unified_runtime",
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class SyclPluginInfo:
    """Metadata for a single PI backend plugin."""

    name: str                           # e.g. "level_zero", "opencl", "cuda"
    library: str                        # e.g. "libpi_level_zero.so"
    pi_version: str = ""                # PI interface version (if detectable)
    entry_points: list[str] = field(default_factory=list)  # exported pi* symbols
    backend_type: str = ""              # "level_zero" | "opencl" | "cuda" | ...
    min_driver_version: str | None = None  # minimum backend driver version


@dataclass
class SyclMetadata:
    """SYCL runtime + plugin interface metadata for one distribution."""

    implementation: str = ""            # "dpcpp" | "adaptivecpp" | "computecpp"
    runtime_version: str = ""           # e.g. "2025.2.0"
    pi_version: str = ""                # PI interface version of the runtime
    plugins: list[SyclPluginInfo] = field(default_factory=list)
    plugin_search_paths: list[str] = field(default_factory=list)

    @property
    def plugin_map(self) -> dict[str, SyclPluginInfo]:
        """Plugin name -> SyclPluginInfo lookup."""
        return {p.name: p for p in self.plugins}


# ---------------------------------------------------------------------------
# Static extraction — uses pyelftools, no SYCL runtime needed
# ---------------------------------------------------------------------------

def _extract_pi_symbols(so_path: Path) -> list[str]:
    """Extract exported PI function names from a plugin .so via pyelftools.

    Returns an empty list on parse errors (logged as WARNING).
    """
    try:
        from elftools.common.exceptions import ELFError
        from elftools.elf.elffile import ELFFile
        from elftools.elf.sections import SymbolTableSection
    except ImportError:
        log.warning("pyelftools not installed; cannot extract PI symbols from %s", so_path)
        return []

    pi_symbols: list[str] = []
    try:
        with open(so_path, "rb") as f:
            elf = ELFFile(f)
            for section in elf.iter_sections():
                if not isinstance(section, SymbolTableSection):
                    continue
                for sym in section.iter_symbols():
                    name = sym.name
                    if not name:
                        continue
                    # Only exported (GLOBAL/WEAK, not UND) symbols matching PI pattern
                    info_bind = sym.entry["st_info"]["bind"]
                    shndx = sym.entry["st_shndx"]
                    if info_bind in ("STB_GLOBAL", "STB_WEAK") and shndx != "SHN_UNDEF":
                        if _PI_SYMBOL_RE.match(name):
                            pi_symbols.append(name)
    except (ELFError, OSError, ValueError) as exc:
        log.warning("Failed to extract PI symbols from %s: %s", so_path, exc)
    return sorted(pi_symbols)


def _detect_backend_type(plugin_name: str) -> str:
    """Map plugin name to backend type string."""
    return _BACKEND_MAP.get(plugin_name, plugin_name)


def _detect_pi_version_from_symbols(symbols: list[str]) -> str:
    """Heuristic PI version detection from exported symbol set.

    PI versions add new entry points over time. This uses landmark
    symbols to estimate the minimum PI version.

    Returns empty string if version cannot be determined.
    """
    # PI 1.2+ added piextUSM* and piextQueue* families
    has_usm = any(s.startswith("piextUSM") for s in symbols)
    has_queue_ext = any(s.startswith("piextQueue") for s in symbols)
    # PI 1.1+ added piextDevice* family
    has_device_ext = any(s.startswith("piextDevice") for s in symbols)

    if has_usm and has_queue_ext:
        return "1.2"
    if has_device_ext:
        return "1.1"
    if "piPluginInit" in symbols:
        return "1.0"
    return ""


def parse_sycl_plugin(so_path: Path) -> SyclPluginInfo | None:
    """Parse a single SYCL PI plugin .so and extract metadata.

    Returns None if the file is not a valid PI plugin (no piPluginInit).
    """
    name_match = _PLUGIN_NAME_RE.match(so_path.name)
    if not name_match:
        log.debug("Not a PI plugin (name mismatch): %s", so_path.name)
        return None

    plugin_name = name_match.group(1)
    entry_points = _extract_pi_symbols(so_path)

    if "piPluginInit" not in entry_points:
        log.warning("Plugin %s missing piPluginInit — not a valid PI plugin", so_path)
        return None

    return SyclPluginInfo(
        name=plugin_name,
        library=so_path.name,
        pi_version=_detect_pi_version_from_symbols(entry_points),
        entry_points=entry_points,
        backend_type=_detect_backend_type(plugin_name),
    )


def discover_sycl_plugins(
    search_paths: list[Path],
) -> list[SyclPluginInfo]:
    """Discover and parse all PI plugins in the given search paths.

    Scans directories for files matching ``libpi_*.so`` and extracts
    PI metadata from each.
    """
    plugins: list[SyclPluginInfo] = []
    seen: set[str] = set()

    for search_dir in search_paths:
        if not search_dir.is_dir():
            log.debug("SYCL plugin search path does not exist: %s", search_dir)
            continue
        for entry in sorted(search_dir.iterdir()):
            if not entry.is_file():
                continue
            if entry.name in seen:
                continue
            if not _PLUGIN_NAME_RE.match(entry.name):
                continue
            seen.add(entry.name)
            plugin = parse_sycl_plugin(entry)
            if plugin is not None:
                plugins.append(plugin)

    return plugins


def _detect_sycl_implementation(lib_dir: Path) -> str:
    """Heuristic to detect which SYCL implementation is present."""
    # DPC++ ships libsycl.so alongside libpi_*.so plugins
    if (lib_dir / "libsycl.so").exists() or any(
        lib_dir.glob("libsycl.so.*")
    ):
        return "dpcpp"
    # AdaptiveCpp uses libacpp-rt.so
    if (lib_dir / "libacpp-rt.so").exists() or any(
        lib_dir.glob("libhipsycl-rt.so*")
    ):
        return "adaptivecpp"
    return ""


def _default_plugin_search_paths() -> list[Path]:
    """Return default DPC++ plugin search paths from environment.

    DPC++ looks for plugins in:
    1. SYCL_PI_PLUGINS_DIR (if set)
    2. <libdir>/sycl/ (relative to libsycl.so)
    3. Directories in LD_LIBRARY_PATH
    """
    paths: list[Path] = []
    pi_dir = os.environ.get("SYCL_PI_PLUGINS_DIR")
    if pi_dir:
        paths.append(Path(pi_dir))
    return paths


def parse_sycl_metadata(
    lib_dir: Path,
    *,
    extra_plugin_paths: list[Path] | None = None,
) -> SyclMetadata | None:
    """Extract SYCL metadata from a distribution directory.

    Args:
        lib_dir: Directory containing libsycl.so and/or PI plugins.
        extra_plugin_paths: Additional directories to scan for plugins.

    Returns:
        SyclMetadata if SYCL artifacts detected, None otherwise.
    """
    implementation = _detect_sycl_implementation(lib_dir)
    if not implementation:
        return None

    # Build plugin search path list
    search_paths = [lib_dir]
    # DPC++ convention: plugins in <libdir>/ or <libdir>/sycl/
    sycl_subdir = lib_dir / "sycl"
    if sycl_subdir.is_dir():
        search_paths.append(sycl_subdir)
    if extra_plugin_paths:
        search_paths.extend(extra_plugin_paths)
    search_paths.extend(_default_plugin_search_paths())

    plugins = discover_sycl_plugins(search_paths)

    # Detect runtime PI version from plugin versions (take the max)
    pi_versions = [p.pi_version for p in plugins if p.pi_version]
    runtime_pi_version = max(pi_versions) if pi_versions else ""

    return SyclMetadata(
        implementation=implementation,
        pi_version=runtime_pi_version,
        plugins=plugins,
        plugin_search_paths=[str(p) for p in search_paths],
    )
