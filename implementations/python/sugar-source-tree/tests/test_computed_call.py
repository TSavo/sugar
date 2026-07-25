"""The computed callee: `<callee>(<args>)` where the callee is an expression
rather than a bare name or attribute (`fs[0](x)`, `d["k"](x)`). A COMPOSITION:
the callee reduces like any value through whatever sugar its own node built
(SubscriptSugar for `fs[0]`), and the call stands as the coordinate
`py.call(callee, args)`. A callee whose node has no sugar (a Lambda called
inline) stays loud through the ordinary recursion -- this sugar never masks
that gap.

Projection note: formal-parameter indexable operations leave a pending
``ContractConditionalConstructionV1`` until the Rust linker discharges the
demand. ``UniverseValue.post`` panics on pending demands by law. These twins
read the call term from the conditional construction value, not from post().
"""

from __future__ import annotations

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile


def _fn(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return next(SourceFile(path_source(path)).functions())


def _call_term(src):
    """Project the returned call coordinate without illegal UniverseValue.post."""
    universe = _fn(src).sugar().desugar().value
    for entry in universe.record.statements:
        # Discharged path: ReturnValue directly on the record.
        if type(entry).__name__ == "ReturnValue":
            return entry.value.term
        # Pending parameter-contract path: term is on the conditional value.
        if type(entry).__name__ == "ContractConditionalConstructionV1":
            ret = entry.value
            if type(ret).__name__ == "ReturnValue":
                return ret.value.term
            return getattr(ret, "term", ret)
    raise AssertionError(
        f"no return/call term in universe statements: "
        f"{[type(s).__name__ for s in universe.record.statements]}"
    )


def test_computed_call_is_the_py_call_coordinate():
    t = _call_term("def A(fs, x):\n    return fs[0](x)\n")
    assert t.name == "py.call"
    callee = t.args[0]
    assert callee.name == "py.subscript"  # fs[0], the callee operand
    assert t.args[1].name == "x"  # the argument


def test_assert_consumes_the_coordinate():
    universe = (
        _fn("def A(fs, x):\n    assert fs[0](x) == x\n    return x\n")
        .sugar()
        .desugar()
        .value
    )
    # Assert may also sit under a pending contract; walk invs and contributions.
    invs = universe.invs()
    if invs:
        inv = invs[0]
        assert inv.name == "py.eq"
        assert inv.args[0].name == "py.call"
        return
    # Pending-contract path: find py.call in statement tree.
    text = str(universe.record.statements)
    assert "py.call" in text


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
    assert t.args[0].name == "py.subscript"
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
