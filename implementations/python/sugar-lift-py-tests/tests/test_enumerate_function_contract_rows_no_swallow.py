"""JOIN defect: enumeration door must not swallow function_contract_rows throws.

#6944 (sin cluster 4) rips ``except Exception: continue`` around
``function_contract_rows`` in the implications target_candidates loop.
#6946 (sin cluster 6 / enumeration door) rewrote that loop to use
``resolve_function_for_call`` but KEPT the same Exception swallow — a second
mechanism inventing absence when body sugar is unfinished.

Law of One: AST tree shadows → Sugar → meaning. Catch-and-continue is not a
third path. Throwing is honorable (code not written yet). Rip the handler.

Shell deleted: soft survival of unfinished Sugar via empty target_candidates.
No counter, no named refusal at this mouth, no log-and-continue.

Retirement: when the implications path cannot soft-skip any Exception class
(production types force throws to the transport edge), this tooth becomes a
pure reintroduction membrane over open Python source.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from sugar_source_tree.panic import SugarNotWritten

_LIFT_RPC = (
    Path(__file__).resolve().parents[1] / "src" / "sugar_lift_py_tests" / "lift_rpc.py"
)

_CONTRACT_ROWS_CALL = "function_contract_rows"


def _except_exception_continue_wrappers(
    source: str, *, call_name: str, path: str = "<planted>"
) -> list[str]:
    """AST tooth: ``try: <call_name>(...) except Exception: continue``.

    The live offender class is catch-and-continue around a named call that
    must be allowed to throw. Detects the full try body containing the call
    and a handler that catches Exception (or bare Exception subclass chain
    named Exception) whose body is a pure ``continue``.
    """
    tree = ast.parse(source, filename=path)
    offenders: list[str] = []

    def calls_target(node: ast.AST) -> bool:
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            func = child.func
            if isinstance(func, ast.Name) and func.id == call_name:
                return True
            if isinstance(func, ast.Attribute) and func.attr == call_name:
                return True
        return False

    def handler_is_exception_continue(handler: ast.ExceptHandler) -> bool:
        # except Exception / except Exception as e
        t = handler.type
        if t is None:
            return False  # bare except is a different sin class; other teeth
        if isinstance(t, ast.Name) and t.id == "Exception":
            pass
        elif isinstance(t, ast.Tuple) and any(
            isinstance(e, ast.Name) and e.id == "Exception" for e in t.elts
        ):
            pass
        else:
            return False
        # body is continue (optionally with pass-only noise)
        if not handler.body:
            return False
        return all(isinstance(stmt, (ast.Continue, ast.Pass)) for stmt in handler.body)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        if not calls_target(node):
            continue
        for handler in node.handlers:
            if handler_is_exception_continue(handler):
                offenders.append(
                    f"{path}:{getattr(node, 'lineno', 0)}: "
                    f"except Exception: continue wraps {_CONTRACT_ROWS_CALL}"
                )
    return offenders


# ---------------------------------------------------------------------------
# Runtime twins: swallow manufactures absence; bare call throws
# ---------------------------------------------------------------------------


def test_truthful_function_contract_rows_exception_propagates() -> None:
    """Truthful twin: a raise from function_contract_rows is not continue."""

    def function_contract_rows(fn, file_rel):
        del fn, file_rel
        raise SugarNotWritten(
            blame=SimpleNamespace(filename="t.py", line=1, col=0),
            owner="test.enumerate.function_contract_rows",
            observed="body sugar not written",
            requested="Complete universe with contract rows",
            fix="write body sugar; do not drop the target from candidates",
        )

    with pytest.raises(SugarNotWritten) as raised:
        for name in ["target_fn"]:
            function_contract_rows(SimpleNamespace(name=name), "t.py")
    assert raised.value.owner == "test.enumerate.function_contract_rows"


def test_lying_twin_except_exception_continue_manufactures_absence() -> None:
    """LYING TWIN: plant the sin; empty candidates while throws were swallowed.

    This is the historical #6946 join shape. Detection: silent_drops > 0 and
    empty candidates while the bare call still raises.
    """

    def function_contract_rows(fn, file_rel):
        del fn, file_rel
        raise RuntimeError("body sugar refused")

    targets = ["a", "b"]
    target_candidates: list[str] = []
    silent_drops = 0
    for name in targets:
        fn = SimpleNamespace(name=name)
        try:
            _def_memento, rows = function_contract_rows(fn, "t.py")
        except Exception:
            silent_drops += 1
            continue
        if rows is None:
            continue
        target_candidates.append(name)

    # The planted sin works: candidates empty, drops counted.
    assert silent_drops == 2
    assert target_candidates == []
    # Without the swallow, the same call is loud.
    with pytest.raises(RuntimeError, match="body sugar refused"):
        function_contract_rows(SimpleNamespace(name="a"), "t.py")


def test_ast_tooth_lying_twin_planted_swallow_is_visible() -> None:
    """AST tooth must recognize the planted except Exception: continue shape."""
    planted = """
def _handle_enumerate():
    for call in calls:
        try:
            fn = resolve_function_for_call(call)
        except FunctionBindingMiss:
            continue
        try:
            def_memento, rows = function_contract_rows(fn, file_rel)
        except Exception:
            continue
        if rows is None:
            continue
"""
    offenders = _except_exception_continue_wrappers(
        planted, call_name=_CONTRACT_ROWS_CALL, path="planted.py"
    )
    assert len(offenders) == 1, offenders
    assert "except Exception" in offenders[0]
    assert _CONTRACT_ROWS_CALL in offenders[0]


def test_ast_tooth_does_not_flag_sugar_not_written_gap_recording() -> None:
    """except SugarNotWritten that records a gap is a different (named) path.

    This tooth owns only the Exception-continue swallow class. Other soft
    membranes get their own instruments.
    """
    clean = """
def universe_arm():
    for fn in functions:
        try:
            def_memento, rows = function_contract_rows(fn, file_rel)
        except SugarNotWritten as gap:
            gaps.append(gap.observed)
            continue
"""
    assert (
        _except_exception_continue_wrappers(clean, call_name=_CONTRACT_ROWS_CALL) == []
    )


def test_production_lift_rpc_has_zero_exception_continue_on_function_contract_rows() -> (
    None
):
    """Production door: R=0 for Exception-continue wraps of function_contract_rows."""
    assert _LIFT_RPC.is_file(), _LIFT_RPC
    source = _LIFT_RPC.read_text(encoding="utf-8")
    # Collected-count guard: file must still expose the call.
    assert source.count(_CONTRACT_ROWS_CALL) >= 1

    offenders = _except_exception_continue_wrappers(
        source, call_name=_CONTRACT_ROWS_CALL, path=str(_LIFT_RPC)
    )
    assert offenders == [], (
        "function_contract_rows swallow still live in lift_rpc; "
        "rip except Exception: continue. Offenders:\n" + "\n".join(offenders)
    )


def test_production_implications_call_site_has_no_try_around_contract_rows() -> None:
    """Local window check on the implications target_candidates site."""
    source = _LIFT_RPC.read_text(encoding="utf-8")
    marker = "def_memento, rows = _tree.function_contract_rows(fn, file_rel)"
    assert marker in source
    # Every occurrence of this assignment in implications-style loops must not
    # sit inside an Exception-continue try. Use the AST tooth as authority.
    offenders = _except_exception_continue_wrappers(
        source, call_name=_CONTRACT_ROWS_CALL, path=str(_LIFT_RPC)
    )
    assert offenders == []
    # Also: the join-site comment must remain as orientation (deleted => red
    # only if someone removes the bare call; soft check that bare call exists).
    idx = source.index(marker)
    window = source[max(0, idx - 200) : idx + 40]
    assert "except Exception" not in window
