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

"""Debian symbols file generation, parsing, validation, and diffing.

Implements the ``dpkg-gensymbols(1)`` symbols file format used by Debian/Ubuntu
packaging for fine-grained shared library dependency tracking.

Format reference:
  https://manpages.debian.org/unstable/dpkg-dev/dpkg-gensymbols.1.en.html

A symbols file has the structure::

    libfoo.so.1 libfoo1 #MINVER#
     _ZN3foo3barEv@Base 1.0
     (c++)"foo::bar()@Base" 1.0
     (arch=amd64)_ZN3foo3bazEv@Base 1.0
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from .demangle import demangle
from .elf_metadata import ElfMetadata, ElfSymbol, SymbolType, parse_elf_metadata

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

# Regex for parsing optional tags like (c++), (arch=amd64), (symver), etc.
_TAG_RE = re.compile(r"^\(([^)]+)\)")


@dataclass
class DebianSymbolEntry:
    """One symbol line in a Debian symbols file."""
    name: str               # symbol name (mangled or demangled with quotes)
    version_node: str       # "Base" or a version node like "LIBFOO_1.0"
    min_version: str        # minimum package version where this symbol appeared
    tags: list[str] = field(default_factory=list)  # e.g. ["c++", "arch=amd64"]

    @property
    def is_cpp(self) -> bool:
        return "c++" in self.tags

    @property
    def mangled_name(self) -> str:
        """Return the mangled symbol name (strip quotes from demangled C++ form)."""
        if self.is_cpp:
            # (c++)"foo::bar()@Base" → the name field is foo::bar()
            # The mangled name is not stored; return name as-is for matching
            return self.name
        # For non-C++ entries, name is the mangled form (before @)
        return self.name

    def format_line(self) -> str:
        """Format as a Debian symbols file line (without leading space)."""
        tag_prefix = "".join(f"({t})" for t in self.tags)
        if self.is_cpp:
            return f'{tag_prefix}"{self.name}@{self.version_node}" {self.min_version}'
        return f"{tag_prefix}{self.name}@{self.version_node} {self.min_version}"


@dataclass
class DebianSymbolsFile:
    """Parsed Debian symbols file."""
    library: str            # SONAME, e.g. "libfoo.so.1"
    package: str            # package name, e.g. "libfoo1"
    min_version: str        # #MINVER# or a version string
    symbols: list[DebianSymbolEntry] = field(default_factory=list)

    def format(self) -> str:
        """Format the complete Debian symbols file."""
        lines = [f"{self.library} {self.package} {self.min_version}"]
        for sym in sorted(self.symbols, key=lambda s: s.name):
            lines.append(f" {sym.format_line()}")
        return "\n".join(lines) + "\n"


@dataclass
class ValidationResult:
    """Result of validating a symbols file against a binary."""
    library: str
    missing: list[DebianSymbolEntry] = field(default_factory=list)
    new_symbols: list[str] = field(default_factory=list)  # "name@version_node"
    passed: bool = True


@dataclass
class SymbolsDiff:
    """Diff between two Debian symbols files."""
    added: list[DebianSymbolEntry] = field(default_factory=list)
    removed: list[DebianSymbolEntry] = field(default_factory=list)
    version_changed: list[tuple[DebianSymbolEntry, DebianSymbolEntry]] = field(
        default_factory=list,
    )  # (old, new)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_symbols_file(text: str) -> DebianSymbolsFile:
    """Parse a Debian symbols file from its text content.

    Raises ``ValueError`` on malformed input.
    """
    lines = text.splitlines()
    if not lines:
        raise ValueError("Empty symbols file")

    # First line: "libfoo.so.1 libfoo1 #MINVER#"
    header_parts = lines[0].split(None, 2)
    if len(header_parts) < 3:
        raise ValueError(f"Malformed header line: {lines[0]!r}")

    result = DebianSymbolsFile(
        library=header_parts[0],
        package=header_parts[1],
        min_version=header_parts[2],
    )

    for lineno, line in enumerate(lines[1:], start=2):
        if not line or not line.startswith(" "):
            continue  # skip blank or non-symbol lines
        entry = _parse_symbol_line(line.strip(), lineno)
        if entry is not None:
            result.symbols.append(entry)

    return result


def _parse_symbol_line(line: str, lineno: int) -> DebianSymbolEntry | None:
    """Parse a single symbol line (already stripped of leading whitespace).

    Handles forms like::

        _ZN3foo3barEv@Base 1.0
        (c++)"foo::bar()@Base" 1.0
        (c++|optional)"foo::bar()@Base" 1.0
        (arch=amd64)_ZN3foo3barEv@Base 1.0
    """
    tags: list[str] = []
    rest = line

    # Extract leading tags: (tag1)(tag2)...
    while rest.startswith("("):
        m = _TAG_RE.match(rest)
        if not m:
            break
        tag_content = m.group(1)
        # A tag may contain pipe-separated values: (c++|optional)
        for t in tag_content.split("|"):
            tags.append(t.strip())
        rest = rest[m.end():]

    is_cpp = "c++" in tags

    if is_cpp:
        # C++ form: "demangled_name@VersionNode" min_version
        if not rest.startswith('"'):
            _log.warning("Line %d: expected quoted C++ symbol: %s", lineno, line)
            return None
        # Find closing quote
        end_quote = rest.index('"', 1) if '"' in rest[1:] else -1
        if end_quote == -1:
            _log.warning("Line %d: unterminated quote: %s", lineno, line)
            return None
        quoted = rest[1:end_quote]
        remainder = rest[end_quote + 1:].strip()
        # quoted = "foo::bar()@Base"
        at_idx = quoted.rfind("@")
        if at_idx == -1:
            _log.warning("Line %d: missing @version in quoted symbol: %s", lineno, line)
            return None
        name = quoted[:at_idx]
        version_node = quoted[at_idx + 1:]
        min_version = remainder if remainder else ""
    else:
        # Non-C++ form: mangled_name@VersionNode min_version
        parts = rest.split(None, 1)
        if not parts:
            return None
        sym_ver = parts[0]
        min_version = parts[1] if len(parts) > 1 else ""
        at_idx = sym_ver.rfind("@")
        if at_idx == -1:
            _log.warning("Line %d: missing @version: %s", lineno, line)
            return None
        name = sym_ver[:at_idx]
        version_node = sym_ver[at_idx + 1:]

    return DebianSymbolEntry(
        name=name,
        version_node=version_node,
        min_version=min_version.strip(),
        tags=tags,
    )


def load_symbols_file(path: Path) -> DebianSymbolsFile:
    """Load and parse a Debian symbols file from disk."""
    return parse_symbols_file(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def _symbol_version_node(sym: ElfSymbol) -> str:
    """Determine the version node for a symbol.

    Returns the ELF version tag (e.g. "LIBFOO_1.0") if present,
    otherwise "Base" (the Debian convention for unversioned symbols).
    """
    if sym.version:
        return sym.version
    return "Base"


def generate_symbols_file(
    elf_meta: ElfMetadata,
    *,
    package: str = "",
    version: str = "#MINVER#",
    use_cpp: bool = True,
) -> DebianSymbolsFile:
    """Generate a Debian symbols file from ELF metadata.

    Args:
        elf_meta: Parsed ELF metadata (from ``parse_elf_metadata``).
        package: Debian package name. If empty, derived from SONAME.
        version: Version string for the minimum version field.
        use_cpp: If True, emit C++ symbols in demangled ``(c++)`` form.

    Returns:
        A ``DebianSymbolsFile`` ready to be formatted.
    """
    soname = elf_meta.soname or "UNKNOWN"

    if not package:
        # Derive package name from SONAME: libfoo.so.1 → libfoo1
        package = _soname_to_package(soname)

    result = DebianSymbolsFile(
        library=soname,
        package=package,
        min_version=version,
    )

    for sym in elf_meta.symbols:
        # Skip symbols that are not exported functions or objects
        if sym.sym_type not in (SymbolType.FUNC, SymbolType.OBJECT, SymbolType.IFUNC):
            continue

        ver_node = _symbol_version_node(sym)
        tags: list[str] = []
        name = sym.name

        # Try to demangle C++ symbols
        if use_cpp:
            demangled = demangle(sym.name)
            if demangled is not None:
                tags.append("c++")
                name = demangled

        result.symbols.append(DebianSymbolEntry(
            name=name,
            version_node=ver_node,
            min_version=version,
            tags=tags,
        ))

    return result


def generate_from_binary(
    so_path: Path,
    *,
    package: str = "",
    version: str = "#MINVER#",
    use_cpp: bool = True,
) -> DebianSymbolsFile:
    """Generate a Debian symbols file directly from a shared library binary.

    Convenience wrapper around ``parse_elf_metadata`` + ``generate_symbols_file``.
    """
    elf_meta = parse_elf_metadata(so_path)
    return generate_symbols_file(
        elf_meta,
        package=package,
        version=version,
        use_cpp=use_cpp,
    )


def _soname_to_package(soname: str) -> str:
    """Derive a Debian package name from a SONAME.

    Examples::

        libfoo.so.1   → libfoo1
        libbar.so.2.3 → libbar2
        libfoo.so     → libfoo
    """
    # Strip .so and everything after, then append major version
    base = soname
    so_idx = base.find(".so")
    if so_idx == -1:
        return base

    lib_base = base[:so_idx]
    version_part = base[so_idx + 3:]  # ".1" or ".2.3" or ""

    if version_part.startswith("."):
        # Extract major version number
        ver_str = version_part[1:]
        dot_idx = ver_str.find(".")
        if dot_idx != -1:
            ver_str = ver_str[:dot_idx]
        return lib_base + ver_str

    return lib_base


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_symbols(
    elf_meta: ElfMetadata,
    symbols_file: DebianSymbolsFile,
) -> ValidationResult:
    """Validate a Debian symbols file against an ELF binary's metadata.

    Checks:
    - Symbols listed in the file but missing from the binary.
    - Symbols exported by the binary but not listed in the file.

    Returns a ``ValidationResult``.
    """
    soname = elf_meta.soname or "UNKNOWN"

    # Build set of exported symbols from binary: "name@version_node"
    binary_syms: dict[str, ElfSymbol] = {}
    binary_mangled_set: set[str] = set()
    for sym in elf_meta.symbols:
        if sym.sym_type not in (SymbolType.FUNC, SymbolType.OBJECT, SymbolType.IFUNC):
            continue
        ver_node = _symbol_version_node(sym)
        key = f"{sym.name}@{ver_node}"
        binary_syms[key] = sym
        binary_mangled_set.add(sym.name)

    # Build demangled → mangled mapping for C++ symbol lookup
    demangled_to_mangled: dict[str, str] = {}
    for sym_name in binary_mangled_set:
        d = demangle(sym_name)
        if d is not None:
            demangled_to_mangled[d] = sym_name

    result = ValidationResult(library=soname)

    # Track which binary symbols are accounted for
    matched_binary_keys: set[str] = set()

    for entry in symbols_file.symbols:
        if entry.is_cpp:
            # Look up by demangled name
            mangled = demangled_to_mangled.get(entry.name)
            if mangled is not None:
                key = f"{mangled}@{entry.version_node}"
                if key in binary_syms:
                    matched_binary_keys.add(key)
                    continue
            # Not found
            result.missing.append(entry)
        else:
            key = f"{entry.name}@{entry.version_node}"
            if key in binary_syms:
                matched_binary_keys.add(key)
            else:
                result.missing.append(entry)

    # Find new symbols (in binary but not in symbols file)
    for key in sorted(binary_syms.keys()):
        if key not in matched_binary_keys:
            result.new_symbols.append(key)

    result.passed = len(result.missing) == 0

    return result


def validate_from_binary(
    so_path: Path,
    symbols_path: Path,
) -> ValidationResult:
    """Validate a symbols file against a binary (convenience wrapper)."""
    elf_meta = parse_elf_metadata(so_path)
    symbols_file = load_symbols_file(symbols_path)
    return validate_symbols(elf_meta, symbols_file)


def format_validation_report(result: ValidationResult) -> str:
    """Format a human-readable validation report."""
    lines = [f"Symbols validation for {result.library}:"]

    lines.append("  MISSING from binary (in symbols file but not exported):")
    if result.missing:
        for entry in result.missing:
            lines.append(f"    {entry.format_line()}")
    else:
        lines.append("    (none)")

    lines.append("  NEW in binary (exported but not in symbols file):")
    if result.new_symbols:
        for sym_key in result.new_symbols:
            lines.append(f"    {sym_key}")
    else:
        lines.append("    (none)")

    n_missing = len(result.missing)
    n_new = len(result.new_symbols)

    if result.passed and n_new == 0:
        lines.append("  Result: PASS")
    elif result.passed:
        lines.append(f"  Result: PASS ({n_new} new symbol{'s' if n_new != 1 else ''})")
    else:
        lines.append(
            f"  Result: FAIL ({n_missing} missing symbol{'s' if n_missing != 1 else ''})"
        )

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------

def diff_symbols_files(
    old: DebianSymbolsFile,
    new: DebianSymbolsFile,
) -> SymbolsDiff:
    """Compute the diff between two Debian symbols files.

    Returns a ``SymbolsDiff`` with added, removed, and version-changed symbols.
    """
    result = SymbolsDiff()

    # Index by (name, version_node, is_cpp) for identity
    def _key(entry: DebianSymbolEntry) -> str:
        return f"{'(c++)' if entry.is_cpp else ''}{entry.name}@{entry.version_node}"

    old_by_name: dict[str, DebianSymbolEntry] = {}
    for entry in old.symbols:
        # Use name + tags as identity key (without version_node for version change detection)
        ident = f"{'(c++)' if entry.is_cpp else ''}{entry.name}"
        old_by_name[ident] = entry

    new_by_name: dict[str, DebianSymbolEntry] = {}
    for entry in new.symbols:
        ident = f"{'(c++)' if entry.is_cpp else ''}{entry.name}"
        new_by_name[ident] = entry

    old_keys = set(old_by_name.keys())
    new_keys = set(new_by_name.keys())

    # Removed: in old but not in new
    for ident in sorted(old_keys - new_keys):
        result.removed.append(old_by_name[ident])

    # Added: in new but not in old
    for ident in sorted(new_keys - old_keys):
        result.added.append(new_by_name[ident])

    # Version changed: same symbol, different min_version
    for ident in sorted(old_keys & new_keys):
        old_entry = old_by_name[ident]
        new_entry = new_by_name[ident]
        if old_entry.min_version != new_entry.min_version:
            result.version_changed.append((old_entry, new_entry))

    return result


def format_diff_report(
    diff: SymbolsDiff,
    old_path: str = "old",
    new_path: str = "new",
) -> str:
    """Format a human-readable diff report."""
    lines = [f"Symbols diff: {old_path} -> {new_path}"]

    lines.append("  ADDED:")
    if diff.added:
        for entry in diff.added:
            lines.append(f"    + {entry.format_line()}")
    else:
        lines.append("    (none)")

    lines.append("  REMOVED:")
    if diff.removed:
        for entry in diff.removed:
            lines.append(f"    - {entry.format_line()}")
    else:
        lines.append("    (none)")

    lines.append("  VERSION CHANGED:")
    if diff.version_changed:
        for old_entry, new_entry in diff.version_changed:
            lines.append(
                f"    {old_entry.name}: {old_entry.min_version} -> {new_entry.min_version}"
            )
    else:
        lines.append("    (none)")

    total = len(diff.added) + len(diff.removed) + len(diff.version_changed)
    lines.append(f"  Total changes: {total}")

    return "\n".join(lines) + "\n"
