"""CLI — abicheck dump | compare | compat-dump | compat."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import click

from .checker import compare
from .dumper import dump
from .reporter import to_json, to_markdown
from .serialization import load_snapshot, snapshot_to_json

if TYPE_CHECKING:
    from .suppression import SuppressionList
from . import __version__ as _abicheck_version


@click.group()
@click.version_option(version=_abicheck_version, prog_name="abicheck")
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
    from .errors import AbicheckError

    try:
        snap = dump(
            so_path=so_path,
            headers=list(headers),
            extra_includes=list(includes),
            version=version,
            compiler=compiler,
        )
    except (AbicheckError, RuntimeError, OSError, ValueError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(2)

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
@click.option("--policy", "policy",
              type=click.Choice(["strict_abi", "sdk_vendor", "plugin_abi"], case_sensitive=True),
              default="strict_abi", show_default=True,
              help="Built-in policy profile for verdict classification. Ignored when --policy-file is given.")
@click.option("--policy-file", "policy_file_path",
              type=click.Path(exists=True, path_type=Path), default=None,
              help="YAML policy file with per-kind verdict overrides. Overrides --policy.")
def compare_cmd(old_snapshot: Path, new_snapshot: Path, fmt: str, output: Path | None,
                suppress: Path | None, policy: str, policy_file_path: Path | None) -> None:
    """Compare two ABI snapshots and report changes.

    \b
    Example:
      abicheck compare libfoo-1.0.json libfoo-2.0.json --format markdown
      abicheck compare libfoo-1.0.json libfoo-2.0.json --format sarif -o results.sarif
      abicheck compare libfoo-1.0.json libfoo-2.0.json --format html -o report.html
      abicheck compare libfoo-1.0.json libfoo-2.0.json --suppress suppressions.yaml
      abicheck compare libfoo-1.0.json libfoo-2.0.json --policy sdk_vendor
      abicheck compare libfoo-1.0.json libfoo-2.0.json --policy-file project_policy.yaml
    """
    from .policy_file import PolicyFile
    from .suppression import SuppressionList

    old = load_snapshot(old_snapshot)
    new = load_snapshot(new_snapshot)

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

    result = compare(old, new, suppression=suppression, policy=policy, policy_file=pf)

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
    elif result.verdict.value == "API_BREAK":
        sys.exit(2)

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
    compat_cmd,
    compat_dump_cmd,
)

# fmt: on

main.add_command(compat_dump_cmd)
main.add_command(compat_cmd)


if __name__ == "__main__":
    main()
