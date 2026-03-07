"""CLI — abicheck dump | compare | scan."""
from __future__ import annotations

import sys
from pathlib import Path

import click

from .checker import compare
from .dumper import dump
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


if __name__ == "__main__":
    main()
