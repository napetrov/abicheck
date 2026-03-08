"""CLI — abicheck dump | compare | scan | compat."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import click

from .checker import ChangeKind, compare
from .compat import parse_descriptor
from .dumper import dump
from .html_report import write_html_report
from .reporter import to_json, to_markdown
from .serialization import load_snapshot

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
    from .serialization import snapshot_to_json
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
              help="Strict mode: any incompatible change is an error (exit 1). Mirrors ABICC -strict.")
@click.option("-show-retval", "show_retval", is_flag=True, default=False,
              help="Show return-value changes in report. Mirrors ABICC -show-retval.")
@click.option("-headers-only", "headers_only", is_flag=True, default=False,
              help="[Not yet implemented] Reserved for future header-only analysis mode. ELF/DWARF checks still run. Mirrors ABICC -headers-only.")
@click.option("-source", "-src", "-api", "source_only", is_flag=True, default=False,
              help="Check source (API) compatibility only, not binary ABI. Mirrors ABICC -source.")
@click.option("-binary", "-bin", "-abi", "binary_only", is_flag=True, default=False,
              help="Check binary (ABI) compatibility only. Mirrors ABICC -binary (default behavior).")
@click.option("-v1", "-vnum1", "vnum1", default=None,
              help="Override version label for old library.")
@click.option("-v2", "-vnum2", "vnum2", default=None,
              help="Override version label for new library.")
@click.option("-title", "title", default=None,
              help="Report title. Mirrors ABICC -title.")
@click.option("-skip-headers", "skip_headers", default=None, type=click.Path(path_type=Path),
              help="[Not yet implemented] Reserved for future header-skip support. Mirrors ABICC -skip-headers.")
@click.option("-skip-symbols", "skip_symbols_path", default=None, type=click.Path(path_type=Path),
              help="File with symbols to skip. Mirrors ABICC -skip-symbols.")
@click.option("-skip-types", "skip_types_path", default=None, type=click.Path(path_type=Path),
              help="File with types to skip. Mirrors ABICC -skip-types.")
@click.option("-stdout", "to_stdout", is_flag=True, default=False,
              help="Print report to stdout. Mirrors ABICC -stdout.")
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
    skip_headers: Path | None,
    skip_symbols_path: Path | None,
    skip_types_path: Path | None,
    to_stdout: bool,
) -> None:
    """Drop-in replacement for abi-compliance-checker.

    Reads ABICC-format XML descriptors and produces an ABI compatibility report.
    Supports all major ABICC flags for drop-in CI replacement.

    Exit codes mirror ABICC:
      0 — compatible or no change
      1 — breaking ABI change detected
      2 — error (descriptor parse failure, missing files, etc.)

    Examples::

        # Before:
        abi-compliance-checker -lib libdnnl -old old.xml -new new.xml -report-path r.html

        # After (identical flags):
        abicheck compat -lib libdnnl -old old.xml -new new.xml -report-path r.html

        # Strict mode (any change = error):
        abicheck compat -lib libdnnl -old old.xml -new new.xml -s

        # Source (API) compatibility only:
        abicheck compat -lib libdnnl -old old.xml -new new.xml -source
    """
    from .suppression import SuppressionList  # local import to avoid circular

    # Apply version label overrides from -v1/-v2 flags
    # (read descriptors first, then override version labels if provided)
    try:
        old_d = parse_descriptor(old_desc)
        new_d = parse_descriptor(new_desc)
    except (ValueError, FileNotFoundError, OSError) as exc:
        click.echo(f"Error parsing descriptor: {exc}", err=True)
        sys.exit(2)

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
        click.echo(
            f"Warning: descriptor {old_desc.name} has {len(old_d.libs)} <libs> entries; "
            f"using only the first: {old_so}",
            err=True,
        )
    if len(new_d.libs) > 1:
        click.echo(
            f"Warning: descriptor {new_desc.name} has {len(new_d.libs)} <libs> entries; "
            f"using only the first: {new_so}",
            err=True,
        )

    old_headers = old_d.headers
    new_headers = new_d.headers

    # -headers-only: skip ELF/DWARF, check API types only
    # -source: API compatibility only (suppress binary-only changes like SONAME, SYMBOL_*)
    # -binary: default ABI check (no extra filtering)
    if headers_only:
        click.echo("Note: -headers-only is not yet implemented — ELF/DWARF checks still run.", err=True)

    if not old_headers or not new_headers:
        click.echo(
            "Warning: one or both descriptors have no <headers> entry. "
            "Type-level ABI checks (struct layout, enum values, etc.) will be skipped.",
            err=True,
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

    suppression: SuppressionList | None = None

    # -skip-symbols / -skip-types: build suppression on the fly
    if skip_symbols_path is not None or skip_types_path is not None:
        try:
            suppression = _build_skip_suppression(skip_symbols_path, skip_types_path)
        except ValueError as exc:
            click.echo(f"Error in skip-symbols/skip-types: {exc}", err=True)
            sys.exit(2)

    if suppress is not None:
        try:
            file_suppression = SuppressionList.load(suppress)
        except (ValueError, OSError) as exc:
            click.echo(f"Error loading suppression file: {exc}", err=True)
            sys.exit(2)
        # Merge: file suppression + auto-generated skip suppression
        if suppression is not None:
            from .suppression import SuppressionList as SL  # noqa: PLC0415
            suppression = SL.merge(suppression, file_suppression)
        else:
            suppression = file_suppression

    result = compare(old_snap, new_snap, suppression=suppression)

    # -source: filter to source/API breaks only (exclude ELF-only symbol metadata changes)
    # -binary (explicit): no-op — default behavior. If both -source and -binary given, -binary wins.
    if source_only and not binary_only:
        result = _filter_source_only(result)

    # -strict: treat COMPATIBLE and SOURCE_BREAK as BREAKING (any deviation = error)
    if strict and result.verdict.value in ("COMPATIBLE", "SOURCE_BREAK"):
        from .checker import Verdict as V
        result = result.__class__(
            old_version=result.old_version,
            new_version=result.new_version,
            library=result.library,
            changes=result.changes,
            verdict=V.BREAKING,
            suppressed_count=result.suppressed_count,
            suppressed_changes=result.suppressed_changes,
            suppression_file_provided=result.suppression_file_provided,
        )

    verdict = result.verdict.value if hasattr(result.verdict, "value") else str(result.verdict)
    # Determine report output path
    if report_path is None:
        import re as _re
        ext = fmt.lower()

        def _safe_path(v: str) -> str:
            return _re.sub(r"[^\w.\-]", "_", v)

        report_path = (
            Path("compat_reports")
            / _safe_path(lib_name)
            / f"{_safe_path(old_d.version)}_to_{_safe_path(new_d.version)}"
            / f"report.{ext}"
        )

    report_path.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "html":
        from .model import Visibility
        old_symbol_count = sum(
            1 for f in old_snap.functions
            if f.visibility in (Visibility.PUBLIC, Visibility.ELF_ONLY)
        ) + sum(
            1 for v in old_snap.variables
            if v.visibility in (Visibility.PUBLIC, Visibility.ELF_ONLY)
        )
        # TODO(abicc-compat): wire -title to write_html_report once html_report supports custom titles
        write_html_report(
            result, output_path=report_path,
            lib_name=lib_name,
            old_version=old_d.version, new_version=new_d.version,
            old_symbol_count=old_symbol_count or None,
        )
    elif fmt == "json":
        report_path.write_text(to_json(result), encoding="utf-8")
    else:
        report_path.write_text(to_markdown(result), encoding="utf-8")

    if to_stdout:
        click.echo(report_path.read_text(encoding="utf-8"))

    click.echo(f"Verdict: {verdict}", err=True)
    click.echo(f"Report:  {report_path}", err=True)

    # Exit codes mirror ABICC:
    #   0 = NO_CHANGE or COMPATIBLE
    #   1 = BREAKING
    #   2 = SOURCE_BREAK (source-level break, binary compatible)
    if verdict == "BREAKING":
        sys.exit(1)
    if verdict == "SOURCE_BREAK":
        sys.exit(2)


if __name__ == "__main__":
    main()
