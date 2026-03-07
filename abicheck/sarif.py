"""SARIF 2.1.0 output for abicheck.

Produces a Static Analysis Results Interchange Format (SARIF) document
suitable for upload to GitHub Code Scanning via:

    abicheck compare old.so new.so --format sarif > results.sarif

GitHub Code Scanning docs:
  https://docs.github.com/en/code-security/code-scanning/integrating-with-code-scanning/sarif-support-for-code-scanning

SARIF spec: https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html
"""
from __future__ import annotations

import json
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Any

from abicheck.checker import Change, ChangeKind, DiffResult, Verdict

# ---------------------------------------------------------------------------
# Severity mapping
# ---------------------------------------------------------------------------
_BREAKING_SEVERITY = "error"
_COMPATIBLE_SEVERITY = "warning"
_NOTE_SEVERITY = "note"

# ChangeKinds that are purely informational (compatible additions)
_COMPATIBLE_KINDS: frozenset[ChangeKind] = frozenset(
    {
        ChangeKind.FUNC_ADDED,
        ChangeKind.VAR_ADDED,
        ChangeKind.SYMBOL_BINDING_STRENGTHENED,
        ChangeKind.ENUM_MEMBER_ADDED,
    }
)

# Rule ID = change_kind value (snake_case, already stable)


def _tool_version() -> str:
    try:
        return _pkg_version("abicheck")
    except Exception:  # noqa: BLE001
        return "unknown"


def _severity(change: Change) -> str:
    if change.kind in _COMPATIBLE_KINDS:
        return _COMPATIBLE_SEVERITY
    return _BREAKING_SEVERITY


def _rule_for(kind: ChangeKind) -> dict[str, Any]:
    """Produce a SARIF reportingDescriptor for a ChangeKind."""
    rule_id = kind.value
    severity = _BREAKING_SEVERITY if kind not in _COMPATIBLE_KINDS else _COMPATIBLE_SEVERITY
    help_uri = (
        "https://github.com/napetrov/abicheck/blob/main/docs/libabigail_parity.md"
    )
    return {
        "id": rule_id,
        "name": "".join(w.capitalize() for w in rule_id.split("_")),
        "shortDescription": {"text": rule_id.replace("_", " ").capitalize()},
        "fullDescription": {"text": f"ABI change detected: {rule_id.replace('_', ' ')}"},
        "helpUri": help_uri,
        "defaultConfiguration": {"level": severity},
        "properties": {"tags": ["abi", "binary-compatibility"]},
    }


def _result_for(change: Change, library: str, old_version: str, new_version: str) -> dict[str, Any]:
    """Produce a SARIF result object for a Change."""
    msg_parts = [change.description]
    if change.old_value or change.new_value:
        msg_parts.append(
            f"({change.old_value or '?'} → {change.new_value or '?'})"
        )

    return {
        "ruleId": change.kind.value,
        "level": _severity(change),
        "message": {
            "text": " ".join(msg_parts),
        },
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": {
                        "uri": library,
                        "uriBaseId": "%SRCROOT%",
                    },
                },
                "logicalLocations": [
                    {
                        "name": change.symbol,
                        "kind": "member",
                    }
                ],
            }
        ],
        "properties": {
            "symbol": change.symbol,
            "oldVersion": old_version,
            "newVersion": new_version,
        },
    }


def to_sarif(result: DiffResult) -> dict[str, Any]:
    """Convert a DiffResult to a SARIF 2.1.0 document (dict)."""
    tool_version = _tool_version()

    # Collect unique rules used
    rules_seen: dict[str, dict[str, Any]] = {}
    sarif_results: list[dict[str, Any]] = []

    for change in result.changes:
        rule_id = change.kind.value
        if rule_id not in rules_seen:
            rules_seen[rule_id] = _rule_for(change.kind)
        sarif_results.append(
            _result_for(change, result.library, result.old_version, result.new_version)
        )

    # Overall ABI verdict as a notification
    invocation_success = result.verdict != Verdict.BREAKING

    return {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "abicheck",
                        "version": tool_version,
                        "informationUri": "https://github.com/napetrov/abicheck",
                        "rules": list(rules_seen.values()),
                    }
                },
                "invocations": [
                    {
                        "executionSuccessful": invocation_success,
                        "exitCode": 0 if result.verdict == Verdict.NO_CHANGE else (
                            1 if result.verdict == Verdict.BREAKING else 0
                        ),
                        "exitCodeDescription": result.verdict.value,
                    }
                ],
                "results": sarif_results,
                "automationDetails": {
                    "id": f"abicheck/{result.library}/{result.old_version}_to_{result.new_version}",
                    "description": {
                        "text": (
                            f"ABI comparison: {result.library} "
                            f"{result.old_version} → {result.new_version} "
                            f"verdict={result.verdict.value}"
                        )
                    },
                },
                "properties": {
                    "abiVerdict": result.verdict.value,
                    "oldVersion": result.old_version,
                    "newVersion": result.new_version,
                    "library": result.library,
                    "changeCount": len(result.changes),
                    "suppressedCount": result.suppressed_count,
                },
            }
        ],
    }


def to_sarif_str(result: DiffResult, indent: int = 2) -> str:
    """Serialize DiffResult to a SARIF JSON string."""
    return json.dumps(to_sarif(result), indent=indent)


def write_sarif(result: DiffResult, path: Path) -> None:
    """Write SARIF output to *path*."""
    path.write_text(to_sarif_str(result), encoding="utf-8")
