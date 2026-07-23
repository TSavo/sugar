"""Assignment binding and store-effect construction twins.

Exact display destructuring already builds.  The symbolic destructuring tests
below are deliberately red until the binder-bearing ``python:unpack_assign``
projection is implemented: they pin single RHS evaluation, projection
discrimination, nested binding, and loud malformed shapes without choosing a
projection coordinate ahead of the architecture ruling.
"""

import tempfile

import pytest

from sugar_lift_py_tests.effect import (
    AttributeStoreRuntimeEffect,
    SubscriptStoreRuntimeEffect,
)
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.ir import _free_vars_in_term
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _fn(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return next(SourceFile(path_source(path)).functions())


def _post(src):
    return _fn(src).sugar().desugar().value.post()


def _universe(src):
    return _fn(src).sugar().desugar().value


def test_tuple_destructure_assign_lifts_through():
    post = _post("def A():\n    a, b = (1, 2)\n    return a + b\n")
    assert post.args[1].value == 3


def test_tuple_destructure_discriminates_on_pairing():
    # Swap the pair -- a different sum, a different fact -- proves the
    # binding actually threads a AND b, not just "some" value.
    forward = _post("def A():\n    a, b = (1, 2)\n    return a - b\n").args[1].value
    swapped = _post("def A():\n    a, b = (2, 1)\n    return a - b\n").args[1].value
    assert forward == -1
    assert swapped == 1
    assert forward != swapped


def test_list_display_destructure_also_lifts():
    post = _post("def A():\n    a, b = [10, 20]\n    return a + b\n")
    assert post.args[1].value == 30


def test_chained_assign_binds_every_target():
    post = _post("def A():\n    x = y = 5\n    return x + y\n")
    assert post.args[1].value == 10


def test_starred_target_stays_loud():
    with pytest.raises(SugarNotWritten):
        _fn("def A():\n    a, *b = (1, 2, 3)\n    return a\n").sugar()


def test_symbolic_nested_tuple_target_binds_correct_projections():
    universe = _universe(
        "def A(triple):\n"
        "    (a, (b, c)) = triple\n"
        "    return a + b + c\n"
    )
    result = universe.post().args[1]
    assert _free_vars_in_term(result) == set()
    assert set().union(*(_free_vars_in_term(arg) for inv in universe.invs() for arg in inv.args)) == {"triple"}

    # ((a + b) + c): each bound name must denote its own projection.  Reusing
    # one plausible projection for two names is a lying construction.
    first_sum, c_projection = result.args
    a_projection, b_projection = first_sum.args
    assert a_projection != b_projection
    assert a_projection != c_projection
    assert b_projection != c_projection


def test_arity_mismatch_stays_loud():
    with pytest.raises(SugarNotWritten):
        _fn("def A():\n    a, b = (1,)\n    return a\n").sugar()


def test_symbolic_rhs_binds_distinct_correct_projections():
    universe = _universe("def A(pair):\n    a, b = pair\n    return a - b\n")
    result = universe.post().args[1]
    assert _free_vars_in_term(result) == set()
    assert set().union(*(_free_vars_in_term(arg) for inv in universe.invs() for arg in inv.args)) == {"pair"}
    a_projection, b_projection = result.args
    assert a_projection != b_projection


def test_symbolic_destructure_evaluates_rhs_exactly_once(monkeypatch):
    # Count at the meaning boundary, after construction.  An implementation
    # which obtains each projection by independently desugaring ``pair(z)``
    # violates Python's evaluate-RHS-once rule and makes this count two.
    sugar = _fn(
        "def A(z):\n"
        "    a, b = pair(z)\n"
        "    return a - b\n"
    ).sugar()

    from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar

    calls = 0
    original = CallSiteSugar.desugar

    def counted(self, ctx=None):
        nonlocal calls
        if self.target_name == "pair":
            calls += 1
        return original(self, ctx)

    monkeypatch.setattr(CallSiteSugar, "desugar", counted)
    outcome = sugar.desugar()
    assert outcome.value.post() is not None
    assert calls == 1


def test_symbolic_destructure_mints_one_slot_and_exact_paths(monkeypatch):
    import sugar_source_tree.nodes as nodes
    from sugar_source_tree.unpack_assignment import Position

    minted = 0
    original = nodes.unpack_assignment_slot

    def counted(fragment, pattern):
        nonlocal minted
        minted += 1
        return original(fragment, pattern)

    monkeypatch.setattr(nodes, "unpack_assignment_slot", counted)
    substituted = _fn(
        "def A(pair):\n    a, b = pair\n    return a, b\n"
    ).substitute({})
    assignment = substituted.body[0]
    projections = [
        node for node in substituted.body[1].walk() if node.kind == "UnpackProjectionRef"
    ]
    assert minted == 1
    assert len(projections) == 2
    assert all(
        projection.slot.slot_id == assignment.unpack_assignment_slot_id
        for projection in projections
    )
    assert {projection.path for projection in projections} == {
        (Position(0),),
        (Position(1),),
    }


def test_lying_unpack_projection_path_stays_loud():
    from sugar_lift_py_tests.floor.unpack_value_binding import (
        UnpackValueBinding,
        unpack_slot_term,
        validate_unpack_projections,
    )
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.gap.panic import ConstructionPanic
    from sugar_lift_py_tests.ir import atomic, ctor, make_var, num
    from sugar_source_tree.unpack_assignment import (
        UnpackAssignmentSlot,
        UnpackNamePattern,
        UnpackSequencePattern,
    )

    slot = UnpackAssignmentSlot("unpack-assignment:truthful")
    pattern = UnpackSequencePattern(
        "tuple", (UnpackNamePattern("a"), UnpackNamePattern("b"))
    )
    binding = UnpackValueBinding(slot, SymbolicValue(make_var("pair")), pattern)
    lying = ctor(
        "python:unpack_projection",
        [
            unpack_slot_term(slot),
            ctor("python:unpack_path", [ctor("python:position", [num(2)])]),
        ],
    )
    with pytest.raises(ConstructionPanic):
        validate_unpack_projections((atomic("observed", [lying]),), (binding,))


def test_lying_name_to_projection_pair_stays_loud():
    from sugar_source_tree.panic import BackendDefect
    from sugar_source_tree.unpack_assignment import (
        Position,
        UnpackAssignmentSlot,
        UnpackNamePattern,
        UnpackSequencePattern,
    )

    assignment = next(
        node
        for node in _fn("def A(pair):\n    a, b = pair\n").walk()
        if node.kind == "Assign"
    )
    pattern = UnpackSequencePattern(
        "tuple", (UnpackNamePattern("a"), UnpackNamePattern("b"))
    )
    with pytest.raises(BackendDefect):
        assignment._make_unpack_projection_ref(
            UnpackAssignmentSlot("unpack-assignment:test"),
            pattern,
            "b",
            (Position(0),),
        )


def test_mixed_chained_targets_stay_loud():
    # x is a plain Name but the second target is a tuple -- mixed shapes
    # never get a partial binding.
    with pytest.raises(SugarNotWritten):
        _fn("def A():\n    x = (a, b) = (1, 2)\n    return x\n").sugar()


def test_attribute_store_target_lifts_a_typed_red_effect():
    entries = _fn("def A(o):\n    o.a = 1\n    return o\n").sugar().desugar().value.record.statements
    red = [e for e in entries if isinstance(e, Incomplete)]
    assert len(red) == 1
    assert isinstance(red[0].effect, AttributeStoreRuntimeEffect)


def test_subscript_store_target_lifts_a_typed_red_effect():
    entries = _fn("def A(xs):\n    xs[0] = 1\n    return xs\n").sugar().desugar().value.record.statements
    red = [e for e in entries if isinstance(e, Incomplete)]
    assert len(red) == 1
    assert isinstance(red[0].effect, SubscriptStoreRuntimeEffect)


if __name__ == "__main__":
    test_tuple_destructure_assign_lifts_through()
    test_tuple_destructure_discriminates_on_pairing()
    test_list_display_destructure_also_lifts()
    test_chained_assign_binds_every_target()
    test_starred_target_stays_loud()
    test_symbolic_nested_tuple_target_binds_correct_projections()
    test_arity_mismatch_stays_loud()
    test_symbolic_rhs_binds_distinct_correct_projections()
    test_mixed_chained_targets_stay_loud()
    test_attribute_store_target_lifts_a_typed_red_effect()
    test_subscript_store_target_lifts_a_typed_red_effect()
    print(
        "ok: tuple/chained assign destructures; starred/nested stay loud; "
        "store targets lift typed red"
    )
