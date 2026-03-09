"""CLI — abicheck dump | compare | scan | compat."""
from __future__ import annotations

import re as _re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import click

from .checker import ChangeKind, compare
from .compat import parse_descriptor
from .dumper import dump
from .html_report import write_html_report
from .reporter import to_json, to_markdown
from .serialization import load_snapshot, save_snapshot, snapshot_to_json

if TYPE_CHECKING:
    from .checker import DiffResult
    from .suppression import SuppressionList


@click.group()
def main() -> None:
    """abicheck — ABI compatibility checker for C/C++ shared libraries."""


@main.command("dump")
@click.argument("so_path", type=click.Path(exists=True, path_type=Path))
@click.option("-H", "--header", "headers", multiple=True, type=click.Path(exists=True, path_type=Path),
              help="Public header file (repeat for multiple).")
@click.option("-I", "--include", "includes", multiple=True, type=click.Path(path_type=Path),
              help="Extra include directory for castxml.")
@click.option("--version", "version", default="unknown", show_default=True,
              help="Library version string to embed in snapshot.")
@click.option("--compiler", default="c++", show_default=True,
              help="Compiler frontend for castxml (c++ or cc).")
@click.option("-o", "--output", "output", type=click.Path(path_type=Path), default=None,
              help="Output JSON file. Defaults to stdout.")
def dump_cmd(so_path: Path, headers: tuple[Path, ...], includes: tuple[Path, ...],
             version: str, compiler: str, output: Path | None) -> None:
    """Dump ABI snapshot of a shared library to JSON.

    \b
    Example:
      abicheck dump libfoo.so.1 -H include/foo.h --version 1.2.3 -o snap.json
    """
    snap = dump(
        so_path=so_path,
        headers=list(headers),
        extra_includes=list(includes),
        version=version,
        compiler=compiler,
    )
    result = snapshot_to_json(snap)
    if output:
        output.write_text(result, encoding="utf-8")
        click.echo(f"Snapshot written to {output}", err=True)
    else:
        click.echo(result)


@main.command("compare")
@click.argument("old_snapshot", type=click.Path(exists=True, path_type=Path))
@click.argument("new_snapshot", type=click.Path(exists=True, path_type=Path))
@click.option("--format", "fmt", type=click.Choice(["json", "markdown", "sarif", "html"]),
              default="markdown", show_default=True)
@click.option("-o", "--output", type=click.Path(path_type=Path), default=None)
@click.option("--suppress", type=click.Path(exists=True, path_type=Path), default=None,
              help="Suppression file (YAML) to filter known/intentional changes.")
def compare_cmd(old_snapshot: Path, new_snapshot: Path, fmt: str, output: Path | None,
                suppress: Path | None) -> None:
    """Compare two ABI snapshots and report changes.

    \b
    Example:
      abicheck compare libfoo-1.0.json libfoo-2.0.json --format markdown
      abicheck compare libfoo-1.0.json libfoo-2.0.json --format sarif -o results.sarif
      abicheck compare libfoo-1.0.json libfoo-2.0.json --format html -o report.html
      abicheck compare libfoo-1.0.json libfoo-2.0.json --suppress suppressions.yaml
    """
    from .suppression import SuppressionList

    old = load_snapshot(old_snapshot)
    new = load_snapshot(new_snapshot)

    suppression: SuppressionList | None = None
    if suppress is not None:
        try:
            suppression = SuppressionList.load(suppress)
        except (ValueError, OSError) as e:
            raise click.BadParameter(str(e), param_hint="--suppress") from e

    result = compare(old, new, suppression=suppression)

    # Warn if suppression file swallowed all changes (potential misconfiguration)
    total_changes = len(result.changes) + result.suppressed_count
    if result.suppression_file_provided and total_changes > 0 and len(result.changes) == 0:
        click.echo(
            "⚠️  Warning: all ABI changes were suppressed by the suppression file. "
            "Verify your suppression rules are not too broad.",
            err=True,
        )

    if fmt == "json":
        text = to_json(result)
    elif fmt == "sarif":
        from .sarif import to_sarif_str
        text = to_sarif_str(result)
    elif fmt == "html":
        from .html_report import generate_html_report
        from .model import Visibility
        old_symbol_count = sum(
            1 for f in old.functions
            if f.visibility in (Visibility.PUBLIC, Visibility.ELF_ONLY)
        ) + sum(
            1 for v in old.variables
            if v.visibility in (Visibility.PUBLIC, Visibility.ELF_ONLY)
        )
        text = generate_html_report(
            result,
            lib_name=old.library,
            old_version=old.version,
            new_version=new.version,
            old_symbol_count=old_symbol_count or None,
        )
    else:
        text = to_markdown(result)

    if output:
        output.write_text(text, encoding="utf-8")
        click.echo(f"Report written to {output}", err=True)
    else:
        click.echo(text)

    if result.verdict.value == "BREAKING":
        sys.exit(4)
    elif result.verdict.value == "SOURCE_BREAK":
        sys.exit(2)


# ── ABICC compat helpers ──────────────────────────────────────────────────────

def _build_skip_suppression(
    skip_symbols_path: Path | None,
    skip_types_path: Path | None,
) -> SuppressionList:
    """Build a SuppressionList from ABICC-style -skip-symbols / -skip-types files.

    Both symbol and type names are stored as symbol-match suppressions — abicheck
    uses the type name as the symbol field for type-level changes (e.g. TYPE_REMOVED).

    Raises ValueError if a file contains an invalid regex pattern.
    Raises OSError if a file cannot be read.
    """
    from .suppression import Suppression, SuppressionList  # noqa: PLC0415

    rules: list[Suppression] = []
    for label, fpath in [("symbols", skip_symbols_path), ("types", skip_types_path)]:
        if fpath is None:
            continue
        names = [
            ln.strip() for ln in fpath.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")
        ]
        for name in names:
            # Suppression.__post_init__ validates regex — ValueError propagates to caller
            if any(c in name for c in ("*", "?", ".", "[")):
                rules.append(Suppression(symbol_pattern=name))
            else:
                rules.append(Suppression(symbol=name))
    return SuppressionList(suppressions=rules)


def _build_whitelist_suppression(
    symbols_list_path: Path | None,
    types_list_path: Path | None,
) -> SuppressionList:
    """Build a SuppressionList that suppresses everything NOT in the whitelist.

    Inverts the whitelist into a regex-based suppression: any symbol/type not
    matching one of the whitelist entries is suppressed.

    This is the inverse of -skip-symbols / -skip-types.
    """
    from .suppression import Suppression, SuppressionList  # noqa: PLC0415

    rules: list[Suppression] = []
    for label, fpath in [("symbols", symbols_list_path), ("types", types_list_path)]:
        if fpath is None:
            continue
        names = [
            ln.strip() for ln in fpath.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")
        ]
        if not names:
            continue
        # Build a single regex that matches only whitelisted names.
        # Everything NOT matching this pattern will be suppressed.
        # We escape each name and join with |, then negate via a
        # negative-lookahead anchored pattern.
        escaped = [_re.escape(n) for n in names]
        # Pattern matches anything that is NOT one of the whitelisted names
        negate_pattern = f"(?!({'|'.join(escaped)})$).*"
        rules.append(Suppression(symbol_pattern=negate_pattern))
    return SuppressionList(suppressions=rules)


def _build_internal_suppression(
    skip_internal_symbols: str | None,
    skip_internal_types: str | None,
) -> SuppressionList:
    """Build a SuppressionList from -skip-internal-symbols / -skip-internal-types regex patterns."""
    from .suppression import Suppression, SuppressionList  # noqa: PLC0415

    rules: list[Suppression] = []
    if skip_internal_symbols is not None:
        rules.append(Suppression(symbol_pattern=skip_internal_symbols))
    if skip_internal_types is not None:
        rules.append(Suppression(symbol_pattern=skip_internal_types))
    return SuppressionList(suppressions=rules)


# SOURCE_BREAK-only ChangeKinds (source API breaks, not binary ABI breaks)
_SOURCE_BREAK_KINDS: frozenset[ChangeKind] = frozenset({
    ChangeKind.FUNC_PARAMS_CHANGED,
    ChangeKind.FUNC_RETURN_CHANGED,
    ChangeKind.FUNC_NOEXCEPT_ADDED,
    ChangeKind.FUNC_NOEXCEPT_REMOVED,
    ChangeKind.FUNC_DELETED,           # Sprint 2
    ChangeKind.TYPE_FIELD_REMOVED,
    ChangeKind.TYPE_FIELD_TYPE_CHANGED,
    ChangeKind.TYPE_REMOVED,
    ChangeKind.TYPE_BECAME_OPAQUE,     # Sprint 2
    ChangeKind.TYPEDEF_REMOVED,
    ChangeKind.TYPEDEF_BASE_CHANGED,
    ChangeKind.ENUM_MEMBER_REMOVED,
    ChangeKind.ENUM_MEMBER_VALUE_CHANGED,
    ChangeKind.ENUM_MEMBER_ADDED,
})

# ELF/binary-only ChangeKinds (excluded in -source mode)
_BINARY_ONLY_KINDS: frozenset[ChangeKind] = frozenset({
    ChangeKind.SONAME_CHANGED,
    ChangeKind.NEEDED_ADDED,
    ChangeKind.NEEDED_REMOVED,
    ChangeKind.RPATH_CHANGED,
    ChangeKind.RUNPATH_CHANGED,
    ChangeKind.SYMBOL_BINDING_CHANGED,
    ChangeKind.SYMBOL_BINDING_STRENGTHENED,
    ChangeKind.SYMBOL_TYPE_CHANGED,
    ChangeKind.SYMBOL_SIZE_CHANGED,
    ChangeKind.IFUNC_INTRODUCED,
    ChangeKind.IFUNC_REMOVED,
    ChangeKind.COMMON_SYMBOL_RISK,
    ChangeKind.SYMBOL_VERSION_DEFINED_REMOVED,
    ChangeKind.SYMBOL_VERSION_REQUIRED_ADDED,
    ChangeKind.SYMBOL_VERSION_REQUIRED_REMOVED,
    ChangeKind.DWARF_INFO_MISSING,
    ChangeKind.TOOLCHAIN_FLAG_DRIFT,
})

# ChangeKinds that represent new symbols being added (for -warn-newsym)
_NEW_SYMBOL_KINDS: frozenset[ChangeKind] = frozenset({
    ChangeKind.FUNC_ADDED,
    ChangeKind.VAR_ADDED,
})


def _apply_strict(result: DiffResult) -> DiffResult:
    """Apply strict-mode verdict promotion: COMPATIBLE/SOURCE_BREAK → BREAKING."""
    from .checker import DiffResult, Verdict  # noqa: PLC0415

    if result.verdict.value in ("COMPATIBLE", "SOURCE_BREAK"):
        return DiffResult(
            old_version=result.old_version,
            new_version=result.new_version,
            library=result.library,
            changes=result.changes,
            verdict=Verdict.BREAKING,
            suppressed_count=result.suppressed_count,
            suppressed_changes=result.suppressed_changes,
            suppression_file_provided=result.suppression_file_provided,
        )
    return result


def _filter_source_only(result: DiffResult) -> DiffResult:
    """Remove binary-only changes from result for -source mode."""
    from .checker import (  # noqa: PLC0415
        _BREAKING_KINDS,
        _COMPATIBLE_KINDS,
        DiffResult,
        Verdict,
    )
    from .checker import (
        _SOURCE_BREAK_KINDS as _SBK,
    )

    filtered = [c for c in result.changes if c.kind not in _BINARY_ONLY_KINDS]

    if any(c.kind in _BREAKING_KINDS for c in filtered):
        verdict = Verdict.BREAKING
    elif any(c.kind in _SBK for c in filtered):
        verdict = Verdict.SOURCE_BREAK
    elif any(c.kind in _COMPATIBLE_KINDS for c in filtered):
        verdict = Verdict.COMPATIBLE
    else:
        verdict = Verdict.NO_CHANGE

    return DiffResult(
        old_version=result.old_version,
        new_version=result.new_version,
        library=result.library,
        changes=filtered,
        verdict=verdict,
        suppressed_count=result.suppressed_count,
        suppressed_changes=result.suppressed_changes,
        suppression_file_provided=result.suppression_file_provided,
    )


def _apply_warn_newsym(result: DiffResult) -> DiffResult:
    """Promote new-symbol additions to BREAKING when -warn-newsym is set."""
    from .checker import DiffResult, Verdict  # noqa: PLC0415

    has_new = any(c.kind in _NEW_SYMBOL_KINDS for c in result.changes)
    if has_new and result.verdict.value in ("COMPATIBLE", "NO_CHANGE"):
        return DiffResult(
            old_version=result.old_version,
            new_version=result.new_version,
            library=result.library,
            changes=result.changes,
            verdict=Verdict.BREAKING,
            suppressed_count=result.suppressed_count,
            suppressed_changes=result.suppressed_changes,
            suppression_file_provided=result.suppression_file_provided,
        )
    return result


def _limit_affected_changes(result: DiffResult, limit: int) -> DiffResult:
    """Limit the number of reported changes per unique ChangeKind."""
    from .checker import DiffResult  # noqa: PLC0415

    if limit <= 0:
        return result

    counts: dict[ChangeKind, int] = {}
    filtered: list = []
    for c in result.changes:
        cnt = counts.get(c.kind, 0)
        if cnt < limit:
            filtered.append(c)
        counts[c.kind] = cnt + 1

    return DiffResult(
        old_version=result.old_version,
        new_version=result.new_version,
        library=result.library,
        changes=filtered,
        verdict=result.verdict,
        suppressed_count=result.suppressed_count,
        suppressed_changes=result.suppressed_changes,
        suppression_file_provided=result.suppression_file_provided,
    )


def _write_affected_list(result: DiffResult, output_path: Path) -> None:
    """Write a newline-separated file of affected symbols."""
    symbols = sorted({c.symbol for c in result.changes if c.symbol})
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(symbols) + "\n" if symbols else "", encoding="utf-8")


def _safe_path(v: str) -> str:
    return _re.sub(r"[^\w.\-]", "_", v)


def _merge_suppression(base: SuppressionList | None, extra: SuppressionList) -> SuppressionList:
    """Merge two suppression lists, handling None base."""
    from .suppression import SuppressionList as SL  # noqa: PLC0415
    if base is not None:
        return SL.merge(base, extra)
    return extra


def _do_echo(msg: str, quiet: bool, *, err: bool = True) -> None:
    """Echo a message unless quiet mode is active."""
    if not quiet:
        click.echo(msg, err=err)


# ── compat dump subcommand ────────────────────────────────────────────────────

@main.command("compat-dump")
@click.option("-lib", "-l", "-library", "lib_name", required=True, help="Library name.")
@click.option("-dump", "desc_path", required=True, type=click.Path(exists=True, path_type=Path),
              help="Path to ABICC XML descriptor to dump.")
@click.option("-dump-path", "dump_path", default=None, type=click.Path(path_type=Path),
              help="Output dump file path. Default: abi_dumps/<lib>/<version>/dump.json.")
@click.option("-vnum", "vnum", default=None, help="Override version label.")
@click.option("-q", "-quiet", "quiet", is_flag=True, default=False, help="Suppress console output.")
def compat_dump_cmd(
    lib_name: str,
    desc_path: Path,
    dump_path: Path | None,
    vnum: str | None,
    quiet: bool,
) -> None:
    """Create an ABI dump from an ABICC XML descriptor (ABICC -dump equivalent).

    Produces a JSON ABI snapshot that can be used with ``abicheck compat`` or
    ``abicheck compare`` for later comparison. This enables two-stage CI workflows:
    dump once, compare later.

    \b
    Examples::
        # Create dump from descriptor:
        abicheck compat-dump -lib libfoo -dump v1.xml

        # With explicit output path:
        abicheck compat-dump -lib libfoo -dump v1.xml -dump-path libfoo-v1.json

        # Override version label:
        abicheck compat-dump -lib libfoo -dump v1.xml -vnum 2025.1
    """
    try:
        desc = parse_descriptor(desc_path)
    except (ValueError, FileNotFoundError, OSError) as exc:
        click.echo(f"Error parsing descriptor: {exc}", err=True)
        sys.exit(2)

    if vnum:
        desc = desc.__class__(
            version=vnum, headers=desc.headers, libs=desc.libs, path=desc.path
        )

    so_path = desc.libs[0]
    if len(desc.libs) > 1:
        _do_echo(
            f"Warning: descriptor has {len(desc.libs)} <libs> entries; using first: {so_path}",
            quiet,
        )

    if not so_path.exists():
        click.echo(f"Error: library not found: {so_path}", err=True)
        sys.exit(2)

    try:
        snap = dump(so_path, headers=desc.headers, version=desc.version)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"Error during dump: {exc}", err=True)
        sys.exit(2)

    # Override library name to match -lib flag
    snap = snap.__class__(
        library=lib_name,
        version=snap.version,
        functions=snap.functions,
        variables=snap.variables,
        types=snap.types,
        elf=snap.elf,
        dwarf=snap.dwarf,
        dwarf_advanced=snap.dwarf_advanced,
        enums=snap.enums,
        typedefs=snap.typedefs,
    )

    if dump_path is None:
        dump_path = (
            Path("abi_dumps")
            / _safe_path(lib_name)
            / _safe_path(desc.version)
            / "dump.json"
        )

    dump_path.parent.mkdir(parents=True, exist_ok=True)
    save_snapshot(snap, dump_path)
    _do_echo(f"ABI dump written to {dump_path}", quiet)


# ── compat compare subcommand ─────────────────────────────────────────────────

@main.command("compat")
@click.option("-lib", "-l", "-library", "lib_name", required=True, help="Library name (e.g. libdnnl).")
@click.option("-old", "-d1", "old_desc", required=True, type=click.Path(exists=True, path_type=Path),
              help="Path to old version ABICC XML descriptor or ABI dump.")
@click.option("-new", "-d2", "new_desc", required=True, type=click.Path(exists=True, path_type=Path),
              help="Path to new version ABICC XML descriptor or ABI dump.")
@click.option("-report-path", "report_path", default=None, type=click.Path(path_type=Path),
              help="Output report path. Default: compat_reports/<lib>/<old>_to_<new>/report.<fmt>.")
@click.option("-report-format", "fmt", default="html",
              type=click.Choice(["html", "json", "md"], case_sensitive=False),
              help="Report format (default: html).")
@click.option("--suppress", default=None, type=click.Path(path_type=Path),
              help="Suppression YAML file (passed through to compare).")
# ── ABICC strict-compat flags ─────────────────────────────────────────────────
@click.option("-s", "-strict", "strict", is_flag=True, default=False,
              help="Strict mode: any incompatible change is an error (exit 1).")
@click.option("-show-retval", "show_retval", is_flag=True, default=False,
              help="Show return-value changes in report.")
@click.option("-headers-only", "headers_only", is_flag=True, default=False,
              help="[Not yet implemented] Header-only analysis mode.")
@click.option("-source", "-src", "-api", "source_only", is_flag=True, default=False,
              help="Check source (API) compatibility only, not binary ABI.")
@click.option("-binary", "-bin", "-abi", "binary_only", is_flag=True, default=False,
              help="Check binary (ABI) compatibility only (default behavior).")
@click.option("-v1", "-vnum1", "vnum1", default=None,
              help="Override version label for old library.")
@click.option("-v2", "-vnum2", "vnum2", default=None,
              help="Override version label for new library.")
@click.option("-title", "title", default=None,
              help="Custom report title.")
@click.option("-component", "component", default=None,
              help="Component name shown in report.")
@click.option("-skip-headers", "skip_headers", default=None, type=click.Path(path_type=Path),
              help="[Not yet implemented] File listing headers to exclude.")
@click.option("-skip-symbols", "skip_symbols_path", default=None, type=click.Path(path_type=Path),
              help="File with symbols to skip (blacklist).")
@click.option("-skip-types", "skip_types_path", default=None, type=click.Path(path_type=Path),
              help="File with types to skip (blacklist).")
@click.option("-symbols-list", "symbols_list_path", default=None, type=click.Path(path_type=Path),
              help="File with symbols to check (whitelist). Only these symbols will be reported.")
@click.option("-types-list", "types_list_path", default=None, type=click.Path(path_type=Path),
              help="File with types to check (whitelist). Only these types will be reported.")
@click.option("-skip-internal-symbols", "skip_internal_symbols", default=None,
              help="Regex pattern for internal symbols to skip.")
@click.option("-skip-internal-types", "skip_internal_types", default=None,
              help="Regex pattern for internal types to skip.")
@click.option("-warn-newsym", "warn_newsym", is_flag=True, default=False,
              help="Treat new symbols as compatibility breaks.")
@click.option("-limit-affected", "limit_affected", default=0, type=int,
              help="Max affected symbols shown per change kind.")
@click.option("-list-affected", "list_affected", is_flag=True, default=False,
              help="Generate a separate file listing affected symbols.")
@click.option("-stdout", "to_stdout", is_flag=True, default=False,
              help="Print report to stdout.")
@click.option("-q", "-quiet", "quiet", is_flag=True, default=False,
              help="Suppress console output (log to file only).")
def compat_cmd(
    lib_name: str,
    old_desc: Path,
    new_desc: Path,
    report_path: Path | None,
    fmt: str,
    suppress: Path | None,
    strict: bool,
    show_retval: bool,
    headers_only: bool,
    source_only: bool,
    binary_only: bool,
    vnum1: str | None,
    vnum2: str | None,
    title: str | None,
    component: str | None,
    skip_headers: Path | None,
    skip_symbols_path: Path | None,
    skip_types_path: Path | None,
    symbols_list_path: Path | None,
    types_list_path: Path | None,
    skip_internal_symbols: str | None,
    skip_internal_types: str | None,
    warn_newsym: bool,
    limit_affected: int,
    list_affected: bool,
    to_stdout: bool,
    quiet: bool,
) -> None:
    """Drop-in replacement for abi-compliance-checker.

    Reads ABICC-format XML descriptors and produces an ABI compatibility report.
    Supports all major ABICC flags for drop-in CI replacement.

    Exit codes mirror ABICC:
      0 — compatible or no change (NO_CHANGE, COMPATIBLE)
      1 — breaking ABI change detected (BREAKING)
      2 — source-level break (SOURCE_BREAK) or error (descriptor parse failure, etc.)

    Note: with -strict, SOURCE_BREAK is promoted to exit 1.

    Examples::

        # Before:
        abi-compliance-checker -lib libdnnl -old old.xml -new new.xml -report-path r.html

        # After (identical flags):
        abicheck compat -lib libdnnl -old old.xml -new new.xml -report-path r.html

        # Strict mode (any change = error):
        abicheck compat -lib libdnnl -old old.xml -new new.xml -s

        # Source (API) compatibility only:
        abicheck compat -lib libdnnl -old old.xml -new new.xml -source

        # Whitelist: only check specific symbols:
        abicheck compat -lib libdnnl -old old.xml -new new.xml -symbols-list public_api.txt

        # Create ABI dump first, then compare:
        abicheck compat-dump -lib libdnnl -dump v1.xml
        abicheck compat-dump -lib libdnnl -dump v2.xml
        abicheck compare abi_dumps/libdnnl/v1/dump.json abi_dumps/libdnnl/v2/dump.json
    """
    from .suppression import SuppressionList  # local import to avoid circular

    # Parse descriptors (support both XML descriptors and JSON dumps)
    try:
        old_d = _load_descriptor_or_dump(old_desc)
        new_d = _load_descriptor_or_dump(new_desc)
    except (ValueError, FileNotFoundError, OSError) as exc:
        click.echo(f"Error parsing descriptor: {exc}", err=True)
        sys.exit(2)

    # If inputs were JSON dumps, skip the dump step
    if isinstance(old_d, tuple):
        old_snap, new_snap = old_d[0], new_d[0]  # type: ignore[index]
        old_version = old_snap.version
        new_version = new_snap.version
    else:
        if vnum1:
            old_d = old_d.__class__(
                version=vnum1, headers=old_d.headers, libs=old_d.libs, path=old_d.path
            )
        if vnum2:
            new_d = new_d.__class__(
                version=vnum2, headers=new_d.headers, libs=new_d.libs, path=new_d.path
            )

        # Resolve .so paths — use first lib in each descriptor.
        old_so = old_d.libs[0]
        new_so = new_d.libs[0]
        if len(old_d.libs) > 1:
            _do_echo(
                f"Warning: descriptor {old_desc.name} has {len(old_d.libs)} <libs> entries; "
                f"using only the first: {old_so}",
                quiet,
            )
        if len(new_d.libs) > 1:
            _do_echo(
                f"Warning: descriptor {new_desc.name} has {len(new_d.libs)} <libs> entries; "
                f"using only the first: {new_so}",
                quiet,
            )

        old_headers = old_d.headers
        new_headers = new_d.headers

        if headers_only:
            _do_echo("Note: -headers-only is not yet implemented — ELF/DWARF checks still run.", quiet)

        if not old_headers or not new_headers:
            _do_echo(
                "Warning: one or both descriptors have no <headers> entry. "
                "Type-level ABI checks (struct layout, enum values, etc.) will be skipped.",
                quiet,
            )

        if not old_so.exists():
            click.echo(f"Error: library not found: {old_so}", err=True)
            sys.exit(2)
        if not new_so.exists():
            click.echo(f"Error: library not found: {new_so}", err=True)
            sys.exit(2)

        try:
            old_snap = dump(old_so, headers=old_headers, version=old_d.version)
            new_snap = dump(new_so, headers=new_headers, version=new_d.version)
        except Exception as exc:  # noqa: BLE001
            click.echo(f"Error during dump: {exc}", err=True)
            sys.exit(2)

        old_version = old_d.version
        new_version = new_d.version

    # ── Build suppression from all sources ────────────────────────────────
    suppression: SuppressionList | None = None

    # -skip-symbols / -skip-types: build suppression on the fly
    if skip_symbols_path is not None or skip_types_path is not None:
        try:
            suppression = _build_skip_suppression(skip_symbols_path, skip_types_path)
        except ValueError as exc:
            click.echo(f"Error in skip-symbols/skip-types: {exc}", err=True)
            sys.exit(2)

    # -symbols-list / -types-list: whitelist (inverse of skip)
    if symbols_list_path is not None or types_list_path is not None:
        try:
            wl = _build_whitelist_suppression(symbols_list_path, types_list_path)
            suppression = _merge_suppression(suppression, wl)
        except ValueError as exc:
            click.echo(f"Error in symbols-list/types-list: {exc}", err=True)
            sys.exit(2)

    # -skip-internal-symbols / -skip-internal-types: regex-based skip
    if skip_internal_symbols is not None or skip_internal_types is not None:
        try:
            internal = _build_internal_suppression(skip_internal_symbols, skip_internal_types)
            suppression = _merge_suppression(suppression, internal)
        except ValueError as exc:
            click.echo(f"Error in skip-internal-symbols/skip-internal-types: {exc}", err=True)
            sys.exit(2)

    # --suppress: YAML suppression file
    if suppress is not None:
        try:
            file_suppression = SuppressionList.load(suppress)
        except (ValueError, OSError) as exc:
            click.echo(f"Error loading suppression file: {exc}", err=True)
            sys.exit(2)
        suppression = _merge_suppression(suppression, file_suppression)

    result = compare(old_snap, new_snap, suppression=suppression)

    # ── Post-compare transforms ───────────────────────────────────────────

    # -source: filter to source/API breaks only
    if source_only and not binary_only:
        result = _filter_source_only(result)

    # -warn-newsym: treat new symbols as breaks
    if warn_newsym:
        result = _apply_warn_newsym(result)

    # -strict: treat COMPATIBLE and SOURCE_BREAK as BREAKING
    if strict:
        result = _apply_strict(result)

    # -limit-affected: cap reported changes per kind
    if limit_affected > 0:
        result = _limit_affected_changes(result, limit_affected)

    verdict = result.verdict.value if hasattr(result.verdict, "value") else str(result.verdict)

    # ── Determine report output path ──────────────────────────────────────
    if report_path is None:
        ext = fmt.lower()
        report_path = (
            Path("compat_reports")
            / _safe_path(lib_name)
            / f"{_safe_path(old_version)}_to_{_safe_path(new_version)}"
            / f"report.{ext}"
        )

    report_path.parent.mkdir(parents=True, exist_ok=True)

    # Build effective title
    effective_title = title
    if component and not effective_title:
        effective_title = f"ABI Compatibility Report — {lib_name} ({component})"

    if fmt == "html":
        from .model import Visibility
        old_symbol_count = sum(
            1 for f in old_snap.functions
            if f.visibility in (Visibility.PUBLIC, Visibility.ELF_ONLY)
        ) + sum(
            1 for v in old_snap.variables
            if v.visibility in (Visibility.PUBLIC, Visibility.ELF_ONLY)
        )
        write_html_report(
            result, output_path=report_path,
            lib_name=lib_name,
            old_version=old_version, new_version=new_version,
            old_symbol_count=old_symbol_count or None,
            title=effective_title,
        )
    elif fmt == "json":
        report_path.write_text(to_json(result), encoding="utf-8")
    else:
        report_path.write_text(to_markdown(result), encoding="utf-8")

    # -list-affected: write affected symbols to separate file
    if list_affected:
        affected_path = report_path.with_suffix(".affected.txt")
        _write_affected_list(result, affected_path)
        _do_echo(f"Affected symbols: {affected_path}", quiet)

    if to_stdout:
        click.echo(report_path.read_text(encoding="utf-8"))

    _do_echo(f"Verdict: {verdict}", quiet)
    _do_echo(f"Report:  {report_path}", quiet)

    # Exit codes mirror ABICC:
    #   0 = NO_CHANGE or COMPATIBLE
    #   1 = BREAKING
    #   2 = SOURCE_BREAK (source-level break, binary compatible)
    if verdict == "BREAKING":
        sys.exit(1)
    if verdict == "SOURCE_BREAK":
        sys.exit(2)


def _load_descriptor_or_dump(path: Path) -> object:
    """Load either an ABICC XML descriptor or a JSON ABI dump.

    Returns:
        CompatDescriptor for XML files, or (AbiSnapshot,) tuple for JSON dumps.

    Raises:
        ValueError: If the file is an ABICC Perl dump (unsupported format).
    """
    # Detect ABICC Perl dump format (.dump extension or Data::Dumper content)
    if path.suffix == ".dump":
        raise ValueError(
            f"ABICC Perl dump format is not supported: {path}\n"
            "  abicheck uses its own JSON dump format.\n"
            "  To migrate, re-create the dump from the original XML descriptor:\n"
            "    abicheck compat-dump -lib LIBNAME -dump descriptor.xml -dump-path output.json\n"
            "  Then use the JSON dump for comparison."
        )

    # Heuristic: if the file is JSON, load as a dump
    if path.suffix == ".json":
        snap = load_snapshot(path)
        return (snap,)

    # For XML files, peek at content to detect ABICC Perl dump disguised as .xml
    # (ABICC -dump-format xml produces a different XML schema than descriptors)
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:512]
    except OSError:
        head = ""

    # Detect ABICC Perl Data::Dumper format (starts with $VAR1 = { or similar)
    if head.lstrip().startswith("$VAR1"):
        raise ValueError(
            f"ABICC Perl dump format detected: {path}\n"
            "  abicheck uses its own JSON dump format.\n"
            "  To migrate, re-create the dump from the original XML descriptor:\n"
            "    abicheck compat-dump -lib LIBNAME -dump descriptor.xml -dump-path output.json\n"
            "  Then use the JSON dump for comparison."
        )

    # Detect ABICC XML dump format (contains <ABI_dump_* or <abi_dump tags)
    if "<ABI_dump" in head or "<abi_dump" in head or "ABI_COMPLIANCE_CHECKER" in head:
        raise ValueError(
            f"ABICC XML dump format detected: {path}\n"
            "  abicheck uses its own JSON dump format and cannot read ABICC XML dumps.\n"
            "  To migrate, re-create the dump from the original XML descriptor:\n"
            "    abicheck compat-dump -lib LIBNAME -dump descriptor.xml -dump-path output.json\n"
            "  Then use the JSON dump for comparison."
        )

    # Otherwise parse as XML descriptor
    return parse_descriptor(path)


if __name__ == "__main__":
    main()
