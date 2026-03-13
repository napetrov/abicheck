"""CLI — abicheck dump | compare | scan | compat."""
from __future__ import annotations

import logging
import re as _re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import click

from .checker import ChangeKind, compare
from .checker_policy import API_BREAK_KINDS as _POLICY_API_BREAK_KINDS
from .checker_policy import compute_verdict as _compute_verdict
from .compat import CompatDescriptor, parse_descriptor
from .dumper import dump
from .html_report import write_html_report
from .reporter import to_json, to_markdown
from .serialization import load_snapshot, save_snapshot, snapshot_to_json
from .xml_report import write_xml_report

if TYPE_CHECKING:
    from .checker import DiffResult
    from .model import AbiSnapshot
    from .suppression import SuppressionList


@click.group()
@click.version_option(package_name="abicheck", prog_name="abicheck")
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
                # ABICC -skip-symbols commonly contains plain C function names
                # (e.g. "sub"), but our compare pipeline stores Itanium-mangled
                # symbols (e.g. "_Z3subii"). Add a fallback pattern only when the
                # name looks like a plain identifier (not already mangled, not a
                # type/struct name — identifiers starting with uppercase are likely
                # types and already matched by exact symbol= above).
                if (name.isidentifier()
                        and not name.startswith("_Z")
                        and name[0].islower()):
                    rules.append(Suppression(symbol_pattern=rf"_Z\d+{name}.*"))
    return SuppressionList(suppressions=rules)


def _build_whitelist_suppression(
    symbols_list_path: Path | None,
    types_list_path: Path | None,
) -> SuppressionList:
    """Build a SuppressionList that suppresses everything NOT in the whitelist.

    Inverts the whitelist into a regex-based suppression: any symbol/type not
    matching one of the whitelist entries is suppressed.

    Symbol and type whitelists are scoped independently: a symbol whitelist only
    affects symbol-level changes, and a type whitelist only affects type-level
    changes.  Names are preserved as-is (regex/glob syntax is not escaped).

    This is the inverse of -skip-symbols / -skip-types.
    """
    from .suppression import Suppression, SuppressionList  # noqa: PLC0415

    rules: list[Suppression] = []

    # -symbols-list: whitelist scoped to symbol_pattern (function/variable changes)
    if symbols_list_path is not None:
        names = [
            ln.strip() for ln in symbols_list_path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")
        ]
        if names:
            # Pattern matches anything that is NOT one of the whitelisted names.
            # Names are not escaped — regex/glob syntax is preserved.
            negate_pattern = f"(?!({'|'.join(names)})$).*"
            rules.append(Suppression(symbol_pattern=negate_pattern))

    # -types-list: whitelist scoped to type_pattern (type/enum/typedef changes only)
    if types_list_path is not None:
        names = [
            ln.strip() for ln in types_list_path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")
        ]
        if names:
            negate_pattern = f"(?!({'|'.join(names)})$).*"
            rules.append(Suppression(type_pattern=negate_pattern))

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
        rules.append(Suppression(type_pattern=skip_internal_types))
    return SuppressionList(suppressions=rules)


# API_BREAK-only ChangeKinds (source API breaks, not binary ABI breaks).
# Keep this aligned with checker policy as single source of truth.
_API_BREAK_KINDS: frozenset[ChangeKind] = frozenset(_POLICY_API_BREAK_KINDS)

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

# P2 stub flags — accepted for ABICC CLI compatibility but have no effect.
# Each maps to (param_name, help_text).
_P2_STUB_FLAGS: dict[str, str] = {
    "mingw_compatible": "-mingw-compatible: MinGW ABI mode (accepted, no effect)",
    "cxx_incompatible": "-cxx-incompatible: C++ incompatibility mode (accepted, no effect)",
    "cpp_compatible": "-cpp-compatible: C++ compatibility mode (accepted, no effect)",
    "static_libs": "-static: static library analysis (accepted, no effect)",
    "extended": "-ext/-extended: extended analysis mode (accepted, no effect)",
    "quick": "-quick: quick analysis mode (accepted, no effect)",
    "force": "-force: force analysis (accepted, no effect)",
    "check": "-check: dump validity check (accepted, no effect)",
    "extra_info": "-extra-info: extra analysis output directory (accepted, no effect)",
    "extra_dump": "-extra-dump: extended dump (accepted, no effect)",
    "sort_dump": "-sort: sort dump output (accepted, no effect)",
    "xml_format": "-xml: XML dump format (accepted, no effect)",
    "skip_typedef_uncover": "-skip-typedef-uncover: skip typedef uncovering (accepted, no effect)",
    "check_private_abi": "-check-private-abi: check private ABI (accepted, no effect)",
    "skip_unidentified": "-skip-unidentified: skip unidentified headers (accepted, no effect)",
    "tolerance": "-tolerance: header parsing tolerance (accepted, no effect)",
    "tolerant": "-tolerant: enable all tolerance levels (accepted, no effect)",
    "disable_constants_check": "-disable-constants-check: skip constant checking (accepted, no effect)",
    "skip_added_constants": "-skip-added-constants: skip new constants (accepted, no effect)",
    "skip_removed_constants": "-skip-removed-constants: skip removed constants (accepted, no effect)",
}


def _apply_strict(result: DiffResult, *, mode: str = "full") -> DiffResult:
    """Apply strict-mode verdict promotion.

    mode='full': COMPATIBLE and API_BREAK → BREAKING (matches ABICC -strict behaviour).
    mode='api':  only API_BREAK → BREAKING; COMPATIBLE stays COMPATIBLE.
                 Use when you want strict enforcement of API contract changes
                 but still allow purely additive changes.
    """
    from dataclasses import replace  # noqa: PLC0415

    from .checker import Verdict  # noqa: PLC0415

    verdicts_to_promote = (
        {"COMPATIBLE", "API_BREAK"} if mode == "full" else {"API_BREAK"}
    )
    if result.verdict.value in verdicts_to_promote:
        return replace(result, verdict=Verdict.BREAKING)
    return result


def _filter_source_only(result: DiffResult) -> DiffResult:
    """Remove binary-only changes from result for -source mode.

    Re-derives the verdict and propagates result.policy so that the returned
    DiffResult is fully self-consistent (verdict, .breaking, .source_breaks,
    .compatible all use the same policy).
    """
    from .checker import DiffResult  # noqa: PLC0415

    policy = result.policy
    filtered = [c for c in result.changes if c.kind not in _BINARY_ONLY_KINDS]
    verdict = _compute_verdict(filtered, policy=policy)

    return DiffResult(
        old_version=result.old_version,
        new_version=result.new_version,
        library=result.library,
        changes=filtered,
        verdict=verdict,
        suppressed_count=result.suppressed_count,
        suppressed_changes=result.suppressed_changes,
        suppression_file_provided=result.suppression_file_provided,
        policy=policy,
    )


def _filter_binary_only(result: DiffResult) -> DiffResult:
    """Remove source-only changes from result for -binary mode.

    Re-derives the verdict and propagates result.policy so that the returned
    DiffResult is fully self-consistent (verdict, .breaking, .source_breaks,
    .compatible all use the same policy).
    """
    from .checker import DiffResult  # noqa: PLC0415

    policy = result.policy
    filtered = [c for c in result.changes if c.kind not in _API_BREAK_KINDS]
    verdict = _compute_verdict(filtered, policy=policy)

    return DiffResult(
        old_version=result.old_version,
        new_version=result.new_version,
        library=result.library,
        changes=filtered,
        verdict=verdict,
        suppressed_count=result.suppressed_count,
        suppressed_changes=result.suppressed_changes,
        suppression_file_provided=result.suppression_file_provided,
        policy=policy,
    )


def _apply_warn_newsym(result: DiffResult) -> DiffResult:
    """Promote new-symbol additions to BREAKING when -warn-newsym is set."""
    from .checker import DiffResult, Verdict  # noqa: PLC0415

    has_new = any(c.kind in _NEW_SYMBOL_KINDS for c in result.changes)
    if has_new and result.verdict.value in ("COMPATIBLE", "NO_CHANGE", "API_BREAK"):
        return DiffResult(
            old_version=result.old_version,
            new_version=result.new_version,
            library=result.library,
            changes=result.changes,
            verdict=Verdict.BREAKING,
            suppressed_count=result.suppressed_count,
            suppressed_changes=result.suppressed_changes,
            suppression_file_provided=result.suppression_file_provided,
            policy=result.policy,
        )
    return result


def _limit_affected_changes(result: DiffResult, limit: int) -> DiffResult:
    """Limit the number of reported changes per unique ChangeKind."""
    from .checker import Change, DiffResult  # noqa: PLC0415

    if limit <= 0:
        return result

    counts: dict[ChangeKind, int] = {}
    filtered: list[Change] = []
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
        policy=result.policy,
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


def _detect_compiler_version(gcc_path: str | None = None) -> str:
    """Detect GCC version for ABICC XML report <gcc> element."""
    import shutil
    import subprocess as _sp
    compiler = gcc_path or shutil.which("gcc") or shutil.which("cc") or ""
    if not compiler:
        return ""
    try:
        r = _sp.run([compiler, "-dumpversion"], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, _sp.TimeoutExpired):
        return ""


def _setup_logging(
    log_path: Path | None,
    log1_path: Path | None,
    log2_path: Path | None,
    logging_mode: str | None,
    quiet: bool,
) -> tuple[logging.FileHandler | None, logging.FileHandler | None]:
    """Configure logging based on ABICC-style log flags.

    -log-path: shared handler attached immediately.
    -log1-path / -log2-path: per-phase handlers returned (not yet attached)
    so the caller can activate them around the old/new dump phases.

    Returns (log1_handler, log2_handler) — either may be None.
    ``-logging-mode n`` disables file handlers entirely.
    """
    logger = logging.getLogger("abicheck")

    # Close and remove any existing FileHandlers to avoid leaking open files
    # when _setup_logging is called multiple times.
    for existing in list(logger.handlers):
        if isinstance(existing, logging.FileHandler):
            existing.close()
            logger.removeHandler(existing)

    if quiet:
        logger.setLevel(logging.WARNING)

    # -logging-mode n: no file handlers
    if logging_mode == "n":
        return None, None

    mode = "a" if logging_mode == "a" else "w"
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    any_handler = False

    def _make_handler(p: Path) -> logging.FileHandler:
        p.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(str(p), mode=mode, encoding="utf-8")
        handler.setFormatter(fmt)
        return handler

    # Shared log: attach immediately
    if log_path is not None:
        logger.addHandler(_make_handler(log_path))
        any_handler = True

    # Per-phase handlers: create but do NOT attach yet
    log1_handler = _make_handler(log1_path) if log1_path is not None else None
    log2_handler = _make_handler(log2_path) if log2_path is not None else None

    if (any_handler or log1_handler or log2_handler) and not quiet:
        logger.setLevel(logging.DEBUG)

    return log1_handler, log2_handler


def _load_skip_headers(skip_headers_path: Path | None) -> set[str]:
    """Load a set of header names/paths to exclude from analysis."""
    if skip_headers_path is None:
        return set()
    lines = [
        ln.strip() for ln in skip_headers_path.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.startswith("#")
    ]
    return set(lines)


def _resolve_headers_from_list(
    headers_list_path: Path | None,
    single_header: str | None,
    base_headers: list[Path],
    *,
    skip_headers: set[str] | None = None,
) -> list[Path]:
    """Merge headers from -headers-list file and -header flag with descriptor headers."""
    result = list(base_headers)

    if headers_list_path is not None:
        list_base = headers_list_path.parent
        lines = [
            ln.strip() for ln in headers_list_path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")
        ]
        for line in lines:
            p = Path(line)
            # Resolve relative paths against the list file's directory
            if not p.is_absolute():
                p = list_base / p
            if p.exists():
                result.append(p)

    if single_header is not None:
        p = Path(single_header)
        if p.exists():
            result.append(p)

    # Apply -skip-headers filtering: exclude headers whose name or path matches
    if skip_headers:
        result = [
            h for h in result
            if h.name not in skip_headers and str(h) not in skip_headers
        ]

    return result


def _warn_stub_flags(quiet: bool, **kwargs: object) -> None:
    """Emit warnings for P2 stub flags that were passed but have no effect."""
    for param_name, help_text in _P2_STUB_FLAGS.items():
        val = kwargs.get(param_name)
        if val is not None and val is not False and val != 0:
            _do_echo(f"Warning: {help_text}", quiet)


# ── compat dump subcommand ────────────────────────────────────────────────────

@main.command("compat-dump")
@click.option("-lib", "-l", "-library", "lib_name", required=True, help="Library name.")
@click.option("-dump", "desc_path", required=True, type=click.Path(exists=True, path_type=Path),
              help="Path to ABICC XML descriptor to dump.")
@click.option("-dump-path", "dump_path", default=None, type=click.Path(path_type=Path),
              help="Output dump file path. Default: abi_dumps/<lib>/<version>/dump.json.")
@click.option("-dump-format", "dump_format", default="json",
              help="Dump format. Only 'json' is supported (ABICC perl/xml not supported).")
@click.option("-vnum", "vnum", default=None, help="Override version label.")
# ── Cross-compilation flags ───────────────────────────────────────────────────
@click.option("-gcc-path", "-cross-gcc", "gcc_path", default=None,
              help="Path to GCC/G++ cross-compiler binary.")
@click.option("-gcc-prefix", "-cross-prefix", "gcc_prefix", default=None,
              help="Cross-toolchain prefix (e.g. aarch64-linux-gnu-).")
@click.option("-gcc-options", "gcc_options", default=None,
              help="Extra compiler flags passed through to castxml.")
@click.option("-sysroot", "sysroot", default=None, type=click.Path(path_type=Path),
              help="Alternative system root directory.")
@click.option("-nostdinc", "nostdinc", is_flag=True, default=False,
              help="Do not search standard system include paths.")
@click.option("-lang", "lang", default=None, help="Force language: C or C++.")
@click.option("-arch", "arch", default=None, help="Target architecture (informational).")
@click.option("-relpath", "relpath", default=None,
              help="Replace {RELPATH} macros in descriptor paths.")
@click.option("-q", "-quiet", "quiet", is_flag=True, default=False, help="Suppress console output.")
# ── P2 stub flags (accepted for compat, no effect) ───────────────────────────
@click.option("-sort", "sort_dump", is_flag=True, default=False, hidden=True)
@click.option("-extra-dump", "extra_dump", is_flag=True, default=False, hidden=True)
@click.option("-extra-info", "extra_info", default=None, hidden=True)
@click.option("-check", "check", is_flag=True, default=False, hidden=True)
@click.option("-xml", "xml_format", is_flag=True, default=False, hidden=True)
def compat_dump_cmd(
    lib_name: str,
    desc_path: Path,
    dump_path: Path | None,
    dump_format: str,
    vnum: str | None,
    gcc_path: str | None,
    gcc_prefix: str | None,
    gcc_options: str | None,
    sysroot: Path | None,
    nostdinc: bool,
    lang: str | None,
    arch: str | None,
    relpath: str | None,
    quiet: bool,
    # P2 stubs
    sort_dump: bool,
    extra_dump: bool,
    extra_info: str | None,
    check: bool,
    xml_format: bool,
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

        # Cross-compilation:
        abicheck compat-dump -lib libfoo -dump v1.xml -gcc-prefix aarch64-linux-gnu-
    """
    _warn_stub_flags(quiet, sort_dump=sort_dump, extra_dump=extra_dump,
                     extra_info=extra_info, check=check, xml_format=xml_format)

    if dump_format.lower() not in ("json",):
        _do_echo(
            f"Warning: dump format '{dump_format}' is not supported. Using JSON.",
            quiet,
        )

    if arch:
        _do_echo(f"Note: -arch {arch} is recorded for informational purposes.", quiet)

    try:
        desc = parse_descriptor(desc_path, relpath=relpath)
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
        snap = dump(
            so_path, headers=desc.headers, version=desc.version,
            gcc_path=gcc_path, gcc_prefix=gcc_prefix, gcc_options=gcc_options,
            sysroot=sysroot, nostdinc=nostdinc, lang=lang,
        )
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
# ── Core input flags ──────────────────────────────────────────────────────────
@click.option("-lib", "-l", "-library", "lib_name", required=True, help="Library name (e.g. libdnnl).")
@click.option("-old", "-d1", "-o", "old_desc", required=True, type=click.Path(exists=True, path_type=Path),
              help="Path to old version ABICC XML descriptor or ABI dump.")
@click.option("-new", "-d2", "-n", "new_desc", required=True, type=click.Path(exists=True, path_type=Path),
              help="Path to new version ABICC XML descriptor or ABI dump.")
@click.option("-d", "-f", "-filter", "filter_path", default=None, type=click.Path(path_type=Path),
              help="Path to XML descriptor with skip_* filtering rules.")
@click.option("-p", "-params", "params_path", default=None, type=click.Path(path_type=Path),
              help="Path to parameters file (accepted for compat, informational).")
@click.option("-app", "-application", "app_path", default=None, type=click.Path(path_type=Path),
              help="Application binary for portability checking (accepted for compat).")
# ── Report output flags ──────────────────────────────────────────────────────
@click.option("-report-path", "report_path", default=None, type=click.Path(path_type=Path),
              help="Output report path.")
@click.option("-bin-report-path", "bin_report_path", default=None, type=click.Path(path_type=Path),
              help="Separate binary-mode report output path.")
@click.option("-src-report-path", "src_report_path", default=None, type=click.Path(path_type=Path),
              help="Separate source-mode report output path.")
@click.option("-report-format", "fmt", default="html",
              type=click.Choice(["html", "htm", "xml", "json", "md"], case_sensitive=False),
              help="Report format (default: html). 'htm' is an alias for 'html'.")
@click.option("--suppress", default=None, type=click.Path(path_type=Path),
              help="Suppression YAML file.")
# ── Analysis mode flags ──────────────────────────────────────────────────────
@click.option("-s", "-strict", "strict", is_flag=True, default=False,
              help="Strict mode: any incompatible change is an error (exit 1).")
@click.option("--strict-mode", "strict_mode",
              type=click.Choice(["full", "api"], case_sensitive=False),
              default="full",
              help="Strict promotion mode: 'full' (COMPATIBLE+API_BREAK→BREAKING, ABICC parity) "
                   "or 'api' (only API_BREAK→BREAKING, COMPATIBLE stays COMPATIBLE). "
                   "Only applies when -strict is also set.")
@click.option("-show-retval", "show_retval", is_flag=True, default=False,
              help="Show return-value changes in report.")
@click.option("-headers-only", "headers_only", is_flag=True, default=False,
              help="Header-only analysis mode (ELF/DWARF checks still run).")
@click.option("-source", "-src", "-api", "source_only", is_flag=True, default=False,
              help="Check source (API) compatibility only.")
@click.option("-binary", "-bin", "-abi", "binary_only", is_flag=True, default=False,
              help="Check binary (ABI) compatibility only (default).")
@click.option("-warn-newsym", "warn_newsym", is_flag=True, default=False,
              help="Treat new symbols as compatibility breaks.")
@click.option("-old-style", "-compat-html", "compat_html", is_flag=True, default=False,
              help="Generate ABICC-compatible HTML with matching element IDs and structure.")
@click.option("-use-dumps", "use_dumps", is_flag=True, default=False,
              help="Interpret -old/-new as pre-built dumps (auto-detected).")
# ── Version label flags ──────────────────────────────────────────────────────
@click.option("-v1", "-vnum1", "-version1", "vnum1", default=None,
              help="Override version label for old library.")
@click.option("-v2", "-vnum2", "-version2", "vnum2", default=None,
              help="Override version label for new library.")
# ── Report presentation flags ────────────────────────────────────────────────
@click.option("-title", "title", default=None, help="Custom report title.")
@click.option("-component", "component", default=None, help="Component name shown in report.")
@click.option("-limit-affected", "limit_affected", default=0, type=int,
              help="Max affected symbols shown per change kind.")
@click.option("-list-affected", "list_affected", is_flag=True, default=False,
              help="Generate a separate file listing affected symbols.")
@click.option("-stdout", "to_stdout", is_flag=True, default=False,
              help="Print report to stdout.")
# ── Header filtering flags ───────────────────────────────────────────────────
@click.option("-skip-headers", "skip_headers", default=None, type=click.Path(path_type=Path),
              help="File listing headers to exclude from analysis, one per line.")
@click.option("-headers-list", "headers_list_path", default=None, type=click.Path(path_type=Path),
              help="File listing specific headers to include.")
@click.option("-header", "single_header", default=None,
              help="Single header file to analyze.")
# ── Symbol/type filtering flags ──────────────────────────────────────────────
@click.option("-skip-symbols", "skip_symbols_path", default=None, type=click.Path(path_type=Path),
              help="File with symbols to skip (blacklist).")
@click.option("-skip-types", "skip_types_path", default=None, type=click.Path(path_type=Path),
              help="File with types to skip (blacklist).")
@click.option("-symbols-list", "symbols_list_path", default=None, type=click.Path(path_type=Path),
              help="File with symbols to check (whitelist).")
@click.option("-types-list", "types_list_path", default=None, type=click.Path(path_type=Path),
              help="File with types to check (whitelist).")
@click.option("-skip-internal-symbols", "skip_internal_symbols", default=None,
              help="Regex pattern for internal symbols to skip.")
@click.option("-skip-internal-types", "skip_internal_types", default=None,
              help="Regex pattern for internal types to skip.")
@click.option("-keep-cxx", "keep_cxx", is_flag=True, default=False,
              help="Include _ZS*, _ZNS*, _ZNKS* (C++ std) mangled symbols.")
@click.option("-keep-reserved", "keep_reserved", is_flag=True, default=False,
              help="Report changes in reserved fields.")
# ── Cross-compilation / toolchain flags ──────────────────────────────────────
@click.option("-gcc-path", "-cross-gcc", "gcc_path", default=None,
              help="Path to GCC/G++ cross-compiler binary.")
@click.option("-gcc-prefix", "-cross-prefix", "gcc_prefix", default=None,
              help="Cross-toolchain prefix (e.g. aarch64-linux-gnu-).")
@click.option("-gcc-options", "gcc_options", default=None,
              help="Extra compiler flags passed through to castxml.")
@click.option("-sysroot", "sysroot", default=None, type=click.Path(path_type=Path),
              help="Alternative system root directory.")
@click.option("-nostdinc", "nostdinc", is_flag=True, default=False,
              help="Do not search standard system include paths.")
@click.option("-lang", "lang", default=None, help="Force language: C or C++.")
@click.option("-arch", "arch", default=None, help="Target architecture (informational).")
# ── Relpath flags ────────────────────────────────────────────────────────────
@click.option("-relpath", "relpath", default=None,
              help="Replace {RELPATH} macros in both descriptor paths.")
@click.option("-relpath1", "relpath1", default=None,
              help="Replace {RELPATH} macros in old descriptor paths.")
@click.option("-relpath2", "relpath2", default=None,
              help="Replace {RELPATH} macros in new descriptor paths.")
# ── Logging flags ────────────────────────────────────────────────────────────
@click.option("-q", "-quiet", "quiet", is_flag=True, default=False,
              help="Suppress console output.")
@click.option("-log-path", "log_path", default=None, type=click.Path(path_type=Path),
              help="Redirect log output to file.")
@click.option("-log1-path", "log1_path", default=None, type=click.Path(path_type=Path),
              help="Separate log path for old library analysis.")
@click.option("-log2-path", "log2_path", default=None, type=click.Path(path_type=Path),
              help="Separate log path for new library analysis.")
@click.option("-logging-mode", "logging_mode", default=None,
              help="Logging mode: 'w' (overwrite), 'a' (append), 'n' (none).")
# ── P2 stub flags (accepted for ABICC compat, no effect) ─────────────────────
@click.option("-mingw-compatible", "mingw_compatible", is_flag=True, default=False, hidden=True)
@click.option("-cxx-incompatible", "-cpp-incompatible", "cxx_incompatible", is_flag=True, default=False, hidden=True)
@click.option("-cpp-compatible", "cpp_compatible", is_flag=True, default=False, hidden=True)
@click.option("-static", "-static-libs", "static_libs", is_flag=True, default=False, hidden=True)
@click.option("-ext", "-extended", "extended", is_flag=True, default=False, hidden=True)
@click.option("-quick", "quick", is_flag=True, default=False, hidden=True)
@click.option("-force", "force", is_flag=True, default=False, hidden=True)
@click.option("-check", "check", is_flag=True, default=False, hidden=True)
@click.option("-extra-info", "extra_info", default=None, hidden=True)
@click.option("-extra-dump", "extra_dump", is_flag=True, default=False, hidden=True)
@click.option("-sort", "sort_dump", is_flag=True, default=False, hidden=True)
@click.option("-xml", "xml_format", is_flag=True, default=False, hidden=True)
@click.option("-skip-typedef-uncover", "skip_typedef_uncover", is_flag=True, default=False, hidden=True)
@click.option("-check-private-abi", "check_private_abi", is_flag=True, default=False, hidden=True)
@click.option("-skip-unidentified", "skip_unidentified", is_flag=True, default=False, hidden=True)
@click.option("-tolerance", "tolerance", default=None, hidden=True)
@click.option("-tolerant", "tolerant", is_flag=True, default=False, hidden=True)
@click.option("-disable-constants-check", "disable_constants_check", is_flag=True, default=False, hidden=True)
@click.option("-skip-added-constants", "skip_added_constants", is_flag=True, default=False, hidden=True)
@click.option("-skip-removed-constants", "skip_removed_constants", is_flag=True, default=False, hidden=True)
@click.option("-count-symbols", "count_symbols", default=None, hidden=True)
@click.option("-count-all-symbols", "count_all_symbols", default=None, hidden=True)
def compat_cmd(  # noqa: PLR0913
    lib_name: str,
    old_desc: Path,
    new_desc: Path,
    filter_path: Path | None,
    params_path: Path | None,
    app_path: Path | None,
    report_path: Path | None,
    bin_report_path: Path | None,
    src_report_path: Path | None,
    fmt: str,
    suppress: Path | None,
    strict: bool,
    strict_mode: str,
    show_retval: bool,
    headers_only: bool,
    source_only: bool,
    binary_only: bool,
    warn_newsym: bool,
    compat_html: bool,
    use_dumps: bool,
    vnum1: str | None,
    vnum2: str | None,
    title: str | None,
    component: str | None,
    limit_affected: int,
    list_affected: bool,
    to_stdout: bool,
    skip_headers: Path | None,
    headers_list_path: Path | None,
    single_header: str | None,
    skip_symbols_path: Path | None,
    skip_types_path: Path | None,
    symbols_list_path: Path | None,
    types_list_path: Path | None,
    skip_internal_symbols: str | None,
    skip_internal_types: str | None,
    keep_cxx: bool,
    keep_reserved: bool,
    gcc_path: str | None,
    gcc_prefix: str | None,
    gcc_options: str | None,
    sysroot: Path | None,
    nostdinc: bool,
    lang: str | None,
    arch: str | None,
    relpath: str | None,
    relpath1: str | None,
    relpath2: str | None,
    quiet: bool,
    log_path: Path | None,
    log1_path: Path | None,
    log2_path: Path | None,
    logging_mode: str | None,
    # P2 stubs
    mingw_compatible: bool,
    cxx_incompatible: bool,
    cpp_compatible: bool,
    static_libs: bool,
    extended: bool,
    quick: bool,
    force: bool,
    check: bool,
    extra_info: str | None,
    extra_dump: bool,
    sort_dump: bool,
    xml_format: bool,
    skip_typedef_uncover: bool,
    check_private_abi: bool,
    skip_unidentified: bool,
    tolerance: str | None,
    tolerant: bool,
    disable_constants_check: bool,
    skip_added_constants: bool,
    skip_removed_constants: bool,
    count_symbols: str | None,
    count_all_symbols: str | None,
) -> None:
    """Drop-in replacement for abi-compliance-checker.

    Reads ABICC-format XML descriptors and produces an ABI compatibility report.
    Supports all ABICC flags for drop-in CI replacement.

    Exit codes mirror ABICC:
      0 — compatible or no change (NO_CHANGE, COMPATIBLE)
      1 — breaking ABI change detected (BREAKING)
      2 — source-level break (API_BREAK) or error

    Note: with -strict, API_BREAK is promoted to exit 1.

    Examples::

        # Before:
        abi-compliance-checker -lib libdnnl -old old.xml -new new.xml -report-path r.html

        # After (identical flags):
        abicheck compat -lib libdnnl -old old.xml -new new.xml -report-path r.html
    """
    from .suppression import SuppressionList  # local import to avoid circular

    # ── Setup logging ────────────────────────────────────────────────────
    try:
        _log1_handler, _log2_handler = _setup_logging(log_path, log1_path, log2_path, logging_mode, quiet)
    except OSError as exc:
        click.echo(f"Error setting up logging: {exc}", err=True)
        sys.exit(2)

    # ── Warn about P2 stub flags ─────────────────────────────────────────
    _warn_stub_flags(
        quiet,
        mingw_compatible=mingw_compatible, cxx_incompatible=cxx_incompatible,
        cpp_compatible=cpp_compatible, static_libs=static_libs,
        extended=extended, quick=quick, force=force, check=check,
        extra_info=extra_info, extra_dump=extra_dump, sort_dump=sort_dump,
        xml_format=xml_format, skip_typedef_uncover=skip_typedef_uncover,
        check_private_abi=check_private_abi, skip_unidentified=skip_unidentified,
        tolerance=tolerance, tolerant=tolerant,
        disable_constants_check=disable_constants_check,
        skip_added_constants=skip_added_constants,
        skip_removed_constants=skip_removed_constants,
    )

    # Info-level notices for accepted but limited-effect flags
    if compat_html:
        _do_echo("Note: -compat-html / -old-style enabled: HTML will match ABICC element IDs.", quiet)
    if use_dumps:
        _do_echo("Note: -use-dumps is accepted; abicheck auto-detects JSON dumps by extension.", quiet)
    if filter_path:
        _do_echo(f"Note: -filter {filter_path} is accepted for compatibility (not yet applied).", quiet)
    if params_path:
        _do_echo(f"Note: -params {params_path} is accepted for compatibility (not yet applied).", quiet)
    if app_path:
        _do_echo(f"Note: -app {app_path} is accepted for compatibility (not yet applied).", quiet)
    if arch:
        _do_echo(f"Note: -arch {arch} is recorded for informational purposes.", quiet)
    if keep_cxx:
        _do_echo("Note: -keep-cxx is accepted; abicheck includes all exported symbols by default.", quiet)
    if keep_reserved:
        _do_echo("Note: -keep-reserved is accepted; abicheck reports all field changes by default.", quiet)
    if count_symbols:
        _do_echo(f"Note: -count-symbols {count_symbols} is accepted for compatibility (not yet applied).", quiet)
    if count_all_symbols:
        _do_echo(f"Note: -count-all-symbols {count_all_symbols} is accepted for compatibility (not yet applied).", quiet)

    # ── Resolve relpath overrides ────────────────────────────────────────
    old_relpath = relpath1 or relpath
    new_relpath = relpath2 or relpath

    # ── Parse descriptors (support both XML descriptors and JSON dumps) ──
    try:
        old_d = _load_descriptor_or_dump(old_desc, relpath=old_relpath)
        new_d = _load_descriptor_or_dump(new_desc, relpath=new_relpath)
    except (ValueError, FileNotFoundError, OSError) as exc:
        click.echo(f"Error parsing descriptor: {exc}", err=True)
        sys.exit(2)

    # ── Load skip-headers set ────────────────────────────────────────────
    _skip_headers_set = _load_skip_headers(skip_headers)
    if _skip_headers_set:
        _do_echo(f"Applying -skip-headers: excluding {len(_skip_headers_set)} header(s).", quiet)

    # Determine which inputs are dumps vs descriptors (handles mixed inputs)
    from .model import AbiSnapshot as _AbiSnapshot  # noqa: PLC0415

    def _snap_from_input(
        d: CompatDescriptor | _AbiSnapshot,
        vnum_override: str | None,
        desc_path: Path,
    ) -> tuple[_AbiSnapshot, str]:
        """Convert a descriptor or dump to (snapshot, version), honoring vnum override."""
        if isinstance(d, _AbiSnapshot):
            version = vnum_override or d.version
            if vnum_override:
                d = d.__class__(
                    library=d.library, version=vnum_override,
                    functions=d.functions, variables=d.variables,
                    types=d.types, elf=d.elf, dwarf=d.dwarf,
                    dwarf_advanced=d.dwarf_advanced,
                    enums=d.enums, typedefs=d.typedefs,
                )
            return d, version

        # It's a CompatDescriptor — dump it
        desc: CompatDescriptor = d
        if vnum_override:
            desc = desc.__class__(
                version=vnum_override, headers=desc.headers, libs=desc.libs, path=desc.path
            )
        so = desc.libs[0]
        if len(desc.libs) > 1:
            _do_echo(
                f"Warning: descriptor {desc_path.name} has {len(desc.libs)} <libs> entries; "
                f"using only the first: {so}",
                quiet,
            )
        hdrs = _resolve_headers_from_list(
            headers_list_path, single_header, desc.headers,
            skip_headers=_skip_headers_set or None,
        )
        if not so.exists():
            click.echo(f"Error: library not found: {so}", err=True)
            sys.exit(2)
        snap = dump(
            so, headers=hdrs, version=desc.version,
            gcc_path=gcc_path, gcc_prefix=gcc_prefix, gcc_options=gcc_options,
            sysroot=sysroot, nostdinc=nostdinc, lang=lang,
        )
        return snap, desc.version

    _logger = logging.getLogger("abicheck")
    try:
        # Activate log1 handler for old library analysis phase
        if _log1_handler is not None:
            _logger.addHandler(_log1_handler)
        old_snap, old_version = _snap_from_input(old_d, vnum1, old_desc)
        if _log1_handler is not None:
            _logger.removeHandler(_log1_handler)
            _log1_handler.close()

        # Activate log2 handler for new library analysis phase
        if _log2_handler is not None:
            _logger.addHandler(_log2_handler)
        new_snap, new_version = _snap_from_input(new_d, vnum2, new_desc)
        if _log2_handler is not None:
            _logger.removeHandler(_log2_handler)
            _log2_handler.close()
    except Exception as exc:  # noqa: BLE001
        # Clean up phase handlers on error
        if _log1_handler is not None:
            _log1_handler.close()
        if _log2_handler is not None:
            _log2_handler.close()
        click.echo(f"Error during dump: {exc}", err=True)
        sys.exit(2)

    if headers_only:
        _do_echo("Note: -headers-only is accepted — ELF/DWARF checks still run.", quiet)

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

    result = compare(old_snap, new_snap, suppression=suppression, policy="strict_abi")

    # ── Post-compare transforms ───────────────────────────────────────────

    # -warn-newsym: treat new symbols as breaks
    if warn_newsym:
        result = _apply_warn_newsym(result)

    # -limit-affected: cap reported changes per kind
    if limit_affected > 0:
        result = _limit_affected_changes(result, limit_affected)

    # Save post-processed result before source filtering for split reports.
    # -bin-report-path needs the full (non-source-filtered) result;
    # -src-report-path derives from this via _filter_source_only.
    full_result = result

    # -source: filter to source/API breaks only (for primary report).
    # -binary is the default mode and does NOT filter source-level changes
    # from the primary report (matching ABICC semantics). _filter_binary_only
    # is only used for -bin-report-path split reports.
    if source_only and not binary_only:
        result = _filter_source_only(result)

    # -strict: treat COMPATIBLE and API_BREAK as BREAKING.
    # Applied AFTER source filtering so that -source -strict --strict-mode api
    # promotes the already-filtered verdict, not the pre-filter one.
    if strict:
        result = _apply_strict(result, mode=strict_mode)

    verdict = result.verdict.value if hasattr(result.verdict, "value") else str(result.verdict)

    # Normalize format aliases: htm → html
    if fmt.lower() == "htm":
        fmt = "html"

    # ── Determine report output path ──────────────────────────────────────
    if report_path is None:
        ext = fmt.lower()
        report_path = (
            Path("compat_reports")
            / _safe_path(lib_name)
            / f"{_safe_path(old_version)}_to_{_safe_path(new_version)}"
            / f"compat_report.{ext}"
        )

    report_path.parent.mkdir(parents=True, exist_ok=True)

    # Build effective title
    effective_title = title
    if component and not effective_title:
        effective_title = f"ABI Compatibility Report — {lib_name} ({component})"

    # ── Compute old symbol count (shared by HTML and XML reports) ────────
    from .model import Visibility
    old_symbol_count = sum(
        1 for f in old_snap.functions
        if f.visibility in (Visibility.PUBLIC, Visibility.ELF_ONLY)
    ) + sum(
        1 for v in old_snap.variables
        if v.visibility in (Visibility.PUBLIC, Visibility.ELF_ONLY)
    )

    # ── Generate report ──────────────────────────────────────────────────
    def _generate_report(r: DiffResult, path: Path) -> None:
        if fmt == "html":
            write_html_report(
                r, output_path=path,
                lib_name=lib_name,
                old_version=old_version, new_version=new_version,
                old_symbol_count=old_symbol_count or None,
                title=effective_title,
                compat_html=compat_html,
            )
        elif fmt == "xml":
            write_xml_report(
                r, output_path=path,
                lib_name=lib_name,
                old_version=old_version, new_version=new_version,
                old_symbol_count=old_symbol_count or None,
                arch=arch or "",
                compiler=_detect_compiler_version(gcc_path),
            )
        elif fmt == "json":
            path.write_text(to_json(r), encoding="utf-8")
        else:
            path.write_text(to_markdown(r), encoding="utf-8")

    # Write primary report
    _generate_report(result, report_path)

    # -bin-report-path / -src-report-path: generate split reports
    if bin_report_path:
        bin_report_path.parent.mkdir(parents=True, exist_ok=True)
        bin_result = _filter_binary_only(full_result)
        _generate_report(bin_result, bin_report_path)
        _do_echo(f"Binary report: {bin_report_path}", quiet)

    if src_report_path:
        src_report_path.parent.mkdir(parents=True, exist_ok=True)
        src_result = _filter_source_only(full_result)
        _generate_report(src_result, src_report_path)
        _do_echo(f"Source report: {src_report_path}", quiet)

    # -list-affected: write affected symbols to separate file
    if list_affected:
        affected_path = report_path.with_suffix(".affected.txt")
        _write_affected_list(result, affected_path)
        _do_echo(f"Affected symbols: {affected_path}", quiet)

    if to_stdout:
        click.echo(report_path.read_text(encoding="utf-8"))

    # Compute BC% for console output (matches ABICC console format)
    from .report_summary import compatibility_metrics  # noqa: PLC0415
    metrics = compatibility_metrics(result.changes, old_symbol_count)
    breaking_count = metrics.breaking_count
    _bc_pct = metrics.binary_compatibility_pct

    _do_echo(f"Binary compatibility: {_bc_pct:.1f}%", quiet)
    _do_echo(f"Total binary compatibility problems: {breaking_count}, warnings: 0", quiet)
    _do_echo(f"Verdict: {verdict}", quiet)
    _do_echo(f"Report:  {report_path}", quiet)

    # Exit codes mirror ABICC:
    #   0 = NO_CHANGE or COMPATIBLE
    #   1 = BREAKING
    #   2 = API_BREAK (source-level break, binary compatible)
    if verdict == "BREAKING":
        sys.exit(1)
    if verdict == "API_BREAK":
        sys.exit(2)


def _load_descriptor_or_dump(path: Path, *, relpath: str | None = None) -> CompatDescriptor | AbiSnapshot:
    """Load either an ABICC XML descriptor or a JSON ABI dump.

    Returns:
        CompatDescriptor for XML descriptor files, AbiSnapshot for JSON dumps.

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
        return load_snapshot(path)

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
    return parse_descriptor(path, relpath=relpath)


if __name__ == "__main__":
    main()
