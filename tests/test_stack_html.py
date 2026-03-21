"""Tests for stack HTML report generator."""
from __future__ import annotations

from types import SimpleNamespace

from abicheck.stack_html import stack_to_html
from abicheck.stack_checker import StackCheckResult, StackVerdict


def _node(soname: str, depth: int = 0, path: str = "", reason: str = "") -> object:
    return SimpleNamespace(
        soname=soname, depth=depth, path=path or f"/lib/{soname}",
        needed=[], resolution_reason=reason or ("root" if depth == 0 else "DT_NEEDED"),
    )


def _graph(root: str = "/bin/app", nodes: dict | None = None) -> object:
    ns = nodes or {root: _node("app", 0, root)}
    return SimpleNamespace(
        root=root,
        nodes=ns,
        node_count=len(ns),
        edges=[],
        unresolved=[],
    )


def _binding(consumer: str, symbol: str, status: str, version: str = "", explanation: str = "") -> object:
    return SimpleNamespace(
        consumer=consumer, symbol=symbol, version=version,
        status=SimpleNamespace(value=status), explanation=explanation,
    )


def _stack_result(
    loadability: StackVerdict = StackVerdict.PASS,
    abi_risk: StackVerdict = StackVerdict.PASS,
    risk_score: str = "low",
    missing_symbols: list | None = None,
    stack_changes: list | None = None,
) -> StackCheckResult:
    return StackCheckResult(
        root_binary="/bin/myapp",
        baseline_env="/baseline",
        candidate_env="/candidate",
        loadability=loadability,
        abi_risk=abi_risk,
        baseline_graph=_graph(),
        candidate_graph=_graph(),
        bindings_baseline=[],
        bindings_candidate=[
            _binding("/bin/myapp", "main", "bound"),
        ],
        missing_symbols=missing_symbols or [],
        stack_changes=stack_changes or [],
        risk_score=risk_score,
    )


def test_html_is_valid_document() -> None:
    out = stack_to_html(_stack_result())
    assert out.startswith("<!DOCTYPE html>")
    assert "</html>" in out


def test_html_contains_root_binary() -> None:
    out = stack_to_html(_stack_result())
    assert "/bin/myapp" in out


def test_html_shows_pass_verdict() -> None:
    out = stack_to_html(_stack_result())
    assert "PASS" in out


def test_html_shows_fail_verdict() -> None:
    out = stack_to_html(_stack_result(loadability=StackVerdict.FAIL))
    assert "FAIL" in out


def test_html_shows_binding_summary() -> None:
    out = stack_to_html(_stack_result())
    assert "Symbol Binding Summary" in out
    assert "bound" in out


def test_html_shows_missing_symbols() -> None:
    missing = [_binding("/bin/myapp", "missing_func", "missing", explanation="not found")]
    out = stack_to_html(_stack_result(missing_symbols=missing))
    assert "Missing Symbols" in out
    assert "missing_func" in out


def test_html_shows_dependency_tree() -> None:
    out = stack_to_html(_stack_result())
    assert "Dependency Tree" in out


def test_html_shows_risk_score() -> None:
    out = stack_to_html(_stack_result(risk_score="high"))
    assert "HIGH" in out
