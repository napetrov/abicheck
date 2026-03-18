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

"""CLI — abicheck dump | compare | compat (dump | check)."""
from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import click

from .checker import DiffResult, LibraryMetadata, compare
from .compat.abicc_dump_import import import_abicc_perl_dump, looks_like_perl_dump
from .compat.cli import compat_group
from .dumper import dump
from .errors import AbicheckError
from .reporter import to_json, to_markdown
from .serialization import load_snapshot, snapshot_to_json

if TYPE_CHECKING:
    from .policy_file import PolicyFile
    from .suppression import SuppressionList

from . import __version__ as _abicheck_version
from .model import AbiSnapshot

# Number of bytes to read when sniffing file format (covers ELF magic + JSON/Perl head)
_SNIFF_BYTES = 256

_logger = logging.getLogger("abicheck")

_HEADER_EXTS = {".h", ".hh", ".hpp", ".hxx", ".ipp", ".tpp", ".inc"}


def _expand_header_inputs(inputs: list[Path]) -> list[Path]:
    """Expand header inputs where each item can be a file or a directory.

    Directories are scanned recursively for known header extensions.
    """
    out: list[Path] = []
    for p in inputs:
        if not p.exists():
            raise click.ClickException(f"Header file not found or not a file: {p}")
        if p.is_file():
            out.append(p)
            continue
        if p.is_dir():
            found = [
                f for f in p.rglob("*")
                if f.is_file() and f.suffix.lower() in _HEADER_EXTS
            ]
            if not found:
                raise click.ClickException(
                    f"Header directory contains no supported header files: {p}"
                )
            out.extend(sorted(found))
            continue
        raise click.ClickException(f"Header path is neither file nor directory: {p}")

    # Deduplicate while preserving deterministic order
    seen: set[str] = set()
    deduped: list[Path] = []
    for h in out:
        k = str(h.resolve())
        if k in seen:
            continue
        seen.add(k)
        deduped.append(h)
    return deduped


def _setup_verbosity(verbose: bool) -> None:
    """Configure logging verbosity for native commands."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    _logger.addHandler(handler)
    _logger.setLevel(logging.DEBUG if verbose else logging.WARNING)


def _is_elf(path: Path) -> bool:
    """Check if file starts with ELF magic bytes."""
    try:
        with open(path, "rb") as f:
            return f.read(4) == b"\x7fELF"
    except OSError:
        return False


def _is_pe(path: Path) -> bool:
    """Check if file is a PE binary (Windows DLL/EXE)."""
    from .pe_metadata import is_pe
    return is_pe(path)


def _is_macho(path: Path) -> bool:
    """Check if file is a Mach-O binary (macOS dylib/framework)."""
    from .macho_metadata import is_macho
    return is_macho(path)


def _detect_binary_format(path: Path) -> str | None:
    """Detect binary format from magic bytes.

    Returns 'elf', 'pe', 'macho', or None for non-binary / unknown.
    """
    if _is_elf(path):
        return "elf"
    if _is_pe(path):
        return "pe"
    if _is_macho(path):
        return "macho"
    return None


def _sniff_text_format(path: Path) -> str:
    """Read a small header chunk and return 'json', 'perl', or 'unknown'."""
    try:
        with open(path, "rb") as f:
            raw = f.read(_SNIFF_BYTES)
        head = raw.decode("utf-8", errors="replace").lstrip()
    except OSError:
        return "unknown"
    # Check Perl dump BEFORE JSON — a Perl dump can start with $VAR1 = {
    # which would incorrectly match the JSON heuristic after the '{'
    if looks_like_perl_dump(head):
        return "perl"
    if head.startswith("{"):
        return "json"
    return "unknown"


def _dump_native_binary(
    path: Path, binary_fmt: str,
    headers: list[Path], includes: list[Path],
    version: str, lang: str,
    *,
    pdb_path: Path | None = None,
    dwarf_only: bool = False,
) -> AbiSnapshot:
    """Dump ABI snapshot from a native binary (ELF, PE, or Mach-O).

    For ELF, headers are required for full AST analysis unless dwarf_only
    is set or DWARF debug info is available (ADR-003 fallback chain).
    For PE/Mach-O, headers are optional — export tables provide the symbol surface.
    """
    fmt_labels = {"elf": "ELF", "pe": "PE (Windows DLL)", "macho": "Mach-O (macOS dylib)"}
    fmt_label = fmt_labels.get(binary_fmt, binary_fmt)

    if binary_fmt == "elf":
        resolved_headers = _expand_header_inputs(headers) if headers else []
        if not resolved_headers and not dwarf_only:
            click.echo(
                f"Warning: '{path}' — no headers provided. "
                "Will use DWARF debug info if available, else symbols-only mode.",
                err=True,
            )
        # include dirs are only relevant when headers are parsed via castxml
        if resolved_headers and not dwarf_only:
            for inc in includes:
                if not inc.exists() or not inc.is_dir():
                    raise click.ClickException(f"Include directory not found or not a directory: {inc}")
        elif includes and not dwarf_only:
            click.echo(
                "Warning: --include paths are ignored without headers.",
                err=True,
            )
        compiler = "c++" if lang == "c++" else "cc"
        try:
            return dump(
                so_path=path,
                headers=resolved_headers,
                extra_includes=includes,
                version=version,
                compiler=compiler,
                lang=lang if lang == "c" else None,
                dwarf_only=dwarf_only,
            )
        except (AbicheckError, RuntimeError, OSError, ValueError) as exc:
            raise click.ClickException(f"Failed to dump '{path}': {exc}") from exc

    if binary_fmt == "pe":
        from .pe_metadata import parse_pe_metadata
        try:
            pe_meta = parse_pe_metadata(path)
        except ImportError as exc:
            raise click.ClickException(str(exc)) from exc
        except (RuntimeError, OSError, ValueError) as exc:
            raise click.ClickException(f"Failed to parse PE '{path}': {exc}") from exc
        if not pe_meta.machine:
            raise click.ClickException(
                f"Failed to extract PE metadata from '{path}'. "
                "The file may be corrupt or not a valid PE binary."
            )
        if not pe_meta.exports:
            raise click.ClickException(
                f"PE file '{path}' has no exports (named or ordinal). "
                "Verify the file is a valid DLL."
            )
        # Build snapshot from PE export table — include ordinal-only exports
        from .model import Function, Visibility
        funcs = [
            Function(
                name=(exp.name or f"ordinal:{exp.ordinal}"),
                mangled=(exp.name or f"ordinal:{exp.ordinal}"),
                return_type="?",
                visibility=Visibility.PUBLIC,
                is_extern_c=not (exp.name or "").startswith("?"),  # MSVC mangling uses ? prefix
            )
            for exp in pe_meta.exports
        ]

        # PDB debug info extraction (struct layouts, enums, calling conventions)
        dwarf_meta = None
        dwarf_adv = None
        try:
            from .pdb_metadata import parse_pdb_debug_info
            from .pdb_utils import locate_pdb
            pdb_file = locate_pdb(
                path, pdb_path_override=pdb_path,
                allow_network=False,  # never auto-download from symbol servers
            )
            if pdb_file is not None:
                dwarf_meta, dwarf_adv = parse_pdb_debug_info(pdb_file)
                _logger.info("PDB debug info loaded from %s", pdb_file)
            else:
                _logger.debug("No PDB file found for %s", path)
        except Exception as exc:  # noqa: BLE001
            _logger.warning("PDB parsing failed for %s: %s", path, exc)

        return AbiSnapshot(
            library=path.name, version=version,
            functions=funcs, pe=pe_meta,
            dwarf=dwarf_meta,
            dwarf_advanced=dwarf_adv,
            platform="pe",
        )

    if binary_fmt == "macho":
        from .macho_metadata import parse_macho_metadata
        try:
            macho_meta = parse_macho_metadata(path)
        except (RuntimeError, OSError, ValueError) as exc:
            raise click.ClickException(
                f"Failed to parse Mach-O '{path}': {exc}"
            ) from exc
        if not macho_meta.exports and not macho_meta.install_name and not macho_meta.dependent_libs:
            raise click.ClickException(
                f"Mach-O file '{path}' has no exports or load-command metadata. "
                "Verify the file is a valid dynamic library."
            )
        # Build snapshot from Mach-O export table
        from .model import Function, Visibility
        funcs = [
            Function(
                name=exp.name, mangled=exp.name, return_type="?",
                visibility=Visibility.PUBLIC,
                is_extern_c=not exp.name.startswith("_Z"),
            )
            for exp in macho_meta.exports if exp.name
        ]
        return AbiSnapshot(
            library=path.name, version=version,
            functions=funcs, macho=macho_meta,
            platform="macho",
        )

    raise click.ClickException(f"Unsupported binary format: {fmt_label}")


def _resolve_input(
    path: Path,
    headers: list[Path],
    includes: list[Path],
    version: str,
    lang: str,
    *,
    is_elf: bool | None = None,
    pdb_path: Path | None = None,
    dwarf_only: bool = False,
) -> AbiSnapshot:
    """Auto-detect input type and return an AbiSnapshot.

    Detection order:
    1. Native binary (ELF / PE / Mach-O, detected by magic bytes)
    2. ABICC Perl dump (``$VAR1`` prefix) → :func:`import_abicc_perl_dump`
    3. JSON snapshot (``{`` prefix) → :func:`load_snapshot`

    Args:
        path: Path to the input file.
        headers: Public header files (required for ELF inputs).
        includes: Extra include directories (used for ELF inputs).
        version: Version label to embed in the resulting snapshot.
        lang: Language mode for castxml (``c++`` or ``c``).
        is_elf: Pre-computed ELF detection result; if *None*, detection is
            performed here (avoids a second ``open()`` when the caller already
            knows the result).
        dwarf_only: If True, force DWARF-only mode (ADR-003).
    """
    # Fast path: caller already knows it's ELF
    if is_elf is True:
        return _dump_native_binary(
            path, "elf", headers, includes, version, lang,
            dwarf_only=dwarf_only,
        )

    # Detect binary format from magic bytes
    binary_fmt = _detect_binary_format(path) if is_elf is None else None
    if binary_fmt is not None:
        return _dump_native_binary(
            path, binary_fmt, headers, includes, version, lang,
            pdb_path=pdb_path,
            dwarf_only=dwarf_only,
        )

    # Text-based formats: detect by sniffing only a small header chunk
    fmt = _sniff_text_format(path)

    if fmt == "perl":
        try:
            return import_abicc_perl_dump(path)
        except (ValueError, KeyError, UnicodeDecodeError, OSError, AbicheckError) as exc:
            raise click.ClickException(
                f"Failed to import ABICC Perl dump '{path}': {exc}"
            ) from exc

    if fmt == "json":
        try:
            return load_snapshot(path)
        except (ValueError, KeyError, UnicodeDecodeError, OSError) as exc:
            raise click.ClickException(
                f"Failed to load JSON snapshot '{path}': {exc}"
            ) from exc

    raise click.UsageError(
        f"Cannot detect format of '{path}'. "
        "Expected: ELF (.so), PE (.dll), Mach-O (.dylib), JSON snapshot, or ABICC Perl dump."
    )


def _collect_metadata(path: Path) -> LibraryMetadata:
    """Compute SHA-256 and file size for a library artifact."""
    import hashlib

    data = path.read_bytes()
    return LibraryMetadata(
        path=str(path),
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
    )


@click.group()
@click.version_option(version=_abicheck_version, prog_name="abicheck")
def main() -> None:
    """abicheck — ABI compatibility checker for C/C++ shared libraries."""


def _populate_dependency_info(
    snap: AbiSnapshot, so_path: Path,
    search_paths: list[Path], sysroot: Path | None, ld_library_path: str,
) -> None:
    """Resolve transitive deps and store DependencyInfo in the snapshot."""
    from .binder import BindingStatus, compute_bindings
    from .model import DependencyInfo
    from .resolver import resolve_dependencies

    graph = resolve_dependencies(
        so_path,
        search_paths=search_paths or None,
        sysroot=sysroot,
        ld_library_path=ld_library_path,
    )
    bindings = compute_bindings(graph)

    summary: dict[str, int] = {}
    for b in bindings:
        summary[b.status.value] = summary.get(b.status.value, 0) + 1

    missing = [
        {"consumer": b.consumer, "symbol": b.symbol, "version": b.version}
        for b in bindings if b.status == BindingStatus.MISSING
    ]

    snap.dependency_info = DependencyInfo(
        nodes=[
            {
                "path": str(node.path),
                "soname": node.soname,
                "needed": node.needed,
                "depth": node.depth,
                "resolution_reason": node.resolution_reason,
            }
            for node in sorted(graph.nodes.values(), key=lambda n: (n.depth, n.soname))
        ],
        edges=[
            {"consumer": consumer, "provider": provider}
            for consumer, provider in graph.edges
        ],
        unresolved=[
            {"consumer": consumer, "soname": soname}
            for consumer, soname in graph.unresolved
        ],
        bindings_summary=summary,
        missing_symbols=missing,
    )


@main.command("dump")
@click.argument("so_path", type=click.Path(exists=True, path_type=Path))
@click.option("-H", "--header", "headers", multiple=True, type=click.Path(exists=True, path_type=Path),
              help="Public header file or directory (repeat for multiple).")
@click.option("-I", "--include", "includes", multiple=True, type=click.Path(path_type=Path),
              help="Extra include directory for castxml.")
@click.option("--version", "version", default="unknown", show_default=True,
              help="Library version string to embed in snapshot.")
@click.option("--lang", default="c++", show_default=True,
              type=click.Choice(["c++", "c"], case_sensitive=False),
              help="Language mode for castxml.")
@click.option("-o", "--output", "output", type=click.Path(path_type=Path), default=None,
              help="Output JSON file. Defaults to stdout.")
# ── Cross-compilation flags ───────────────────────────────────────────────────
@click.option("--gcc-path", default=None,
              help="Path to GCC/G++ cross-compiler binary.")
@click.option("--gcc-prefix", default=None,
              help="Cross-toolchain prefix (e.g. aarch64-linux-gnu-).")
@click.option("--gcc-options", default=None,
              help="Extra compiler flags passed through to castxml.")
@click.option("--sysroot", type=click.Path(path_type=Path), default=None,
              help="Alternative system root directory.")
@click.option("--nostdinc", is_flag=True, default=False,
              help="Do not search standard system include paths.")
@click.option("--pdb-path", "pdb_path", type=click.Path(path_type=Path), default=None,
              help="Explicit path to PDB file for Windows PE debug info. "
                   "Overrides automatic PDB discovery from the PE debug directory.")
@click.option("--follow-deps", is_flag=True, default=False,
              help="Resolve transitive DT_NEEDED dependencies and include the full "
                   "dependency graph and symbol binding status in the snapshot. "
                   "ELF only.")
@click.option("--search-path", "search_paths", multiple=True,
              type=click.Path(exists=True, path_type=Path),
              help="Additional directory to search for shared libraries (with --follow-deps).")
@click.option("--ld-library-path", "ld_library_path", default="",
              help="Simulated LD_LIBRARY_PATH (with --follow-deps).")
@click.option("--dwarf-only", is_flag=True, default=False,
              help="Force DWARF-only mode: use DWARF debug info as the primary "
                   "data source even when headers are available. Enables 24/30 "
                   "detectors without requiring castxml.")
@click.option("--show-data-sources", is_flag=True, default=False,
              help="Print which data layers (L0/L1/L2) are available for the "
                   "binary and exit.")
@click.option("-v", "--verbose", is_flag=True, default=False,
              help="Enable verbose/debug output.")
def dump_cmd(so_path: Path, headers: tuple[Path, ...], includes: tuple[Path, ...],
             version: str, lang: str, output: Path | None,
             gcc_path: str | None, gcc_prefix: str | None, gcc_options: str | None,
             sysroot: Path | None, nostdinc: bool, pdb_path: Path | None,
             follow_deps: bool, search_paths: tuple[Path, ...], ld_library_path: str,
             dwarf_only: bool, show_data_sources: bool,
             verbose: bool) -> None:
    """Dump ABI snapshot of a shared library to JSON.

    \b
    Example:
      abicheck dump libfoo.so.1 -H include/foo.h --version 1.2.3 -o snap.json
      abicheck dump libfoo.so.1 -H include/foo.h --lang c -o snap.json
      abicheck dump libfoo.so.1 -H include/foo.h --gcc-prefix aarch64-linux-gnu-
      abicheck dump libfoo.so.1 --follow-deps -o snap.json
      abicheck dump libfoo.so.1 --dwarf-only -o snap.json
      abicheck dump libfoo.so.1 --show-data-sources
    """
    _setup_verbosity(verbose)

    # --show-data-sources: diagnostic output and exit
    if show_data_sources:
        _print_data_sources(so_path, bool(headers))
        return

    # Auto-detect binary format — PE/Mach-O skip the ELF/castxml path
    binary_fmt = _detect_binary_format(so_path)
    if binary_fmt in ("pe", "macho"):
        if follow_deps:
            click.echo("Warning: --follow-deps is only supported for ELF binaries.", err=True)
        try:
            snap = _dump_native_binary(
                so_path, binary_fmt, list(headers), list(includes), version, lang,
                pdb_path=pdb_path,
            )
        except click.ClickException:
            raise
        except (AbicheckError, RuntimeError, OSError, ValueError) as exc:
            raise click.ClickException(str(exc)) from exc
        result = snapshot_to_json(snap)
        if output:
            output.write_text(result, encoding="utf-8")
            click.echo(f"Snapshot written to {output}", err=True)
        else:
            click.echo(result)
        return

    compiler = "c++" if lang == "c++" else "cc"
    resolved_headers = _expand_header_inputs(list(headers)) if headers else []
    try:
        snap = dump(
            so_path=so_path,
            headers=resolved_headers,
            extra_includes=list(includes),
            version=version,
            compiler=compiler,
            gcc_path=gcc_path,
            gcc_prefix=gcc_prefix,
            gcc_options=gcc_options,
            sysroot=sysroot,
            nostdinc=nostdinc,
            lang=lang if lang == "c" else None,
            dwarf_only=dwarf_only,
        )
    except (AbicheckError, RuntimeError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc

    if follow_deps:
        _populate_dependency_info(snap, so_path, list(search_paths), sysroot, ld_library_path)

    result = snapshot_to_json(snap)
    if output:
        output.write_text(result, encoding="utf-8")
        click.echo(f"Snapshot written to {output}", err=True)
    else:
        click.echo(result)


def _print_data_sources(so_path: Path, has_headers: bool) -> None:
    """Print data source diagnostic information for a binary."""
    from .dwarf_snapshot import show_data_sources

    binary_fmt = _detect_binary_format(so_path)
    elf_meta = None
    dwarf_meta = None

    if binary_fmt == "elf":
        from .dwarf_unified import parse_dwarf
        from .elf_metadata import parse_elf_metadata
        elf_meta = parse_elf_metadata(so_path)
        dwarf_meta, _ = parse_dwarf(so_path)

    click.echo(show_data_sources(so_path, elf_meta, dwarf_meta, has_headers))


def _resolve_per_side_options(
    headers: tuple[Path, ...], includes: tuple[Path, ...],
    old_headers_only: tuple[Path, ...], new_headers_only: tuple[Path, ...],
    old_includes_only: tuple[Path, ...], new_includes_only: tuple[Path, ...],
) -> tuple[list[Path], list[Path], list[Path], list[Path]]:
    """Resolve per-side headers/includes: --old-header overrides -H, etc."""
    old_h = list(old_headers_only) if old_headers_only else list(headers)
    new_h = list(new_headers_only) if new_headers_only else list(headers)
    old_inc = list(old_includes_only) if old_includes_only else list(includes)
    new_inc = list(new_includes_only) if new_includes_only else list(includes)
    return old_h, new_h, old_inc, new_inc


def _warn_ignored_flags(
    old_is_binary: bool, new_is_binary: bool,
    headers: tuple[Path, ...], includes: tuple[Path, ...],
    old_headers_only: tuple[Path, ...], new_headers_only: tuple[Path, ...],
    old_includes_only: tuple[Path, ...], new_includes_only: tuple[Path, ...],
) -> None:
    """Warn if dump-only options are provided but not used (both inputs are snapshots)."""
    if old_is_binary or new_is_binary:
        return
    flag_pairs: list[tuple[tuple[Path, ...], str]] = [
        (headers, "-H/--header"),
        (old_headers_only, "--old-header"),
        (new_headers_only, "--new-header"),
        (includes, "-I/--include"),
        (old_includes_only, "--old-include"),
        (new_includes_only, "--new-include"),
    ]
    ignored_flags = [label for value, label in flag_pairs if value]
    if ignored_flags:
        click.echo(
            f"Warning: {', '.join(ignored_flags)} ignored when both inputs are snapshots.",
            err=True,
        )


def _load_suppression_and_policy(
    suppress: Path | None, policy: str, policy_file_path: Path | None,
) -> tuple[SuppressionList | None, PolicyFile | None]:
    """Load suppression list and policy file from CLI arguments."""
    from .policy_file import PolicyFile
    from .suppression import SuppressionList

    suppression: SuppressionList | None = None
    if suppress is not None:
        try:
            suppression = SuppressionList.load(suppress)
        except (ValueError, OSError) as e:
            raise click.BadParameter(str(e), param_hint="--suppress") from e

    pf: PolicyFile | None = None
    if policy_file_path is not None:
        try:
            pf = PolicyFile.load(policy_file_path)
        except ImportError as e:
            raise click.ClickException(str(e)) from e
        except (ValueError, OSError) as e:
            raise click.BadParameter(str(e), param_hint="--policy-file") from e
        if policy != "strict_abi":
            click.echo(
                f"Warning: --policy={policy!r} is ignored when --policy-file is given. "
                "Set base_policy in the YAML file to override the base policy.",
                err=True,
            )
    return suppression, pf


def _render_output(
    fmt: str, result: DiffResult, old: AbiSnapshot, new: AbiSnapshot | None = None,
    *, follow_deps: bool = False,
) -> str:
    """Render comparison result in the requested output format."""
    if fmt == "json":
        base = to_json(result)
        if follow_deps and (old.dependency_info or (new and new.dependency_info)):
            import json
            d = json.loads(base)
            if old.dependency_info:
                from dataclasses import asdict
                d["old_dependency_info"] = asdict(old.dependency_info)
            if new and new.dependency_info:
                from dataclasses import asdict
                d["new_dependency_info"] = asdict(new.dependency_info)
            return json.dumps(d, indent=2)
        return base
    if fmt == "sarif":
        from .sarif import to_sarif_str
        return to_sarif_str(result)
    if fmt == "html":
        from .html_report import generate_html_report
        from .model import Visibility
        old_symbol_count = sum(
            1 for f in old.functions
            if f.visibility in (Visibility.PUBLIC, Visibility.ELF_ONLY)
        ) + sum(
            1 for v in old.variables
            if v.visibility in (Visibility.PUBLIC, Visibility.ELF_ONLY)
        )
        return generate_html_report(
            result,
            lib_name=old.library,
            old_version=old.version,
            new_version=new.version if new else "new",
            old_symbol_count=old_symbol_count or None,
        )
    md = to_markdown(result)
    if follow_deps and (old.dependency_info or (new and new.dependency_info)):
        md += _render_deps_section_md(old, new)
    return md


def _render_deps_section_md(old: AbiSnapshot, new: AbiSnapshot | None) -> str:
    """Append dependency summary section to markdown output."""
    lines: list[str] = ["", "## Dependency Analysis", ""]

    for label, snap in [("Old", old), ("New", new)]:
        if snap is None or snap.dependency_info is None:
            continue
        info = snap.dependency_info
        lines.append(f"### {label} version (`{snap.version}`)")
        lines.append("")

        if info.nodes:
            lines.append(f"**Dependencies**: {len(info.nodes)} resolved DSOs")
            for node in info.nodes:
                raw_depth = node.get("depth", 0)
                depth = raw_depth if isinstance(raw_depth, int) else 0
                indent = "  " * depth
                reason = node.get("resolution_reason", "")
                lines.append(f"  {indent}- `{node.get('soname', '?')}` ({reason})")
            lines.append("")

        if info.bindings_summary:
            lines.append("**Bindings**:")
            for status, count in sorted(info.bindings_summary.items()):
                lines.append(f"  - `{status}`: {count}")
            lines.append("")

        if info.unresolved:
            lines.append("**Unresolved libraries**:")
            for u in info.unresolved:
                lines.append(f"  - `{u.get('soname', '?')}` needed by `{u.get('consumer', '?')}`")
            lines.append("")

        if info.missing_symbols:
            lines.append(f"**Missing symbols**: {len(info.missing_symbols)}")
            for ms in info.missing_symbols[:10]:
                ver = f"@{ms['version']}" if ms.get('version') else ""
                lines.append(f"  - `{ms['symbol']}{ver}`")
            if len(info.missing_symbols) > 10:
                lines.append(f"  - ... +{len(info.missing_symbols) - 10} more")
            lines.append("")

    return "\n".join(lines)


def _collect_additions(result: DiffResult) -> list[object]:
    """Collect additive changes in a policy-independent way."""
    from .checker_policy import COMPATIBLE_KINDS
    addition_kinds = {k for k in COMPATIBLE_KINDS if k.value.endswith("_added")}
    return [c for c in result.changes if c.kind in addition_kinds]


def _run_compare_pair(
    old_input: Path,
    new_input: Path,
    old_headers: list[Path],
    new_headers: list[Path],
    old_includes: list[Path],
    new_includes: list[Path],
    old_version: str,
    new_version: str,
    lang: str,
    suppress: Path | None,
    policy: str,
    policy_file_path: Path | None,
    old_pdb_path: Path | None,
    new_pdb_path: Path | None,
) -> tuple[DiffResult, AbiSnapshot, AbiSnapshot]:
    """Run compare for one old/new pair and return result + resolved snapshots."""
    old_fmt = _detect_binary_format(old_input)
    new_fmt = _detect_binary_format(new_input)

    old = _resolve_input(
        old_input,
        old_headers,
        old_includes,
        old_version,
        lang,
        is_elf=True if old_fmt == "elf" else None,
        pdb_path=old_pdb_path,
    )
    new = _resolve_input(
        new_input,
        new_headers,
        new_includes,
        new_version,
        lang,
        is_elf=True if new_fmt == "elf" else None,
        pdb_path=new_pdb_path,
    )

    suppression, pf = _load_suppression_and_policy(suppress, policy, policy_file_path)
    result = compare(old, new, suppression=suppression, policy=policy, policy_file=pf)
    result.old_metadata = _collect_metadata(old_input)
    result.new_metadata = _collect_metadata(new_input)
    return result, old, new


def _canonical_library_key(path: Path) -> str:
    """Canonical key used to match libraries across releases.

    For ELF versioned names, canonicalize to ``*.so`` (e.g. ``libfoo.so.1.2`` → ``libfoo.so``).
    """
    lower = path.name.lower()
    m = re.search(r"\.so(?:\.|$)", lower)
    if m:
        return lower[: m.start() + 3]
    return lower


def _version_sort_key(path: Path, canonical_key: str) -> tuple[list[tuple[int, int | str]], str]:
    """Build a version-aware sort key for ambiguous library candidates."""
    lower = path.name.lower()
    remainder = lower
    if canonical_key.endswith(".so") and canonical_key in lower:
        remainder = lower[lower.find(canonical_key) + len(canonical_key):]
    # strip known wrapper extensions for snapshots/dumps
    for suffix in (".json", ".pl", ".pm"):
        if remainder.endswith(suffix):
            remainder = remainder[: -len(suffix)]
            break
    remainder = remainder.lstrip("._-")
    tokens = re.findall(r"\d+|[a-z]+", remainder)
    parsed: list[tuple[int, int | str]] = []
    for tok in tokens:
        if tok.isdigit():
            parsed.append((1, int(tok)))
        else:
            parsed.append((0, tok))
    return parsed, lower


def _is_supported_compare_input(path: Path) -> bool:
    """Return True for files accepted by compare/resolve_input."""
    if not path.is_file():
        return False
    lower = path.name.lower()
    if ".so" in lower or lower.endswith((".dll", ".dylib", ".json", ".pl", ".pm")):
        return True
    if _detect_binary_format(path) is not None:
        return True
    return _sniff_text_format(path) in {"json", "perl"}


def _collect_release_inputs(path: Path) -> list[Path]:
    """Collect compare-able inputs from a file or directory."""
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise click.ClickException(f"Input path is neither file nor directory: {path}")
    files = [p for p in sorted(path.rglob("*")) if _is_supported_compare_input(p)]
    if not files:
        raise click.ClickException(f"No supported ABI inputs found in directory: {path}")
    return files


def _build_match_map(paths: list[Path]) -> tuple[dict[str, Path], list[str]]:
    """Build key->path map with version-aware duplicate resolution."""
    buckets: dict[str, list[Path]] = {}
    for p in paths:
        buckets.setdefault(_canonical_library_key(p), []).append(p)

    mapping: dict[str, Path] = {}
    warnings: list[str] = []
    for key, vals in buckets.items():
        ordered = sorted(vals, key=lambda x: _version_sort_key(x, key))
        selected = ordered[-1]
        mapping[key] = selected
        if len(ordered) > 1:
            warnings.append(
                f"Ambiguous match for '{key}': {[v.name for v in ordered]}; using '{selected.name}'"
            )
    return mapping, warnings


@main.command("compare")
@click.argument("old_input", type=click.Path(exists=True, path_type=Path))
@click.argument("new_input", type=click.Path(exists=True, path_type=Path))
# ── Dump options (used when input is an ELF binary) ──────────────────────────
@click.option("-H", "--header", "headers", multiple=True,
              type=click.Path(path_type=Path),
              help="Public header file or directory applied to both sides (repeat for multiple). "
                   "Recommended for full ELF ABI analysis; without headers, ELF falls back to symbols-only mode. "
                   "Validated when input is ELF; ignored for snapshots.")
@click.option("-I", "--include", "includes", multiple=True,
              type=click.Path(path_type=Path),
              help="Extra include directory for castxml (applied to both sides).")
@click.option("--lang", default="c++", show_default=True,
              type=click.Choice(["c++", "c"], case_sensitive=False),
              help="Language mode for castxml.")
@click.option("--old-header", "old_headers_only", multiple=True,
              type=click.Path(path_type=Path),
              help="Public header for old side only (overrides -H for old). "
                   "Validated when input is ELF; ignored for snapshots.")
@click.option("--new-header", "new_headers_only", multiple=True,
              type=click.Path(path_type=Path),
              help="Public header for new side only (overrides -H for new). "
                   "Validated when input is ELF; ignored for snapshots.")
@click.option("--old-include", "old_includes_only", multiple=True,
              type=click.Path(path_type=Path),
              help="Include dir for old side only (overrides -I for old).")
@click.option("--new-include", "new_includes_only", multiple=True,
              type=click.Path(path_type=Path),
              help="Include dir for new side only (overrides -I for new).")
@click.option("--old-version", "old_version", default="old", show_default=True,
              help="Version label for old side (used when input is a .so file).")
@click.option("--new-version", "new_version", default="new", show_default=True,
              help="Version label for new side (used when input is a .so file).")
# ── Compare options (unchanged) ──────────────────────────────────────────────
@click.option("--format", "fmt", type=click.Choice(["json", "markdown", "sarif", "html"]),
              default="markdown", show_default=True)
@click.option("-o", "--output", type=click.Path(path_type=Path), default=None)
@click.option("--suppress", type=click.Path(exists=True, path_type=Path), default=None,
              help="Suppression file (YAML) to filter known/intentional changes.")
@click.option("--policy", "policy",
              type=click.Choice(["strict_abi", "sdk_vendor", "plugin_abi"], case_sensitive=True),
              default="strict_abi", show_default=True,
              help="Built-in policy profile for verdict classification. Ignored when --policy-file is given.")
@click.option("--policy-file", "policy_file_path",
              type=click.Path(exists=True, path_type=Path), default=None,
              help="YAML policy file with per-kind verdict overrides. Overrides --policy.")
@click.option("--pdb-path", "pdb_path", type=click.Path(path_type=Path), default=None,
              help="Explicit PDB file path for Windows PE debug info (applied to both sides). "
                   "Overrides automatic PDB discovery.")
@click.option("--old-pdb-path", "old_pdb_path", type=click.Path(path_type=Path), default=None,
              help="PDB file path for old side only (overrides --pdb-path for old).")
@click.option("--new-pdb-path", "new_pdb_path", type=click.Path(path_type=Path), default=None,
              help="PDB file path for new side only (overrides --pdb-path for new).")
@click.option("--dwarf-only", is_flag=True, default=False,
              help="Force DWARF-only mode for both sides: use DWARF debug info "
                   "as primary data source even when headers are available.")
@click.option("--fail-on-additions/--no-fail-on-additions", "fail_on_additions", default=False,
              help="Exit with code 1 if any new public symbols, types, or fields were added "
                   "(COMPATIBLE changes). Useful for detecting unintentional API expansion in PRs. "
                   "Use --no-fail-on-additions (or omit the flag) to allow API growth.")
@click.option("--follow-deps", is_flag=True, default=False,
              help="Resolve transitive dependencies for both old and new, compute symbol "
                   "bindings, and include a dependency-change section in the report. ELF only.")
@click.option("--search-path", "search_paths", multiple=True,
              type=click.Path(exists=True, path_type=Path),
              help="Additional directory to search for shared libraries (with --follow-deps).")
@click.option("--ld-library-path", "ld_library_path", default="",
              help="Simulated LD_LIBRARY_PATH (with --follow-deps).")
@click.option("-v", "--verbose", is_flag=True, default=False,
              help="Enable verbose/debug output.")
def compare_cmd(
    old_input: Path, new_input: Path,
    headers: tuple[Path, ...], includes: tuple[Path, ...], lang: str,
    old_headers_only: tuple[Path, ...], new_headers_only: tuple[Path, ...],
    old_includes_only: tuple[Path, ...], new_includes_only: tuple[Path, ...],
    old_version: str, new_version: str,
    fmt: str, output: Path | None,
    suppress: Path | None, policy: str, policy_file_path: Path | None,
    pdb_path: Path | None, old_pdb_path: Path | None, new_pdb_path: Path | None,
    dwarf_only: bool,
    fail_on_additions: bool,
    follow_deps: bool, search_paths: tuple[Path, ...], ld_library_path: str,
    verbose: bool,
) -> None:
    """Compare two ABI surfaces and report changes.

    Each input (OLD, NEW) can be a .so shared library, a JSON snapshot from
    'abicheck dump', or an ABICC Perl dump file. The format is auto-detected.

    When a .so file is given, headers (-H) are recommended for full ABI
    extraction. If headers are absent for ELF, abicheck falls back to
    DWARF-only mode (if DWARF available) or symbols-only analysis.

    \b
    Exit codes:
      0  NO_CHANGE, COMPATIBLE, or COMPATIBLE_WITH_RISK — no binary ABI break
         (COMPATIBLE_WITH_RISK: deployment risk present; check the report)
      2  API_BREAK — source-level API break — recompilation required
      4  BREAKING — binary ABI break detected

    \b
    Examples:
      # One-liner: each version has its own header (primary flow)
      abicheck compare libfoo.so.1 libfoo.so.2 \\
        --old-header include/v1/foo.h --new-header include/v2/foo.h

      # Shorthand: -H when the same header applies to both versions
      abicheck compare libfoo.so.1 libfoo.so.2 -H include/foo.h

      # With version labels and SARIF output
      abicheck compare libfoo.so.1 libfoo.so.2 \\
        --old-header v1/foo.h --new-header v2/foo.h \\
        --old-version 1.0 --new-version 2.0 --format sarif -o abi.sarif

      # Compare saved snapshot vs current build (mixed mode)
      abicheck compare baseline.json ./build/libfoo.so --new-header include/foo.h

      # Compare two pre-dumped snapshots (existing workflow)
      abicheck compare libfoo-1.0.json libfoo-2.0.json

      # Policy and suppression
      abicheck compare libfoo.so.1 libfoo.so.2 -H include/foo.h --policy sdk_vendor
      abicheck compare old.json new.json --suppress suppressions.yaml
    """
    _setup_verbosity(verbose)

    old_h, new_h, old_inc, new_inc = _resolve_per_side_options(
        headers, includes, old_headers_only, new_headers_only,
        old_includes_only, new_includes_only,
    )

    old_fmt = _detect_binary_format(old_input)
    new_fmt = _detect_binary_format(new_input)
    _warn_ignored_flags(
        old_fmt is not None, new_fmt is not None,
        headers, includes,
        old_headers_only, new_headers_only,
        old_includes_only, new_includes_only,
    )

    # Resolve per-side PDB paths: --old-pdb-path overrides --pdb-path for old, etc.
    resolved_old_pdb = old_pdb_path if old_pdb_path else pdb_path
    resolved_new_pdb = new_pdb_path if new_pdb_path else pdb_path

    old = _resolve_input(
        old_input, old_h, old_inc, old_version, lang,
        is_elf=True if old_fmt == "elf" else None,
        pdb_path=resolved_old_pdb,
        dwarf_only=dwarf_only,
    )
    new = _resolve_input(
        new_input, new_h, new_inc, new_version, lang,
        is_elf=True if new_fmt == "elf" else None,
        pdb_path=resolved_new_pdb,
        dwarf_only=dwarf_only,
    )

    suppression, pf = _load_suppression_and_policy(suppress, policy, policy_file_path)

    # Populate dependency info if --follow-deps is active and inputs are ELF binaries.
    if follow_deps:
        if old_fmt == "elf":
            _populate_dependency_info(old, old_input, list(search_paths), None, ld_library_path)
        if new_fmt == "elf":
            _populate_dependency_info(new, new_input, list(search_paths), None, ld_library_path)

    result = compare(old, new, suppression=suppression, policy=policy, policy_file=pf)

    # Attach file-level metadata (path, SHA-256, size) for report traceability
    result.old_metadata = _collect_metadata(old_input)
    result.new_metadata = _collect_metadata(new_input)

    # Warn if suppression file swallowed all changes (potential misconfiguration)
    total_changes = len(result.changes) + result.suppressed_count
    if result.suppression_file_provided and total_changes > 0 and len(result.changes) == 0:
        click.echo(
            "Warning: all ABI changes were suppressed by the suppression file. "
            "Verify your suppression rules are not too broad.",
            err=True,
        )

    text = _render_output(fmt, result, old, new, follow_deps=follow_deps)
    if output:
        output.write_text(text, encoding="utf-8")
        click.echo(f"Report written to {output}", err=True)
    else:
        click.echo(text)

    if result.verdict.value == "BREAKING":
        sys.exit(4)
    elif result.verdict.value == "API_BREAK":
        sys.exit(2)

    # --fail-on-additions: exit 1 if any new public symbols/types were added.
    # Filter result.changes directly (not result.compatible) so the check is
    # policy-independent: _ADDITION_KINDS covers all known additive change kinds.
    if fail_on_additions:
        from .checker_policy import COMPATIBLE_KINDS
        _ADDITION_KINDS = {k for k in COMPATIBLE_KINDS if k.value.endswith("_added")}
        additions = [c for c in result.changes if c.kind in _ADDITION_KINDS]
        if additions:
            click.echo(
                f"API expansion detected: {len(additions)} addition(s) "
                f"({', '.join(sorted({c.kind.value for c in additions}))}). "
                "Use --no-fail-on-additions (or omit the flag) to allow API growth.",
                err=True,
            )
            sys.exit(1)

@main.command("compare-release")
@click.argument("old_dir", type=click.Path(exists=True, path_type=Path))
@click.argument("new_dir", type=click.Path(exists=True, path_type=Path))
@click.option("-H", "--header", "headers", multiple=True,
              type=click.Path(path_type=Path),
              help="Public header file or directory applied to both sides.")
@click.option("-I", "--include", "includes", multiple=True,
              type=click.Path(path_type=Path),
              help="Extra include directory for castxml.")
@click.option("--old-header", "old_headers_only", multiple=True,
              type=click.Path(path_type=Path),
              help="Header for old side only (overrides -H for old).")
@click.option("--new-header", "new_headers_only", multiple=True,
              type=click.Path(path_type=Path),
              help="Header for new side only (overrides -H for new).")
@click.option("--old-version", "old_version", default="old", show_default=True,
              help="Version label for old side.")
@click.option("--new-version", "new_version", default="new", show_default=True,
              help="Version label for new side.")
@click.option("--lang", default="c++", show_default=True,
              type=click.Choice(["c++", "c"], case_sensitive=False))
@click.option("--format", "fmt",
              type=click.Choice(["json", "markdown"]),
              default="markdown", show_default=True)
@click.option("-o", "--output", type=click.Path(path_type=Path), default=None,
              help="Output file for summary report (default: stdout).")
@click.option("--output-dir", "output_dir", type=click.Path(path_type=Path), default=None,
              help="Directory to write per-library reports.")
@click.option("--suppress", type=click.Path(exists=True, path_type=Path), default=None,
              help="Suppression file (YAML).")
@click.option("--policy", "policy",
              type=click.Choice(["strict_abi", "sdk_vendor", "plugin_abi"], case_sensitive=True),
              default="strict_abi", show_default=True)
@click.option("--policy-file", "policy_file_path",
              type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--fail-on-removed-library/--no-fail-on-removed-library",
              "fail_on_removed", default=False,
              help="Exit 8 when a library present in old_dir is absent in new_dir.")
@click.option("--fail-on-additions/--no-fail-on-additions",
              "fail_on_additions", default=False)
@click.option("--debug-info1", type=click.Path(exists=True, path_type=Path), default=None,
              help="Debug info package for old side (RPM/Deb/tar).")
@click.option("--debug-info2", type=click.Path(exists=True, path_type=Path), default=None,
              help="Debug info package for new side (RPM/Deb/tar).")
@click.option("--devel-pkg1", type=click.Path(exists=True, path_type=Path), default=None,
              help="Development package with headers for old side.")
@click.option("--devel-pkg2", type=click.Path(exists=True, path_type=Path), default=None,
              help="Development package with headers for new side.")
@click.option("--dso-only", is_flag=True, default=False,
              help="Only compare shared objects, skip executables.")
@click.option("--include-private-dso", is_flag=True, default=False,
              help="Include private (non-public) shared objects from non-standard paths.")
@click.option("--keep-extracted", is_flag=True, default=False,
              help="Keep extracted temporary files for debugging.")
@click.option("-v", "--verbose", is_flag=True, default=False)
def compare_release_cmd(
    old_dir: Path,
    new_dir: Path,
    headers: tuple[Path, ...],
    includes: tuple[Path, ...],
    old_headers_only: tuple[Path, ...],
    new_headers_only: tuple[Path, ...],
    old_version: str,
    new_version: str,
    lang: str,
    fmt: str,
    output: Path | None,
    output_dir: Path | None,
    suppress: Path | None,
    policy: str,
    policy_file_path: Path | None,
    fail_on_removed: bool,
    fail_on_additions: bool,
    debug_info1: Path | None,
    debug_info2: Path | None,
    devel_pkg1: Path | None,
    devel_pkg2: Path | None,
    dso_only: bool,
    include_private_dso: bool,
    keep_extracted: bool,
    verbose: bool,
) -> None:
    """Compare all libraries in two release directories or packages.

    OLD_DIR and NEW_DIR may each be a file, directory, or package
    (RPM, Deb, tar, conda, wheel). Package format is auto-detected.
    When directories are given, libraries are matched by filename stem.

    \b
    Exit codes:
      0  All libraries: NO_CHANGE, COMPATIBLE, or COMPATIBLE_WITH_RISK
      2  At least one library: API_BREAK
      4  At least one library: BREAKING
      8  Library removed (only when --fail-on-removed-library)

    \b
    Examples:
      abicheck compare-release release-1.0/ release-2.0/ -H include/
      abicheck compare-release libfoo-1.0.rpm libfoo-1.1.rpm
      abicheck compare-release libfoo_1.0.deb libfoo_1.1.deb
      abicheck compare-release sdk-2.0.tar.gz sdk-2.1.tar.gz
      abicheck compare-release pkg-v1.conda pkg-v2.conda
      abicheck compare-release old.whl new.whl
      abicheck compare-release libfoo-1.0.rpm libfoo-1.1.rpm \\
          --debug-info1 libfoo-debuginfo-1.0.rpm \\
          --debug-info2 libfoo-debuginfo-1.1.rpm
    """
    import tempfile

    from .package import (
        _is_elf_shared_object,
        detect_extractor,
        discover_shared_libraries,
        is_package,
        resolve_debug_info,
    )

    _setup_verbosity(verbose)

    # Track temporary directory paths for cleanup
    _temp_dir_paths: list[str] = []

    def _make_temp_dir(prefix: str) -> Path:
        """Create a temporary directory, tracking it for later cleanup."""
        path = tempfile.mkdtemp(prefix=prefix)
        _temp_dir_paths.append(path)
        return Path(path)

    def _extract_if_package(
        input_path: Path,
        debug_pkg: Path | None,
        devel_pkg: Path | None,
    ) -> tuple[Path, Path | None, Path | None]:
        """Extract package to tempdir if needed, return (lib_dir, debug_dir, header_dir)."""
        if not is_package(input_path):
            return input_path, None, None

        extractor = detect_extractor(input_path)
        if extractor is None:
            raise click.ClickException(f"Unrecognized package format: {input_path}")

        target = _make_temp_dir("abicheck_pkg_")

        result = extractor.extract(input_path, target)
        lib_dir = result.lib_dir
        debug_dir = result.debug_dir
        header_dir = result.header_dir

        # Extract debug info package if provided
        if debug_pkg is not None:
            dbg_ext = detect_extractor(debug_pkg)
            if dbg_ext is None:
                raise click.ClickException(f"Unrecognized debug package format: {debug_pkg}")
            dbg_target = _make_temp_dir("abicheck_dbg_")
            dbg_result = dbg_ext.extract(debug_pkg, dbg_target)
            debug_dir = dbg_result.lib_dir

        # Extract devel package if provided
        if devel_pkg is not None:
            dev_ext = detect_extractor(devel_pkg)
            if dev_ext is None:
                raise click.ClickException(f"Unrecognized devel package format: {devel_pkg}")
            dev_target = _make_temp_dir("abicheck_dev_")
            dev_result = dev_ext.extract(devel_pkg, dev_target)
            header_dir = dev_result.lib_dir

        return lib_dir, debug_dir, header_dir

    try:
        old_lib_dir, old_debug_dir, old_header_dir = _extract_if_package(
            old_dir, debug_info1, devel_pkg1,
        )
        new_lib_dir, new_debug_dir, new_header_dir = _extract_if_package(
            new_dir, debug_info2, devel_pkg2,
        )

        # When packages were extracted, first try binary discovery (ELF DSOs),
        # then fall back to _collect_release_inputs (catches JSON snapshots too).
        if is_package(old_dir):
            old_files = discover_shared_libraries(old_lib_dir, include_private=include_private_dso)
            if not old_files:
                old_files = _collect_release_inputs(old_lib_dir)
        else:
            old_files = _collect_release_inputs(old_lib_dir)

        if is_package(new_dir):
            new_files = discover_shared_libraries(new_lib_dir, include_private=include_private_dso)
            if not new_files:
                new_files = _collect_release_inputs(new_lib_dir)
        else:
            new_files = _collect_release_inputs(new_lib_dir)

        # --dso-only: keep only ELF shared objects (ET_DYN), skip executables
        if dso_only:
            old_files = [f for f in old_files if _is_elf_shared_object(f)]
            new_files = [f for f in new_files if _is_elf_shared_object(f)]

        old_map, old_warns = _build_match_map(old_files)
        new_map, new_warns = _build_match_map(new_files)
        warning_msgs: list[str] = [f"Warning: {w}" for w in (old_warns + new_warns)]

        # Use headers from devel packages if extracted, otherwise use CLI flags
        old_h: list[Path] = list(old_headers_only) if old_headers_only else list(headers)
        new_h: list[Path] = list(new_headers_only) if new_headers_only else list(headers)
        if old_header_dir and not old_headers_only:
            old_h = [old_header_dir]
        if new_header_dir and not new_headers_only:
            new_h = [new_header_dir]
        old_inc: list[Path] = list(includes)
        new_inc: list[Path] = list(includes)

        # Special case: file-vs-file should compare directly even when names differ.
        # (Does not apply to package inputs — those are always discovered.)
        direct_file_pair = (
            old_dir.is_file() and new_dir.is_file()
            and not is_package(old_dir) and not is_package(new_dir)
        )
        if direct_file_pair:
            matched_keys = ["__direct_pair__"]
            old_map = {"__direct_pair__": old_files[0]}
            new_map = {"__direct_pair__": new_files[0]}
            removed_keys: list[str] = []
            added_keys: list[str] = []
        else:
            matched_keys = sorted(set(old_map) & set(new_map))
            removed_keys = sorted(set(old_map) - set(new_map))
            added_keys = sorted(set(new_map) - set(old_map))

        if removed_keys:
            for k in removed_keys:
                warning_msgs.append(f"Warning: library removed: {old_map[k].name}")

        if added_keys:
            for k in added_keys:
                warning_msgs.append(f"Info: library added: {new_map[k].name}")

        if not matched_keys:
            warning_msgs.append(
                "Warning: no matching library pairs found between OLD and NEW inputs."
            )

        if fmt != "json":
            for msg in warning_msgs:
                click.echo(msg, err=True)

        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)

        library_results: list[dict[str, object]] = []
        worst_verdict = "NO_CHANGE"
        _VERDICT_ORDER = {
            "NO_CHANGE": 0,
            "COMPATIBLE": 1,
            "COMPATIBLE_WITH_RISK": 2,
            "API_BREAK": 3,
            "BREAKING": 4,
            "ERROR": 5,
        }

        for key in matched_keys:
            old_path = old_map[key]
            new_path = new_map[key]
            # Resolve per-binary debug info from extracted debug packages
            old_dbg = (
                resolve_debug_info(old_path, old_debug_dir)
                if old_debug_dir else None
            )
            new_dbg = (
                resolve_debug_info(new_path, new_debug_dir)
                if new_debug_dir else None
            )
            try:
                result, _, _ = _run_compare_pair(
                    old_path, new_path,
                    old_h, new_h, old_inc, new_inc,
                    old_version, new_version,
                    lang, suppress, policy, policy_file_path,
                    old_pdb_path=old_dbg, new_pdb_path=new_dbg,
                )
            except (click.ClickException, click.UsageError) as exc:
                msg = exc.format_message()
                click.echo(f"Error comparing {old_path.name}: {msg}", err=True)
                library_results.append({
                    "library": old_path.name,
                    "verdict": "ERROR",
                    "error": msg,
                })
                worst_verdict = "ERROR"
                continue

            v = result.verdict.value
            if _VERDICT_ORDER.get(v, 0) > _VERDICT_ORDER.get(worst_verdict, 0):
                worst_verdict = v

            lib_entry: dict[str, object] = {
                "library": old_path.name,
                "verdict": v,
                "breaking": len(result.breaking),
                "source_breaks": len(result.source_breaks),
                "risk_changes": len(result.risk),
                "compatible_additions": len(result.compatible),
            }
            library_results.append(lib_entry)

            if output_dir:
                lib_report_path = output_dir / f"{old_path.stem}.json"
                lib_report_path.write_text(to_json(result), encoding="utf-8")

        # Summary output
        if fmt == "json":
            summary: dict[str, object] = {
                "verdict": worst_verdict,
                "old_dir": str(old_dir),
                "new_dir": str(new_dir),
                "libraries": library_results,
                "unmatched_old": [old_map[k].name for k in removed_keys],
                "unmatched_new": [new_map[k].name for k in added_keys],
                "warnings": warning_msgs,
            }
            text = json.dumps(summary, indent=2)
        else:
            _VERDICT_EMOJI = {
                "NO_CHANGE": "✅", "COMPATIBLE": "✅", "COMPATIBLE_WITH_RISK": "⚠️",
                "API_BREAK": "⚠️", "BREAKING": "❌", "ERROR": "💥",
            }
            lines: list[str] = [
                "# ABI Release Comparison",
                "",
                "| | |",
                "|---|---|",
                f"| **Old** | `{old_dir}` |",
                f"| **New** | `{new_dir}` |",
                f"| **Verdict** | {_VERDICT_EMOJI.get(worst_verdict, '?')} `{worst_verdict}` |",
                "",
                "## Libraries",
                "",
                "| Library | Verdict | Breaking | Source | Risk | Additions |",
                "|---|---|---|---|---|---|",
            ]
            for lib in library_results:
                em = _VERDICT_EMOJI.get(str(lib["verdict"]), "?")
                lines.append(
                    f"| `{lib['library']}` | {em} `{lib['verdict']}` "
                    f"| {lib.get('breaking', '—')} | {lib.get('source_breaks', '—')} "
                    f"| {lib.get('risk_changes', '—')} | {lib.get('compatible_additions', '—')} |"
                )
            if removed_keys:
                lines += ["", "## ⚠️ Removed Libraries", ""]
                for k in removed_keys:
                    lines.append(f"- `{old_map[k].name}`")
            if added_keys:
                lines += ["", "## ℹ️ Added Libraries", ""]
                for k in added_keys:
                    lines.append(f"- `{new_map[k].name}`")
            text = "\n".join(lines)

        if output:
            output.write_text(text, encoding="utf-8")
            click.echo(f"Report written to {output}", err=True)
        else:
            click.echo(text)

        if output_dir:
            summary_path = output_dir / "summary.json"
            summary_data: dict[str, object] = {
                "verdict": worst_verdict,
                "libraries": library_results,
                "unmatched_old": [old_map[k].name for k in removed_keys],
                "unmatched_new": [new_map[k].name for k in added_keys],
            }
            summary_path.write_text(json.dumps(summary_data, indent=2), encoding="utf-8")
            click.echo(f"Per-library reports written to {output_dir}/", err=True)

        # Exit codes — ABI severity takes priority over policy flags.
        # A removed library is a deployment decision; a binary ABI break is more urgent.
        if worst_verdict in ("BREAKING", "ERROR"):
            sys.exit(4)
        elif worst_verdict == "API_BREAK":
            sys.exit(2)
        if fail_on_removed and removed_keys:
            sys.exit(8)
        if fail_on_additions and any(lib.get("compatible_additions", 0) for lib in library_results):
            sys.exit(1)
    finally:
        import shutil as _shutil
        if not keep_extracted:
            for td_path in _temp_dir_paths:
                _shutil.rmtree(td_path, ignore_errors=True)
        elif _temp_dir_paths:
            kept_paths = ", ".join(_temp_dir_paths)
            click.echo(
                f"Extracted files kept in: {kept_paths}",
                err=True,
            )


# ── Full-stack dependency commands ────────────────────────────────────────────

@main.command("deps")
@click.argument("binary", type=click.Path(exists=True, path_type=Path))
@click.option("--search-path", "search_paths", multiple=True,
              type=click.Path(exists=True, path_type=Path),
              help="Additional directory to search for shared libraries.")
@click.option("--sysroot", type=click.Path(exists=True, path_type=Path), default=None,
              help="Sysroot prefix for cross/container analysis.")
@click.option("--ld-library-path", "ld_library_path", default="",
              help="Simulated LD_LIBRARY_PATH (colon-separated).")
@click.option("--format", "fmt", type=click.Choice(["json", "markdown"]),
              default="markdown", show_default=True)
@click.option("-o", "--output", type=click.Path(path_type=Path), default=None)
@click.option("-v", "--verbose", is_flag=True, default=False)
def deps_cmd(
    binary: Path, search_paths: tuple[Path, ...],
    sysroot: Path | None, ld_library_path: str,
    fmt: str, output: Path | None, verbose: bool,
) -> None:
    """Show the resolved dependency tree and symbol binding status.

    Resolves the transitive closure of DT_NEEDED dependencies for BINARY
    using loader-accurate search order (RPATH/RUNPATH, LD_LIBRARY_PATH,
    default dirs) and reports symbol binding status.

    \b
    Exit codes:
      0  All dependencies resolved, all required symbols bound
      1  Missing dependencies or symbols (load would fail)

    \b
    Examples:
      abicheck deps ./build/libfoo.so
      abicheck deps /usr/bin/myapp --format json -o deps.json
      abicheck deps ./app --sysroot /path/to/container/rootfs
    """
    _setup_verbosity(verbose)

    from .stack_checker import check_single_env
    from .stack_report import stack_to_json, stack_to_markdown

    result = check_single_env(
        binary,
        search_paths=list(search_paths) or None,
        sysroot=sysroot,
        ld_library_path=ld_library_path,
    )

    text = stack_to_json(result) if fmt == "json" else stack_to_markdown(result)
    if output:
        output.write_text(text, encoding="utf-8")
        click.echo(f"Report written to {output}", err=True)
    else:
        click.echo(text)

    if result.loadability.value == "fail":
        sys.exit(1)


@main.command("stack-check")
@click.argument("binary", type=click.Path(path_type=Path))
@click.option("--baseline", type=click.Path(exists=True, path_type=Path), required=True,
              help="Sysroot for the baseline environment.")
@click.option("--candidate", type=click.Path(exists=True, path_type=Path), required=True,
              help="Sysroot for the candidate environment.")
@click.option("--search-path", "search_paths", multiple=True,
              type=click.Path(exists=True, path_type=Path),
              help="Additional directory to search for shared libraries.")
@click.option("--ld-library-path", "ld_library_path", default="",
              help="Simulated LD_LIBRARY_PATH (colon-separated).")
@click.option("--format", "fmt", type=click.Choice(["json", "markdown"]),
              default="markdown", show_default=True)
@click.option("-o", "--output", type=click.Path(path_type=Path), default=None)
@click.option("-v", "--verbose", is_flag=True, default=False)
def stack_check_cmd(
    binary: Path, baseline: Path, candidate: Path,
    search_paths: tuple[Path, ...], ld_library_path: str,
    fmt: str, output: Path | None, verbose: bool,
) -> None:
    """Compare a binary's full dependency stack across two environments.

    Resolves all transitive dependencies in both BASELINE and CANDIDATE sysroots,
    computes symbol bindings, detects changed DSOs, runs per-library ABI diffs,
    and produces a stack-level compatibility verdict.

    BINARY is the path relative to the sysroot (e.g. usr/bin/myapp).

    \b
    Exit codes:
      0  PASS — binary loads and no harmful ABI changes
      1  WARN — loads but ABI risk detected
      4  FAIL — load failure or binary ABI break

    \b
    Examples:
      abicheck stack-check usr/bin/myapp --baseline /old-root --candidate /new-root
      abicheck stack-check usr/lib/libfoo.so.1 \\
        --baseline ./image-v1 --candidate ./image-v2 --format json
    """
    _setup_verbosity(verbose)

    from .stack_checker import check_stack
    from .stack_report import stack_to_json, stack_to_markdown

    result = check_stack(
        binary,
        baseline_root=baseline,
        candidate_root=candidate,
        ld_library_path=ld_library_path,
        search_paths=list(search_paths) or None,
    )

    text = stack_to_json(result) if fmt == "json" else stack_to_markdown(result)
    if output:
        output.write_text(text, encoding="utf-8")
        click.echo(f"Report written to {output}", err=True)
    else:
        click.echo(text)

    if result.loadability.value == "fail" or result.abi_risk.value == "fail":
        sys.exit(4)
    elif result.abi_risk.value == "warn" or result.loadability.value == "warn":
        sys.exit(1)


# ── ABICC compat subcommands (implementation in abicheck.compat) ─────────────
# NOTE: eagerly loads abicheck.compat.cli at import time — intentional so all
# consumers get compat commands registered. Private helpers re-exported for
# backward compatibility with code importing from abicheck.cli directly.
from .compat.cli import (  # noqa: E402,F401
    _API_BREAK_KINDS,
    _BINARY_ONLY_KINDS,
    _NEW_SYMBOL_KINDS,
    _P2_STUB_FLAGS,
    _apply_strict,
    _apply_warn_newsym,
    _build_internal_suppression,
    _build_skip_suppression,
    _build_whitelist_suppression,
    _classify_compat_error_exit_code,
    _compat_fail,
    _detect_compiler_version,
    _do_echo,
    _filter_binary_only,
    _filter_source_only,
    _limit_affected_changes,
    _load_descriptor_or_dump,
    _load_skip_headers,
    _merge_suppression,
    _resolve_headers_from_list,
    _safe_path,
    _setup_logging,
    _warn_stub_flags,
    _write_affected_list,
)

# fmt: on

main.add_command(compat_group)


if __name__ == "__main__":
    main()
