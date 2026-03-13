"""CLI — abicheck dump | compare | compat (dump | check)."""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import click

from .checker import compare
from .compat.abicc_dump_import import import_abicc_perl_dump, looks_like_perl_dump
from .dumper import dump
from .errors import AbicheckError
from .reporter import to_json, to_markdown
from .serialization import load_snapshot, snapshot_to_json

if TYPE_CHECKING:
    from .suppression import SuppressionList

from . import __version__ as _abicheck_version
from .model import AbiSnapshot

# Number of bytes to read when sniffing file format (covers ELF magic + JSON/Perl head)
_SNIFF_BYTES = 256

_logger = logging.getLogger("abicheck")


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


def _resolve_input(
    path: Path,
    headers: list[Path],
    includes: list[Path],
    version: str,
    lang: str,
    *,
    is_elf: bool | None = None,
) -> AbiSnapshot:
    """Auto-detect input type and return an AbiSnapshot.

    Detection order:
    1. ELF binary (magic bytes ``\\x7fELF``) → :func:`dump` (requires headers)
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
    """
    if is_elf is None:
        is_elf = _is_elf(path)
    if is_elf:
        if not headers:
            raise click.UsageError(
                f"Input '{path}' is an ELF binary — "
                "at least one header (-H/--header or --old-header/--new-header) "
                "is required for ABI extraction."
            )
        for hdr in headers:
            if not hdr.exists() or not hdr.is_file():
                raise click.ClickException(f"Header file not found or not a file: {hdr}")
        for inc in includes:
            if not inc.exists() or not inc.is_dir():
                raise click.ClickException(f"Include directory not found or not a directory: {inc}")
        compiler = "c++" if lang == "c++" else "cc"
        try:
            return dump(
                so_path=path,
                headers=headers,
                extra_includes=includes,
                version=version,
                compiler=compiler,
            )
        except (AbicheckError, RuntimeError, OSError, ValueError) as exc:
            raise click.ClickException(f"Failed to dump '{path}': {exc}") from exc

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
        "Expected: ELF binary (.so), JSON snapshot (.json), or ABICC Perl dump."
    )


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
@click.option("-v", "--verbose", is_flag=True, default=False,
              help="Enable verbose/debug output.")
def dump_cmd(so_path: Path, headers: tuple[Path, ...], includes: tuple[Path, ...],
             version: str, lang: str, output: Path | None,
             gcc_path: str | None, gcc_prefix: str | None, gcc_options: str | None,
             sysroot: Path | None, nostdinc: bool, verbose: bool) -> None:
    """Dump ABI snapshot of a shared library to JSON.

    \b
    Example:
      abicheck dump libfoo.so.1 -H include/foo.h --version 1.2.3 -o snap.json
      abicheck dump libfoo.so.1 -H include/foo.h --lang c -o snap.json
      abicheck dump libfoo.so.1 -H include/foo.h --gcc-prefix aarch64-linux-gnu-
    """
    _setup_verbosity(verbose)

    compiler = "c++" if lang == "c++" else "cc"
    try:
        snap = dump(
            so_path=so_path,
            headers=list(headers),
            extra_includes=list(includes),
            version=version,
            compiler=compiler,
            gcc_path=gcc_path,
            gcc_prefix=gcc_prefix,
            gcc_options=gcc_options,
            sysroot=sysroot,
            nostdinc=nostdinc,
            lang=lang if lang == "c" else None,
        )
    except (AbicheckError, RuntimeError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc

    result = snapshot_to_json(snap)
    if output:
        output.write_text(result, encoding="utf-8")
        click.echo(f"Snapshot written to {output}", err=True)
    else:
        click.echo(result)


@main.command("compare")
@click.argument("old_input", type=click.Path(exists=True, path_type=Path))
@click.argument("new_input", type=click.Path(exists=True, path_type=Path))
# ── Dump options (used when input is an ELF binary) ──────────────────────────
@click.option("-H", "--header", "headers", multiple=True,
              type=click.Path(path_type=Path),
              help="Public header file applied to both sides (repeat for multiple). "
                   "Required when input is a .so file. "
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
    verbose: bool,
) -> None:
    """Compare two ABI surfaces and report changes.

    Each input (OLD, NEW) can be a .so shared library, a JSON snapshot from
    'abicheck dump', or an ABICC Perl dump file. The format is auto-detected.

    When a .so file is given, headers (-H) are required so that abicheck can
    extract the public ABI. Use --old-header / --new-header when headers differ
    between versions.

    \b
    Exit codes:
      0  NO_CHANGE or COMPATIBLE — no binary ABI break
      2  API_BREAK — source-level break; existing binaries are safe
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
    from .policy_file import PolicyFile
    from .suppression import SuppressionList

    _setup_verbosity(verbose)

    # Resolve per-side headers/includes: --old-header overrides -H, etc.
    old_h = list(old_headers_only) if old_headers_only else list(headers)
    new_h = list(new_headers_only) if new_headers_only else list(headers)
    old_inc = list(old_includes_only) if old_includes_only else list(includes)
    new_inc = list(new_includes_only) if new_includes_only else list(includes)

    # Warn if dump-only options are provided but not used (both inputs are snapshots)
    old_is_elf = _is_elf(old_input)
    new_is_elf = _is_elf(new_input)
    if not old_is_elf and not new_is_elf:
        ignored_flags: list[str] = []
        if headers:
            ignored_flags.append("-H/--header")
        if old_headers_only:
            ignored_flags.append("--old-header")
        if new_headers_only:
            ignored_flags.append("--new-header")
        if includes:
            ignored_flags.append("-I/--include")
        if old_includes_only:
            ignored_flags.append("--old-include")
        if new_includes_only:
            ignored_flags.append("--new-include")
        if ignored_flags:
            click.echo(
                f"Warning: {', '.join(ignored_flags)} ignored when both inputs are snapshots.",
                err=True,
            )

    old = _resolve_input(old_input, old_h, old_inc, old_version, lang, is_elf=old_is_elf)
    new = _resolve_input(new_input, new_h, new_inc, new_version, lang, is_elf=new_is_elf)

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
            "Warning: all ABI changes were suppressed by the suppression file. "
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
    compat_group,
)

# fmt: on

main.add_command(compat_group)


if __name__ == "__main__":
    main()
