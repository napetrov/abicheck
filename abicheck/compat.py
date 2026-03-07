"""Sprint 5: ABICC drop-in compatibility layer.

Implements:
- ABICC XML descriptor parsing (defusedxml, XXE-safe)
- ``CompatDescriptor`` dataclass matching ABICC's -old/-new descriptor format
- ``parse_descriptor()`` — validates required fields, supports multi-value tags

Typical ABICC descriptor (old.xml):
    <version>2025.0</version>
    <headers>/usr/include/dnnl</headers>
    <libs>/usr/lib/libdnnl.so</libs>

Extended form (multiple headers/libs):
    <version>2025.0</version>
    <headers>/usr/include/dnnl</headers>
    <headers>/usr/include/dnnl/detail</headers>
    <libs>/usr/lib/libdnnl.so</libs>
    <libs>/usr/lib/libdnnl_extra.so</libs>
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import defusedxml.ElementTree as ET

log = logging.getLogger(__name__)


@dataclass
class CompatDescriptor:
    """Parsed ABICC XML descriptor."""
    version: str
    headers: list[Path]
    libs: list[Path]
    path: Path = field(default_factory=lambda: Path("."))


def parse_descriptor(path: Path) -> CompatDescriptor:
    """Parse an ABICC XML descriptor file.

    Args:
        path: Path to the descriptor XML file.

    Returns:
        Populated CompatDescriptor.

    Raises:
        ValueError: If required fields (version, libs) are missing or empty.
        FileNotFoundError: If the descriptor file does not exist.
    """
    if not path.exists():
        raise FileNotFoundError(f"Descriptor not found: {path}")

    try:
        tree = ET.parse(str(path))  # defusedxml.ElementTree.parse
    except ET.ParseError as exc:
        raise ValueError(f"Invalid XML in descriptor {path}: {exc}") from exc

    root = tree.getroot()
    base = path.parent

    def _get_all(tag: str) -> list[str]:
        return [el.text.strip() for el in root.iter(tag) if el.text and el.text.strip()]

    version_vals = _get_all("version")
    if not version_vals:
        raise ValueError(f"Descriptor {path}: missing <version> element")
    version = version_vals[0]

    lib_strs = _get_all("libs")
    if not lib_strs:
        raise ValueError(f"Descriptor {path}: missing <libs> element")
    libs = [_resolve(s, base) for s in lib_strs]

    header_strs = _get_all("headers")
    headers = [_resolve(s, base) for s in header_strs]

    log.debug("Parsed descriptor %s: version=%s, %d lib(s), %d header dir(s)",
              path, version, len(libs), len(headers))

    return CompatDescriptor(version=version, headers=headers, libs=libs, path=path)


def _resolve(p: str, base: Path) -> Path:
    """Return absolute path; resolve relative paths against the descriptor's directory."""
    resolved = Path(p)
    if not resolved.is_absolute():
        resolved = (base / resolved).resolve()
    return resolved
