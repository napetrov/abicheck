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

"""JUnit XML output for abicheck.

Produces a JUnit XML report suitable for CI systems (GitLab CI, Jenkins,
Azure DevOps) that display ABI check results as "test results" in their
standard dashboards.

Usage::

    abicheck compare old.so new.so --format junit -o results.xml

Mapping rules:

- Each library in a ``compare-release`` is a ``<testsuite>``
- Each exported symbol/type that was checked is a ``<testcase>``
- ``classname`` groups: ``functions``, ``variables``, ``types``,
  ``enums``, ``metadata``
- Changes with verdict BREAKING or API_BREAK → ``<failure>``
- Changes with verdict COMPATIBLE_WITH_RISK → ``<failure>`` only when
  the change kind has severity ``"error"`` (currently none do by default)
- COMPATIBLE changes → pass (testcase exists with no ``<failure>`` child)
- ``type`` attribute: the verdict level (``BREAKING``, ``API_BREAK``,
  ``COMPATIBLE_WITH_RISK``)
- ``message`` attribute: ``change_kind: one-line summary``
- Body text: detailed explanation + source location if available
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

from .checker_types import Change, DiffResult
from .checker_policy import ChangeKind, Verdict, policy_for
from .reporter import apply_show_only

if TYPE_CHECKING:
    from .model import AbiSnapshot


# ---------------------------------------------------------------------------
# Classname mapping — groups symbols/types by element kind
# ---------------------------------------------------------------------------

_FUNC_KINDS = frozenset(k for k in ChangeKind if k.value.startswith("func_"))
_VAR_KINDS = frozenset(k for k in ChangeKind if k.value.startswith("var_"))
_TYPE_KINDS = frozenset(
    k for k in ChangeKind
    if k.value.startswith("type_") or k.value.startswith("union_")
)
_ENUM_KINDS = frozenset(k for k in ChangeKind if k.value.startswith("enum_"))


def _classname_for(change: Change) -> str:
    """Determine the JUnit classname group for a change."""
    if change.kind in _FUNC_KINDS:
        return "functions"
    if change.kind in _VAR_KINDS:
        return "variables"
    if change.kind in _TYPE_KINDS:
        return "types"
    if change.kind in _ENUM_KINDS:
        return "enums"
    return "metadata"


# ---------------------------------------------------------------------------
# Verdict → failure classification
# ---------------------------------------------------------------------------

def _is_failure(
    change: Change,
    breaking_set: frozenset[ChangeKind],
    api_break_set: frozenset[ChangeKind],
    risk_set: frozenset[ChangeKind],
) -> bool:
    """Return True if the change should be a JUnit ``<failure>``.

    BREAKING and API_BREAK changes always fail.  COMPATIBLE_WITH_RISK
    changes fail only when their per-kind severity is ``"error"``
    (currently all RISK_KINDS default to ``"warning"``, so they pass).
    """
    if change.kind in breaking_set or change.kind in api_break_set:
        return True
    if change.kind in risk_set:
        return policy_for(change.kind).severity == "error"
    # Kinds not in any explicit set (e.g. newly added ChangeKinds): consult
    # policy_for() which defaults to BREAKING/severity="error" for unknown
    # kinds, ensuring fail-closed behaviour.
    return policy_for(change.kind).severity == "error"


def _failure_type(
    change: Change,
    breaking_set: frozenset[ChangeKind],
    api_break_set: frozenset[ChangeKind],
    risk_set: frozenset[ChangeKind],
) -> str:
    """Return the ``type`` attribute for a ``<failure>`` element."""
    if change.kind in breaking_set:
        return "BREAKING"
    if change.kind in api_break_set:
        return "API_BREAK"
    if change.kind in risk_set:
        return "COMPATIBLE_WITH_RISK"
    return "COMPATIBLE"


# ---------------------------------------------------------------------------
# Single DiffResult → <testsuite>
# ---------------------------------------------------------------------------

def _build_testsuite(
    result: DiffResult,
    old_snapshot: AbiSnapshot | None = None,
    *,
    show_only: str | None = None,
) -> ET.Element:
    """Build a ``<testsuite>`` element from a single DiffResult.

    Each changed symbol becomes a ``<testcase>``.  If *old_snapshot* is
    provided, unchanged symbols are also emitted as passing test cases so
    that the pass-rate is meaningful.
    """
    breaking_set, api_break_set, _, risk_set = result._effective_kind_sets()

    changes = list(result.changes)
    if show_only:
        changes = apply_show_only(changes, show_only, policy=result.policy)

    # Build map: symbol → change (use first change per symbol for the testcase)
    change_by_symbol: dict[str, Change] = {}
    extra_changes: list[Change] = []
    for c in changes:
        if c.symbol not in change_by_symbol:
            change_by_symbol[c.symbol] = c
        else:
            extra_changes.append(c)

    # Collect all symbols (changed + unchanged) when snapshot is available
    all_symbols: dict[str, str] = {}  # symbol_name → classname
    if old_snapshot is not None:
        for f in old_snapshot.functions:
            all_symbols[f.mangled] = "functions"
        for v in old_snapshot.variables:
            all_symbols[v.mangled] = "variables"
        for t in old_snapshot.types:
            all_symbols[t.name] = "types"
        for e in old_snapshot.enums:
            all_symbols[e.name] = "enums"

    # Add changed symbols that might not be in old_snapshot (e.g. additions)
    for sym, c in change_by_symbol.items():
        if sym not in all_symbols:
            all_symbols[sym] = _classname_for(c)

    # Count failures — a symbol counts as failing if ANY of its changes fail
    # (not just the first one stored in change_by_symbol).
    symbols_with_failure: set[str] = set()
    for c in changes:
        if _is_failure(c, breaking_set, api_break_set, risk_set):
            symbols_with_failure.add(c.symbol)
    failure_count = len(symbols_with_failure)

    total = len(all_symbols) if all_symbols else len(change_by_symbol)

    ts = ET.Element("testsuite")
    ts.set("name", result.library)
    ts.set("tests", str(total))
    ts.set("failures", str(failure_count))
    ts.set("errors", "0")

    # Emit test cases for every symbol
    if all_symbols:
        for sym, classname in sorted(all_symbols.items()):
            tc = ET.SubElement(ts, "testcase")
            tc.set("name", sym)
            tc.set("classname", classname)
            if sym in change_by_symbol:
                _maybe_add_failure(
                    tc, change_by_symbol[sym],
                    breaking_set, api_break_set, risk_set,
                )
    else:
        # No snapshot — only emit changed symbols
        for sym, c in sorted(change_by_symbol.items()):
            tc = ET.SubElement(ts, "testcase")
            tc.set("name", sym)
            tc.set("classname", _classname_for(c))
            _maybe_add_failure(tc, c, breaking_set, api_break_set, risk_set)

    # Additional changes for symbols that already have a testcase
    # (e.g. multiple changes to the same symbol) — append as extra failures
    for c in extra_changes:
        if _is_failure(c, breaking_set, api_break_set, risk_set):
            # Find the existing testcase for this symbol
            for tc in ts:
                if tc.get("name") == c.symbol:
                    _add_failure(tc, c, breaking_set, api_break_set, risk_set)
                    break

    return ts


def _maybe_add_failure(
    tc: ET.Element,
    change: Change,
    breaking_set: frozenset[ChangeKind],
    api_break_set: frozenset[ChangeKind],
    risk_set: frozenset[ChangeKind],
) -> None:
    """Add a ``<failure>`` child to *tc* if the change is a failure."""
    if _is_failure(change, breaking_set, api_break_set, risk_set):
        _add_failure(tc, change, breaking_set, api_break_set, risk_set)


def _add_failure(
    tc: ET.Element,
    change: Change,
    breaking_set: frozenset[ChangeKind],
    api_break_set: frozenset[ChangeKind],
    risk_set: frozenset[ChangeKind],
) -> None:
    """Append a ``<failure>`` element to testcase *tc*."""
    ftype = _failure_type(change, breaking_set, api_break_set, risk_set)
    description = change.description or change.kind.value.replace("_", " ")
    message = f"{change.kind.value}: {description}"

    fail = ET.SubElement(tc, "failure")
    fail.set("message", message)
    fail.set("type", ftype)

    # Body text: detailed explanation + source location
    body_parts = [description]
    if change.old_value is not None or change.new_value is not None:
        old = change.old_value if change.old_value is not None else "?"
        new = change.new_value if change.new_value is not None else "?"
        body_parts.append(f"({old} \u2192 {new})")
    if change.source_location:
        body_parts.append(f"Source: {change.source_location}")
    fail.text = "\n".join(body_parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def to_junit_xml(
    result: DiffResult,
    old_snapshot: AbiSnapshot | None = None,
    *,
    show_only: str | None = None,
) -> str:
    """Convert a single DiffResult to a JUnit XML string.

    Parameters
    ----------
    result:
        The comparison result.
    old_snapshot:
        When provided, all symbols from the old snapshot appear as test
        cases (unchanged symbols pass).  Without it, only changed symbols
        appear.
    show_only:
        Optional ``--show-only`` filter string.

    Returns
    -------
    str
        JUnit XML document as a string.
    """
    root = ET.Element("testsuites")
    root.set("name", "abicheck")

    ts = _build_testsuite(result, old_snapshot, show_only=show_only)
    root.append(ts)

    # Roll up counts
    root.set("tests", ts.get("tests", "0"))
    root.set("failures", ts.get("failures", "0"))
    root.set("errors", "0")

    return _to_xml_string(root)


def to_junit_xml_multi(
    results: list[tuple[DiffResult, AbiSnapshot | None]],
    *,
    show_only: str | None = None,
) -> str:
    """Convert multiple DiffResults to a JUnit XML string (compare-release).

    Each ``(DiffResult, old_snapshot)`` pair becomes a ``<testsuite>``.
    """
    root = ET.Element("testsuites")
    root.set("name", "abicheck")

    total_tests = 0
    total_failures = 0

    for result, old_snap in results:
        ts = _build_testsuite(result, old_snap, show_only=show_only)
        root.append(ts)
        total_tests += int(ts.get("tests", "0"))
        total_failures += int(ts.get("failures", "0"))

    root.set("tests", str(total_tests))
    root.set("failures", str(total_failures))
    root.set("errors", "0")

    return _to_xml_string(root)


def _to_xml_string(root: ET.Element) -> str:
    """Serialize an ElementTree element to an XML string with declaration."""
    ET.indent(root)
    tree = ET.ElementTree(root)
    buf = io.BytesIO()
    tree.write(buf, encoding="UTF-8", xml_declaration=True)
    return buf.getvalue().decode("UTF-8")
