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

"""MCP (Model Context Protocol) server for abicheck.

Exposes abicheck functionality as MCP tools so that AI agents (Claude Code,
Cursor, OpenAI Agents, etc.) can discover and invoke ABI checking operations
with structured inputs and outputs.

Run as:
    abicheck-mcp          # stdio transport (default)
    python -m abicheck.mcp_server
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as _exc:
    _msg = (
        "MCP support requires the 'mcp' package. "
        "Install it with: pip install abicheck[mcp]"
    )
    raise ImportError(_msg) from _exc

from .checker import DiffResult, compare
from .checker_policy import (
    API_BREAK_KINDS,
    BREAKING_KINDS,
    COMPATIBLE_KINDS,
    RISK_KINDS,
    VALID_BASE_POLICIES,
    ChangeKind,
    Verdict,
    impact_for,
    policy_for,
    policy_kind_sets,
)
from .errors import AbicheckError
from .model import AbiSnapshot, Visibility
from .reporter import to_json, to_markdown
from .serialization import load_snapshot, snapshot_to_json

_logger = logging.getLogger("abicheck.mcp")

# ---------------------------------------------------------------------------
# Path safety helpers
# ---------------------------------------------------------------------------

# Allowed extensions for output files written by abi_dump
_ALLOWED_OUTPUT_SUFFIXES = frozenset({".json"})

# Allowed extensions for input binary files
_ALLOWED_BINARY_SUFFIXES = frozenset({".so", ".dll", ".dylib", ".json", ".dump", ""})


def _safe_read_path(raw: str, *, label: str = "path") -> Path:
    """Resolve and validate a path for reading.

    - Resolves symlinks and `..` components.
    - Does NOT restrict to a specific directory (read paths are user-specified).
    - Returns the resolved Path.

    Raises ValueError with a generic message on obviously bad input.
    """
    if not raw or raw.strip() == "":
        raise ValueError(f"Empty {label} is not allowed")
    try:
        return Path(raw).resolve()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {label}: {exc!s}") from exc


def _safe_write_path(raw: str, *, label: str = "output_path") -> Path:
    """Resolve and validate a path for writing.

    Enforces:
    - Must have an allowed suffix (.json only)
    - Must not be a system-sensitive location

    Raises ValueError on policy violation.
    """
    if not raw or raw.strip() == "":
        raise ValueError(f"Empty {label} is not allowed")
    try:
        p = Path(raw).resolve()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {label}: {exc!s}") from exc

    if p.suffix.lower() not in _ALLOWED_OUTPUT_SUFFIXES:
        raise ValueError(
            f"{label} must have a .json extension, got: {p.suffix!r}"
        )

    # Block writes to sensitive system locations
    sensitive_prefixes = (
        "/etc/", "/bin/", "/sbin/", "/usr/bin/", "/usr/sbin/",
        "/boot/", "/sys/", "/proc/",
    )
    p_str = str(p)
    for prefix in sensitive_prefixes:
        if p_str.startswith(prefix):
            raise ValueError(
                f"{label} points to a sensitive system path: {prefix}..."
            )

    # Block writes to SSH/credential directories
    home = Path.home()
    for sensitive_dir in [home / ".ssh", home / ".aws", home / ".gnupg"]:
        try:
            p.relative_to(sensitive_dir)
            raise ValueError(
                f"{label} points to a sensitive credential directory"
            )
        except ValueError as e:
            if "credential" in str(e):
                raise

    return p


def _sanitize_error(exc: Exception, *, context: str = "operation") -> str:
    """Return a safe error message that does not leak filesystem paths or internals."""
    # Known domain errors: safe to surface as-is
    from .errors import AbicheckError
    if isinstance(exc, AbicheckError):
        return str(exc)
    if isinstance(exc, (ValueError, KeyError)):
        return str(exc)
    # OS/IO errors: return generic message, log details internally
    if isinstance(exc, (OSError, FileNotFoundError, PermissionError)):
        _logger.debug("OS error in %s: %s", context, exc, exc_info=True)
        return f"{context} failed: file system error (check logs for details)"
    # All others: generic
    _logger.debug("Unexpected error in %s: %s", context, exc, exc_info=True)
    return f"{context} failed: unexpected error"


mcp = FastMCP(
    "abicheck",
    instructions=(
        "ABI compatibility checker for C/C++ shared libraries. "
        "Detects breaking changes in .so/.dll/.dylib files before they reach production. "
        "Use abi_compare to diff two library versions, abi_dump to extract ABI snapshots, "
        "abi_list_changes to browse change kinds, and abi_explain_change for detailed explanations."
    ),
)


# ---------------------------------------------------------------------------
# Helpers — reuse CLI logic without Click dependency
# ---------------------------------------------------------------------------

# Mach-O magic bytes (fat/BE32/LE32/BE64/LE64)
_MACHO_MAGICS = frozenset({
    b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",
})


def _detect_binary_format(path: Path) -> str | None:
    """Detect binary format from magic bytes — single file open."""
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
    except OSError:
        return None
    if magic == b"\x7fELF":
        return "elf"
    if magic[:2] == b"MZ":
        return "pe"
    if magic in _MACHO_MAGICS:
        return "macho"
    return None


def _resolve_input(
    path: Path,
    headers: list[Path],
    includes: list[Path],
    version: str,
    lang: str,
) -> AbiSnapshot:
    """Auto-detect input type and return an AbiSnapshot.

    Mirrors cli._resolve_input but without Click exceptions.
    """
    binary_fmt = _detect_binary_format(path)

    if binary_fmt == "elf":
        from .dumper import dump
        compiler = "c++" if lang == "c++" else "cc"
        return dump(
            so_path=path,
            headers=headers,
            extra_includes=includes,
            version=version,
            compiler=compiler,
            lang=lang if lang == "c" else None,
        )

    if binary_fmt == "pe":
        from .model import Function
        from .pe_metadata import parse_pe_metadata
        pe_meta = parse_pe_metadata(path)
        if not pe_meta.machine:
            raise AbicheckError(
                f"Failed to extract PE metadata from '{path}'. "
                "The file may be corrupt or not a valid PE binary."
            )
        if not pe_meta.exports:
            raise AbicheckError(
                f"PE file '{path}' has no exports (named or ordinal). "
                "Verify the file is a valid DLL."
            )
        funcs = [
            Function(
                name=(exp.name or f"ordinal:{exp.ordinal}"),
                mangled=(exp.name or f"ordinal:{exp.ordinal}"),
                return_type="?",
                visibility=Visibility.PUBLIC,
                is_extern_c=not (exp.name or "").startswith("?"),
            )
            for exp in pe_meta.exports
        ]
        return AbiSnapshot(
            library=path.name, version=version,
            functions=funcs, pe=pe_meta, platform="pe",
        )

    if binary_fmt == "macho":
        from .macho_metadata import parse_macho_metadata
        from .model import Function
        macho_meta = parse_macho_metadata(path)
        if not macho_meta.exports and not macho_meta.install_name and not macho_meta.dependent_libs:
            raise AbicheckError(
                f"Mach-O file '{path}' has no exports or load-command metadata. "
                "Verify the file is a valid dynamic library."
            )
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
            functions=funcs, macho=macho_meta, platform="macho",
        )

    # Text-based: JSON snapshot or Perl dump
    try:
        with open(path, "rb") as f:
            head = f.read(256).decode("utf-8", errors="replace").lstrip()
    except OSError as exc:
        raise AbicheckError(f"Cannot read '{path}': {exc}") from exc

    from .compat.abicc_dump_import import import_abicc_perl_dump, looks_like_perl_dump
    if looks_like_perl_dump(head):
        return import_abicc_perl_dump(path)

    if head.startswith("{"):
        return load_snapshot(path)

    raise AbicheckError(
        f"Cannot detect format of '{path}'. "
        "Expected: ELF (.so), PE (.dll), Mach-O (.dylib), JSON snapshot, or ABICC Perl dump."
    )


def _snapshot_summary(snap: AbiSnapshot) -> dict[str, Any]:
    """Build a compact summary of an ABI snapshot."""
    return {
        "library": snap.library,
        "version": snap.version,
        "platform": snap.platform,
        "functions": len(snap.functions),
        "variables": len(snap.variables),
        "types": len(snap.types),
        "enums": len(snap.enums),
    }


_VALID_FORMATS = frozenset({"json", "sarif", "html", "markdown"})


def _render_output(
    fmt: str, result: DiffResult, old: AbiSnapshot, new: AbiSnapshot,
) -> str:
    """Render comparison result in the requested output format."""
    if fmt not in _VALID_FORMATS:
        msg = f"Unknown output format {fmt!r}. Valid formats: {sorted(_VALID_FORMATS)}"
        raise ValueError(msg)
    if fmt == "json":
        return to_json(result)
    if fmt == "sarif":
        from .sarif import to_sarif_str
        return to_sarif_str(result)
    if fmt == "html":
        from .html_report import generate_html_report
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
            new_version=new.version,
            old_symbol_count=old_symbol_count or None,
        )
    return to_markdown(result)



def _impact_category(kind: ChangeKind, policy: str = "strict_abi") -> str:
    """Return the impact category string for a ChangeKind under the given policy.

    When *policy* is not ``strict_abi``, some kinds may be downgraded
    (e.g. ``sdk_vendor`` downgrades source-level renames from ``api_break``
    to ``compatible``).  This ensures per-change impact labels agree with
    the policy-aware verdict.
    """
    breaking, api_break, compatible, risk = policy_kind_sets(policy)
    if kind in breaking:
        return "breaking"
    if kind in api_break:
        return "api_break"
    if kind in risk:
        return "risk"
    if kind in compatible:
        return "compatible"
    _logger.warning("_impact_category: unknown ChangeKind %r, defaulting to breaking", kind)
    return "breaking"  # fail-safe for unknown kinds


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def abi_dump(
    library_path: str,
    headers: list[str] | None = None,
    include_dirs: list[str] | None = None,
    version: str = "unknown",
    language: str = "c++",
    output_path: str | None = None,
) -> str:
    """Dump ABI snapshot of a C/C++ shared library to JSON.

    Extracts the public ABI surface (functions, variables, types, enums)
    from a shared library binary and its public headers.

    Args:
        library_path: Path to .so, .dll, or .dylib file.
        headers: Public header file paths. Required for ELF (.so) — omitting them
            produces a symbol-only snapshot with no type information. Not used for
            PE (.dll) or Mach-O (.dylib) inputs.
        include_dirs: Extra include directories for the C/C++ parser.
        version: Version label to embed in the snapshot (e.g. "1.2.3").
        language: Language mode — "c++" (default) or "c".
        output_path: If provided, write snapshot to this file and return the path.
            Otherwise the snapshot JSON is returned inline.
    """
    try:
        lib = _safe_read_path(library_path, label="library_path")
        if not lib.exists():
            return json.dumps({"status": "error", "error": "Library file not found"})

        hdr_paths = [_safe_read_path(h, label="header") for h in (headers or [])]
        inc_paths = [_safe_read_path(d, label="include_dir") for d in (include_dirs or [])]

        snap = _resolve_input(lib, hdr_paths, inc_paths, version, language)
        snap_json = snapshot_to_json(snap)

        if output_path:
            out = _safe_write_path(output_path, label="output_path")
            out.write_text(snap_json, encoding="utf-8")
            return json.dumps({
                "status": "ok",
                "output_path": str(out),
                "summary": _snapshot_summary(snap),
            })

        return json.dumps({
            "status": "ok",
            "summary": _snapshot_summary(snap),
            "snapshot": json.loads(snap_json),
        })
    except Exception as exc:
        _logger.exception("abi_dump failed")
        return json.dumps({"status": "error", "error": _sanitize_error(exc, context="abi_dump")})


@mcp.tool()
def abi_compare(
    old_input: str,
    new_input: str,
    old_headers: list[str] | None = None,
    new_headers: list[str] | None = None,
    headers: list[str] | None = None,
    include_dirs: list[str] | None = None,
    language: str = "c++",
    policy: str = "strict_abi",
    policy_file: str | None = None,
    suppression_file: str | None = None,
    output_format: str = "json",
) -> str:
    """Compare two ABI surfaces and report breaking changes.

    Each input can be a shared library (.so/.dll/.dylib), a JSON snapshot
    from abi_dump, or an ABICC Perl dump (.pl). The format is auto-detected.

    Returns a structured JSON result with verdict, change summary, and the
    full list of changes. The verdict indicates binary ABI compatibility:
    - NO_CHANGE: identical ABI
    - COMPATIBLE: only additions (backward compatible)
    - COMPATIBLE_WITH_RISK: binary-compatible but deployment risk present
    - API_BREAK: source-level break (recompilation needed)
    - BREAKING: binary ABI break (old binaries will crash)

    Args:
        old_input: Path to old library (.so/.dll/.dylib) or JSON snapshot.
        new_input: Path to new library (.so/.dll/.dylib) or JSON snapshot.
        old_headers: Header files for old side (required if old is ELF binary).
        new_headers: Header files for new side (required if new is ELF binary).
        headers: Header files for both sides (shorthand; overridden by old_headers/new_headers).
        include_dirs: Include directories for the C/C++ parser.
        language: Language mode — "c++" (default) or "c".
        policy: Built-in policy: "strict_abi" (default), "sdk_vendor", or "plugin_abi".
        policy_file: Path to custom YAML policy file (overrides policy parameter).
        suppression_file: Path to YAML suppression file to filter known changes.
        output_format: Output format for the rendered report: "json" (default), "markdown", "sarif", "html".
    """
    try:
        old_path = _safe_read_path(old_input, label="old_input")
        new_path = _safe_read_path(new_input, label="new_input")
        for p, label in [(old_path, "old_input"), (new_path, "new_input")]:
            if not p.exists():
                return json.dumps({"status": "error", "error": f"File not found for {label}"})

        # Validate policy name
        if policy not in VALID_BASE_POLICIES:
            return json.dumps({
                "error": f"Unknown policy: {policy!r}. "
                f"Valid policies: {', '.join(sorted(VALID_BASE_POLICIES))}"
            })

        # Resolve per-side headers
        shared = [_safe_read_path(h, label="header") for h in (headers or [])]
        old_h = [_safe_read_path(h, label="old_header") for h in old_headers] if old_headers is not None else shared
        new_h = [_safe_read_path(h, label="new_header") for h in new_headers] if new_headers is not None else shared
        inc = [_safe_read_path(d, label="include_dir") for d in (include_dirs or [])]

        old_snap = _resolve_input(old_path, old_h, inc, "old", language)
        new_snap = _resolve_input(new_path, new_h, inc, "new", language)

        # Load suppression
        suppression = None
        if suppression_file:
            from .suppression import SuppressionList
            suppression = SuppressionList.load(_safe_read_path(suppression_file, label="suppression_file"))

        # Load policy file
        pf = None
        if policy_file:
            from .policy_file import PolicyFile
            pf = PolicyFile.load(_safe_read_path(policy_file, label="policy_file"))

        # Validate output_format early (before expensive compare)
        if output_format not in _VALID_FORMATS:
            return json.dumps({"status": "error", "error": f"Unknown output format {output_format!r}. Valid: {sorted(_VALID_FORMATS)}"})

        result = compare(old_snap, new_snap, suppression=suppression, policy=policy, policy_file=pf)

        # Use the active policy from the result (may differ from input when
        # policy_file overrides the base policy).
        active_policy = result.policy

        # Determine exit code (matches CLI semantics)
        exit_code = 0
        if result.verdict == Verdict.BREAKING:
            exit_code = 4
        elif result.verdict == Verdict.API_BREAK:
            exit_code = 2

        # Build structured response
        response: dict[str, Any] = {
            "status": "ok",
            "verdict": result.verdict.value,
            "exit_code": exit_code,
            "summary": {
                "breaking": len(result.breaking),
                "api_breaks": len(result.source_breaks),
                "risk_changes": len(result.risk),
                "compatible": len(result.compatible),
                "total_changes": len(result.changes),
            },
            "changes": [
                {
                    "kind": c.kind.value,
                    "symbol": c.symbol,
                    "description": c.description,
                    "impact": _impact_category(c.kind, active_policy),
                    "old_value": c.old_value,
                    "new_value": c.new_value,
                    "source_location": c.source_location,
                }
                for c in result.changes
            ],
            "suppressed_count": result.suppressed_count,
        }

        # Include rendered report
        rendered = _render_output(output_format, result, old_snap, new_snap)
        # When format is json, embed as nested object (not double-encoded string)
        if output_format == "json":
            response["report"] = json.loads(rendered)
        else:
            response["report"] = rendered

        return json.dumps(response)
    except Exception as exc:
        _logger.exception("abi_compare failed")
        return json.dumps({"status": "error", "error": _sanitize_error(exc, context="abi_compare")})


@mcp.tool()
def abi_list_changes(
    impact: str | None = None,
) -> str:
    """List all ABI change kinds that abicheck can detect.

    Returns an array of change kinds with their impact classification
    and description. Use this to understand what types of ABI breaks
    abicheck detects and how they are classified.

    Args:
        impact: Filter by impact level. One of: "breaking", "api_break",
            "risk", "compatible". If omitted, returns all change kinds.
    """
    filter_set: set[ChangeKind] | None = None
    if impact == "breaking":
        filter_set = BREAKING_KINDS
    elif impact == "api_break":
        filter_set = API_BREAK_KINDS
    elif impact == "risk":
        filter_set = set(RISK_KINDS)
    elif impact == "compatible":
        filter_set = COMPATIBLE_KINDS
    elif impact is not None:
        return json.dumps({
            "status": "error",
            "error": f"Unknown impact filter: {impact!r}. "
            "Use one of: breaking, api_break, risk, compatible"
        })

    results = []
    for kind in sorted(ChangeKind, key=lambda k: k.value):
        if filter_set is not None and kind not in filter_set:
            continue
        entry = policy_for(kind)
        results.append({
            "kind": kind.value,
            "impact": _impact_category(kind),
            "default_verdict": entry.default_verdict.value,
            "description": impact_for(kind),
        })

    return json.dumps({"count": len(results), "change_kinds": results})


@mcp.tool()
def abi_explain_change(
    change_kind: str,
) -> str:
    """Get a detailed explanation of a specific ABI change kind.

    Returns what the change means, why it's dangerous, and what
    impact it has on binary compatibility. Use this after abi_compare
    returns changes to understand and explain each finding.

    Args:
        change_kind: The change kind to explain (e.g. "func_removed",
            "type_size_changed"). Use abi_list_changes to see all available kinds.
    """
    # Look up the ChangeKind enum member
    try:
        kind = ChangeKind(change_kind)
    except ValueError:
        # Try case-insensitive lookup
        for k in ChangeKind:
            if k.value.lower() == change_kind.lower():
                kind = k
                break
        else:
            return json.dumps({
                "status": "error",
                "error": f"Unknown change kind: {change_kind!r}. "
                "Use abi_list_changes to see all available kinds."
            })

    entry = policy_for(kind)
    impact_text = impact_for(kind)
    category = _impact_category(kind)

    result: dict[str, Any] = {
        "kind": kind.value,
        "impact": category,
        "default_verdict": entry.default_verdict.value,
        "severity": entry.severity,
        "description": impact_text,
    }

    # Add fix guidance based on impact category
    if category == "breaking":
        result["fix_guidance"] = (
            "This is a binary ABI break. Old binaries compiled against the previous "
            "version will malfunction (crash, corrupt data, or fail to load). "
            "Options: (1) revert the change, (2) bump the SONAME/major version, "
            "(3) add the old symbol as a compatibility alias."
        )
    elif category == "api_break":
        result["fix_guidance"] = (
            "This is a source-level API break. Existing binaries may still work, "
            "but code compiled against the old headers will fail to build. "
            "Options: (1) revert the change, (2) provide a compatibility typedef/alias, "
            "(3) document the migration path."
        )
    elif category == "risk":
        result["fix_guidance"] = (
            "This change is binary-compatible but introduces deployment risk. "
            "Verify that your target environments satisfy the new requirements "
            "(e.g. minimum glibc version)."
        )
    else:
        result["fix_guidance"] = (
            "This change is backward-compatible. No action required."
        )

    return json.dumps(result)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the abicheck MCP server (stdio transport)."""
    # Redirect logging to stderr to avoid corrupting stdio JSON-RPC
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(name)s: %(message)s"))
    logging.getLogger("abicheck").addHandler(handler)
    logging.getLogger("abicheck").setLevel(logging.WARNING)

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
