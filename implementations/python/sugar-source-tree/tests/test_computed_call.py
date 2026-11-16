"""The computed callee: `<callee>(<args>)` where the callee is an expression
rather than a bare name or attribute (`fs[0](x)`, `d["k"](x)`). A COMPOSITION:
the callee reduces like any value through whatever sugar its own node built
(SubscriptSugar for `fs[0]`), and the call stands as the coordinate
`py.call(callee, args)`. A callee whose node has no sugar (a Lambda called
inline) stays loud through the ordinary recursion -- this sugar never masks
that gap.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_source_tree.reporter import CollectingReporter


def _fn(src):
    """The one function of ``src``, opened through the one construction door
    under its own workspace: an ``assert`` halts at a ground exit whose
    locus is workspace-relative (``ground_exit``)."""
    root = Path(tempfile.mkdtemp())
    path = root / "m.py"
    path.write_text(src, encoding="utf-8")
    source_file = open_source_file_for_construction(
        path, root=root, reporter=CollectingReporter()
    )
    return next(source_file.functions())


def _called(term):
    """The call a ``python:call_result(<call term>, <occurrence>)`` names:
    one evaluation of a call nothing answered (``_occurrence_result``)."""
    assert term.name == "python:call_result", term
    return term.args[0]


def _universe(fn):
    """The function's universe on its one completed face.  A formal's
    subscript (``fs[0]``) is the one undecided read (#7757, audit 2 row
    NEW-1, #9016), never a carrier waiting on a caller's actual: its value
    is ``python:subscript_result(fs, 0, <key>)``, the callee operand."""
    from sugar_lift_py_tests.outcome import Completed

    outcome = fn.sugar().desugar()
    (done,) = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    return done.value


def _call_term(src):
    """Project the returned call coordinate without illegal UniverseValue.post."""
    universe = _universe(_fn(src))
    for entry in universe.record.statements:
        if type(entry).__name__ == "ReturnValue":
            return _called(entry.value.term)
    raise AssertionError(
        f"no return/call term in universe statements: "
        f"{[type(s).__name__ for s in universe.record.statements]}"
    )


def test_computed_call_is_the_py_call_coordinate():
    t = _call_term("def A(fs, x):\n    return fs[0](x)\n")
    assert t.name == "py.call"
    callee = t.args[0]
    assert callee.name == "python:subscript_result"  # fs[0], the callee operand
    assert t.args[1].name == "x"  # the argument


def test_assert_consumes_the_coordinate():
    universe = _universe(_fn("def A(fs, x):\n    assert fs[0](x) == x\n    return x\n"))
    # The equality over the call's result is the undecided equality's two
    # faces, keyed per evaluation (#7757 NEW-1): the truth of
    # ``python:compare_result("Eq", python:call_result(py.call(..)), x, <key>)``.
    inv = universe.invs()[0]
    assert inv.name == "python:truth_result"
    compared = inv.args[0]
    assert compared.name == "python:compare_result"
    assert compared.args[0].value == "Eq"
    assert _called(compared.args[1]).name == "py.call"


def test_discrimination_differs_by_callee_operand():
    # fs[0](x) vs fs[1](x) -- same shape, different callee coordinate.
    t0 = _call_term("def A(fs, x):\n    return fs[0](x)\n")
    t1 = _call_term("def A(fs, x):\n    return fs[1](x)\n")
    assert t0.name == t1.name == "py.call"
    assert t0.args[0] != t1.args[0]  # the callee subscript differs
    assert t0 != t1


def test_computed_call_spread_uses_reference_call_shape():
    t = _call_term("def A(fs, x, d):\n    return fs[0](x, key=1, **d)\n")

    assert t.name in {"python:call", "py.call"}
    assert t.args[0].name == "python:subscript_result"
    named, spread = t.args[-2:]
    assert named.name in {"python:kwarg", "py.kwarg"}
    assert named.args[0].value == "key"
    assert named.args[1].value == 1
    assert spread.name in {
        "python:double_starred_kwarg",
        "py.double_starred_kwarg",
    }
    assert spread.args[0].name == "d"


def test_lambda_callee_uses_the_computed_call_path():
    sugar = _fn("def A(x):\n    return (lambda z: z)(x)\n").sugar()
    call = sugar.statements[0].value

    assert type(call).__name__ == "ComputedCallSugar"
    assert type(call.callee).__name__ == "LambdaSugar"
    assert call.callee.formals == ("z",)
