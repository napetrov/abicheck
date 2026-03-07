"""CLI — abicheck dump | compare | scan | compat."""
from __future__ import annotations

import sys
from pathlib import Path

import click

from .checker import compare
from .compat import parse_descriptor
from .dumper import dump
from .html_report import write_html_report
from .reporter import to_json, to_markdown
from .serialization import load_snapshot


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
@click.option("--format", "fmt", type=click.Choice(["json", "markdown"]),
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


@main.command("compat")
@click.option("-lib", "lib_name", required=True, help="Library name (e.g. libdnnl).")
@click.option("-old", "old_desc", required=True, type=click.Path(exists=True, path_type=Path),
              help="Path to old version ABICC XML descriptor.")
@click.option("-new", "new_desc", required=True, type=click.Path(exists=True, path_type=Path),
              help="Path to new version ABICC XML descriptor.")
@click.option("-report-path", "report_path", default=None, type=click.Path(path_type=Path),
              help="Output report path. Default: compat_reports/<lib>/<old>_to_<new>/report.<fmt>.")
@click.option("-report-format", "fmt", default="html",
              type=click.Choice(["html", "json", "md"], case_sensitive=False),
              help="Report format (default: html).")
@click.option("--suppress", default=None, type=click.Path(path_type=Path),
              help="Suppression YAML file (passed through to compare).")
def compat_cmd(
    lib_name: str,
    old_desc: Path,
    new_desc: Path,
    report_path: Path | None,
    fmt: str,
    suppress: Path | None,
) -> None:
    """Drop-in replacement for abi-compliance-checker.

    Reads ABICC-format XML descriptors and produces an ABI compatibility report.

    Exit codes mirror ABICC:
      0 — compatible or no change
      1 — breaking ABI change detected
      2 — error (descriptor parse failure, missing files, etc.)

    Example (replacing an existing ABICC call)::

        # Before:
        abi-compliance-checker -lib libdnnl -old old.xml -new new.xml -report-path r.html

        # After:
        abicheck compat -lib libdnnl -old old.xml -new new.xml -report-path r.html
    """
    from .suppression import SuppressionList  # local import to avoid circular

    try:
        old = parse_descriptor(old_desc)
        new = parse_descriptor(new_desc)
    except (ValueError, FileNotFoundError, OSError) as exc:
        click.echo(f"Error parsing descriptor: {exc}", err=True)
        sys.exit(2)

    # Resolve .so paths — use first lib in each descriptor
    old_so = old.libs[0]
    new_so = new.libs[0]
    old_headers = old.headers[0] if old.headers else None
    new_headers = new.headers[0] if new.headers else None

    if not old_so.exists():
        click.echo(f"Error: library not found: {old_so}", err=True)
        sys.exit(2)
    if not new_so.exists():
        click.echo(f"Error: library not found: {new_so}", err=True)
        sys.exit(2)

    try:
        old_snap = dump(old_so,
                        headers=[old_headers] if old_headers else [],
                        version=old.version)
        new_snap = dump(new_so,
                        headers=[new_headers] if new_headers else [],
                        version=new.version)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"Error during dump: {exc}", err=True)
        sys.exit(2)

    suppression: SuppressionList | None = None
    if suppress is not None:
        try:
            suppression = SuppressionList.load(suppress)
        except (ValueError, OSError) as exc:
            click.echo(f"Error loading suppression file: {exc}", err=True)
            sys.exit(2)

    result = compare(old_snap, new_snap, suppression=suppression)
    verdict = result.verdict.value if hasattr(result.verdict, "value") else str(result.verdict)

    # Determine report output path
    if report_path is None:
        ext = fmt.lower()
        report_path = (
            Path("compat_reports")
            / lib_name
            / f"{old.version}_to_{new.version}"
            / f"report.{ext}"
        )

    report_path.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "html":
        write_html_report(result, output_path=report_path,
                          lib_name=lib_name,
                          old_version=old.version, new_version=new.version)
    elif fmt == "json":
        report_path.write_text(to_json(result), encoding="utf-8")
    else:
        report_path.write_text(to_markdown(result), encoding="utf-8")

    click.echo(f"Verdict: {verdict}", err=True)
    click.echo(f"Report:  {report_path}", err=True)

    # Exit codes: 0=compatible/no_change, 1=breaking, 2=error (already handled above)
    if verdict == "BREAKING":
        sys.exit(1)


if __name__ == "__main__":
    main()
