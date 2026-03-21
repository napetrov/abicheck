"""Tests for stack HTML report generator."""
from __future__ import annotations

from types import SimpleNamespace

from abicheck.stack_checker import StackCheckResult, StackVerdict
from abicheck.stack_html import stack_to_html


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


def test_html_shows_warn_verdict() -> None:
    out = stack_to_html(_stack_result(abi_risk=StackVerdict.WARN))
    assert "WARN" in out


def test_html_shows_unresolved_libraries() -> None:
    graph = _graph()
    graph.unresolved = [("/bin/myapp", "libmissing.so.1")]
    r = _stack_result()
    r = StackCheckResult(
        root_binary="/bin/myapp",
        baseline_env="/baseline",
        candidate_env="/candidate",
        loadability=StackVerdict.FAIL,
        abi_risk=StackVerdict.PASS,
        baseline_graph=_graph(),
        candidate_graph=graph,
        bindings_baseline=[],
        bindings_candidate=[],
        missing_symbols=[],
        stack_changes=[],
        risk_score="high",
    )
    out = stack_to_html(r)
    assert "Unresolved Libraries" in out
    assert "libmissing.so.1" in out
    assert "NOT FOUND" in out


def test_html_shows_stack_changes_removed() -> None:
    sc = SimpleNamespace(library="libold.so", change_type="removed", abi_diff=None)
    out = stack_to_html(_stack_result(stack_changes=[sc]))
    assert "Stack Changes" in out
    assert "libold.so" in out
    assert "Removed from candidate" in out


def test_html_shows_stack_changes_added() -> None:
    sc = SimpleNamespace(library="libnew.so", change_type="added", abi_diff=None)
    out = stack_to_html(_stack_result(stack_changes=[sc]))
    assert "libnew.so" in out
    assert "New in candidate" in out


def test_html_shows_stack_changes_content_changed() -> None:
    from abicheck.checker import Verdict

    abi_diff = SimpleNamespace(
        verdict=Verdict.BREAKING,
        breaking=[SimpleNamespace(kind=SimpleNamespace(value="func_removed"), description="foo removed")],
        changes=[SimpleNamespace()],
    )
    sc = SimpleNamespace(library="libchanged.so", change_type="content_changed", abi_diff=abi_diff)
    out = stack_to_html(_stack_result(stack_changes=[sc]))
    assert "libchanged.so" in out
    assert "BREAKING" in out
    assert "Content changed" in out


def test_html_shows_environments() -> None:
    out = stack_to_html(_stack_result())
    assert "/baseline" in out
    assert "/candidate" in out


def test_html_tree_with_edges() -> None:
    """Tree rendering with parent-child edges."""
    root_key = "/bin/app"
    child_key = "/lib/libfoo.so"
    nodes = {
        root_key: _node("app", 0, root_key),
        child_key: _node("libfoo.so", 1, child_key, "DT_NEEDED"),
    }
    graph = SimpleNamespace(
        root=root_key,
        nodes=nodes,
        node_count=2,
        edges=[(root_key, child_key)],
        unresolved=[],
    )
    r = StackCheckResult(
        root_binary="/bin/myapp",
        baseline_env="/baseline",
        candidate_env="/candidate",
        loadability=StackVerdict.PASS,
        abi_risk=StackVerdict.PASS,
        baseline_graph=_graph(),
        candidate_graph=graph,
        bindings_baseline=[],
        bindings_candidate=[],
        missing_symbols=[],
        stack_changes=[],
        risk_score="low",
    )
    out = stack_to_html(r)
    assert "libfoo.so" in out
    assert "DT_NEEDED" in out


def test_html_tree_node_with_none_reason() -> None:
    """Node with depth > 0 but None resolution_reason should not show (None)."""
    root_key = "/bin/app"
    child_key = "/lib/libfoo.so"
    nodes = {
        root_key: _node("app", 0, root_key),
        child_key: SimpleNamespace(
            soname="libfoo.so", depth=1, path=child_key,
            needed=[], resolution_reason=None,
        ),
    }
    graph = SimpleNamespace(
        root=root_key, nodes=nodes, node_count=2,
        edges=[(root_key, child_key)], unresolved=[],
    )
    r = StackCheckResult(
        root_binary="/bin/myapp",
        baseline_env="/baseline", candidate_env="/candidate",
        loadability=StackVerdict.PASS, abi_risk=StackVerdict.PASS,
        baseline_graph=_graph(), candidate_graph=graph,
        bindings_baseline=[], bindings_candidate=[],
        missing_symbols=[], stack_changes=[], risk_score="low",
    )
    out = stack_to_html(r)
    assert "(None)" not in out
    assert "libfoo.so" in out
