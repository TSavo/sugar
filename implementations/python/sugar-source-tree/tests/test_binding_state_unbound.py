from __future__ import annotations

import tempfile

import pytest

from sugar_lift_py_tests.effect import NameErrorEffect, RaiseEffect
from sugar_lift_py_tests.floor import ReturnValue, TermValue, UniverseValue
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_py_tests.outcome.exit_set import _are_exclusive, _conjuncts
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.binding_state import (
    BranchResultSlot,
    GuardedBinding,
    UnboundBinding,
)
from sugar_source_tree.nodes import Node
from sugar_source_tree.panic import BackendDefect
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.tree import SourceFile


def _out(source: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(source)
        path = f.name
    return next(SourceFile(path_source(path), construction_context=TreeConstructionContextV1.for_test_without_workspace()).functions()).sugar().desugar()


def _substituted(source: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(source)
        path = f.name
    return next(SourceFile(path_source(path), construction_context=TreeConstructionContextV1.for_test_without_workspace()).functions()).substitute({})


def _assert_unpack_effect(halt, *, arity: int):
    """The arity obligation itself: the halt raises something undetermined
    (no exception class is invented), under the complement of the completes
    atom over ``python:unpack.destructure(term, arity)``, and binds nothing."""
    from sugar_lift_py_tests.effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.floor.scope_rebind import ScopeRebinds
    from sugar_lift_py_tests.ir import num

    effect = halt.effect
    assert isinstance(effect, UndeterminedRaiseEffect)
    assert effect.exception_type_coordinate is None
    guard = str(halt.guard)
    assert "python:unpack.destructure" in guard, guard
    assert str(num(arity)) in guard, guard
    assert not isinstance(getattr(effect, "value", None), ScopeRebinds)
    return effect


def _assert_unpack_arity_obligation(out, *, arity: int):
    """The typed arity obligation a non-display unpack retains, and NO binding.

    `a, b = <name>` has no lift-time cardinality: the count belongs to Python's
    `__iter__` at runtime. The lift keeps the demand as one typed effect rather
    than refusing to have a meaning (#6316) and rather than assuming the count
    matched (which would be the one forbidden move). CPython binds nothing when
    `UNPACK_SEQUENCE` raises, so this asserts nothing bound too.

    Nor does it claim the unpack always fails: the halt is one arm, under the
    complement of the unpack's completes atom, and the statements after it
    run beneath the completed arm.
    """
    (halt,) = _unpack_halts(out)
    assert any(isinstance(exit_, Completed) for exit_ in out.exits), out
    return _assert_unpack_effect(halt, arity=arity)


def _unpack_halts(out):
    """The runtime unpack's own undetermined raise (``runtime_unpack_faces``),
    not another undecided operation's (a comparison or an augmented
    assignment over a symbolic operand raises something undetermined too)."""
    from sugar_lift_py_tests.effect import UndeterminedRaiseEffect

    assert isinstance(out, ExitSet), out
    return [
        exit_
        for exit_ in out.halts()
        if isinstance(exit_.effect, UndeterminedRaiseEffect)
        and str(exit_.effect.producer_node_owner).endswith(".unpack")
    ]


def _return(exit_):
    assert isinstance(exit_, Completed)
    assert isinstance(exit_.value, UniverseValue)
    returns = [e for e in exit_.value.record.statements if isinstance(e, ReturnValue)]
    assert len(returns) == 1
    return returns[0]


def _truth_halt(exit_) -> bool:
    """A formal's truth halt: ``bool(c)`` on a parameter is the one truth
    rule's two faces (#9018), so ``if c:`` completes under its truth's
    completion and halts undetermined under the complement, beside every
    arm the branch itself decides."""
    from sugar_lift_py_tests.effect import UndeterminedRaiseEffect

    return (
        isinstance(exit_, Halted)
        and isinstance(exit_.effect, UndeterminedRaiseEffect)
        and str(exit_.effect.producer_node_owner).endswith(".truth")
    )


def _partition(out):
    """The halts the body itself decides and its completions; a formal's
    truth halts (``_truth_halt``) are kept beside them, never counted as
    either."""
    assert isinstance(out, ExitSet)
    halted = [e for e in out.exits if isinstance(e, Halted) and not _truth_halt(e)]
    completed = [e for e in out.exits if isinstance(e, Completed)]
    return halted, completed


def _completed_values(out):
    """Every completed arm's value; at least one, and no halt but a
    formal's truth halt beside them."""
    assert isinstance(out, ExitSet), out
    assert all(_truth_halt(halt) for halt in out.halts()), out.halts()
    values = [e.value for e in out.exits if isinstance(e, Completed)]
    assert values, out
    return values


def _truthy_literals(guard):
    """The positive branch literals (``py.truthy(...)``) ``guard`` conjoins."""
    return {
        literal
        for literal in _conjuncts(guard)
        if getattr(literal, "name", None) == "py.truthy"
    }


def test_delete_one_branch_then_read_has_exact_guard_partition() -> None:
    out = _out("def f(c):\n x=1\n if c:\n  del x\n return x\n")
    halted, completed = _partition(out)
    assert len(halted) == len(completed) == 1
    assert isinstance(halted[0].effect, NameErrorEffect)
    # The read halts exactly where the branch deleted, and completes exactly
    # where it did not: the two faces of one branch, never overlapping.
    assert _are_exclusive(halted[0].guard, completed[0].guard)
    assert _truthy_literals(halted[0].guard)
    assert _return(completed[0]).value == TermValue(1)

    reverse = _out("def f(c):\n x=1\n if c:\n  pass\n else:\n  del x\n return x\n")
    halted, completed = _partition(reverse)
    assert len(halted) == len(completed) == 1
    assert isinstance(halted[0].effect, NameErrorEffect)
    assert _are_exclusive(halted[0].guard, completed[0].guard)
    assert _truthy_literals(completed[0].guard)


def test_delete_both_branches_then_read_is_unconditionally_unbound() -> None:
    out = _out("def f(c):\n x=1\n if c:\n  del x\n else:\n  del x\n return x\n")
    assert out.halts() == out.exits
    named = [halt for halt in out.halts() if not _truth_halt(halt)]
    assert named
    assert all(isinstance(halt.effect, NameErrorEffect) for halt in named), named


def test_neither_branch_deletes_keeps_ordinary_value_phi() -> None:
    out = _out("def f(c):\n x=1\n if c:\n  x=2\n else:\n  x=3\n return x\n")
    for value in _completed_values(out):
        assert isinstance(value, UniverseValue)
        assert not any(isinstance(e, NameErrorEffect) for e in value.record.statements)


def test_unconditional_reassignment_replaces_tombstone_but_read_rhs_does_not() -> None:
    out = _out("def f(c):\n x=1\n if c:\n  del x\n x=2\n return x\n")
    for value in _completed_values(out):
        returns = [e for e in value.record.statements if isinstance(e, ReturnValue)]
        assert returns[0].value == TermValue(2)

    bad = _out("def f(c):\n x=1\n if c:\n  del x\n x=x+1\n return x\n")
    halted, completed = _partition(bad)
    (name_error,) = [h for h in halted if isinstance(h.effect, NameErrorEffect)]
    assert completed
    assert all(_are_exclusive(name_error.guard, arm.guard) for arm in completed)


def test_delete_after_halt_does_not_create_a_reachable_name_error() -> None:
    out = _out("def f(c, E):\n x=1\n if c:\n  raise E\n  del x\n return x\n")
    halted, completed = _partition(out)
    # The raise halts its branch (raising a formal may itself halt more than
    # one way); the delete after it is unreachable, so no read halts on it.
    assert halted, out.exits
    assert not any(isinstance(h.effect, NameErrorEffect) for h in halted)
    assert len(completed) == 1
    assert all(_are_exclusive(h.guard, completed[0].guard) for h in halted)
    assert _return(completed[0]).value == TermValue(1)


def _guarded_slots(reads):
    """Every branch slot a guarded read in ``reads`` is under, through the
    states and the nodes they hold (a state is never an AST child, so the
    tree walk alone does not reach a read a state holds)."""
    slots = set()
    seen = set()
    pending = [read.state for read in reads]
    while pending:
        state = pending.pop()
        if id(state) in seen:
            continue
        seen.add(id(state))
        if isinstance(state, GuardedBinding):
            slots.add(state.slot.slot_id)
            pending.extend((state.when_true, state.when_false))
        elif isinstance(state, Node):
            pending.extend(
                node.state for node in state.walk() if node.kind == "GuardedBindingRead"
            )
    return slots


def test_delete_already_unbound_and_second_delete_are_loud() -> None:
    out = _out("def f():\n del x\n")
    assert out.halts() == out.exits
    (halt,) = out.halts()
    assert isinstance(halt.effect, NameErrorEffect)
    twice = _out("def f():\n x=1\n del x\n del x\n")
    assert twice.halts() == twice.exits
    (twice_halt,) = twice.halts()
    assert isinstance(twice_halt.effect, NameErrorEffect)


def test_nested_conditional_delete_retains_both_source_guards() -> None:
    out = _out("def f(a,b):\n x=1\n if a:\n  if b:\n   del x\n return x\n")
    halted, completed = _partition(out)
    (name_error,) = [h for h in halted if isinstance(h.effect, NameErrorEffect)]
    # The delete ran only under BOTH branches: the halt holds both source
    # guards, and no completed arm overlaps it.
    assert len(_truthy_literals(name_error.guard)) >= 2, name_error.guard
    assert completed
    assert all(_are_exclusive(name_error.guard, arm.guard) for arm in completed)
    assert all(_return(arm).value == TermValue(1) for arm in completed)


def test_pandas_blocks_nested_if_augassign_reads_the_unpack_binding() -> None:
    source = (
        "def f(i, values):\n"
        " if isinstance(i, tuple):\n"
        "  col, loc = i\n"
        "  if loc < 0:\n"
        "   loc += len(values)\n"
        "  return loc\n"
    )
    function = _substituted(source)
    reads = [node for node in function.walk() if node.kind == "GuardedBindingRead"]
    # The unpack binds ``loc`` on its completed face (a read of its
    # projection key, #7661), so no read of ``loc`` after it is unbound.
    assert not any(
        isinstance(read.state, UnboundBinding) and read.name == "loc"
        for read in reads
    )
    # #6316 drained this refusal too. Here the unpack sits INSIDE an `if`, so the
    # arity obligation is one HALTED face of the partition and the complementary
    # face still completes -- the guard and the obligation coexist, which is the
    # whole point of retaining the demand instead of refusing the statement.
    # The unpack itself is two-faced too: beneath the branch, it completes
    # under its completes atom and halts under the complement.
    out = _out(source)
    (halt,) = _unpack_halts(out)
    assert any(isinstance(exit_, Completed) for exit_ in out.exits)
    _assert_unpack_effect(halt, arity=2)


def test_pandas_html_if_augassign_reads_guarded_binding_as_a_node() -> None:
    function = _substituted(
        "def f(c, foot):\n"
        " if c:\n"
        "  body = 1\n"
        " if foot:\n"
        "  body += foot\n"
        " return body\n"
    )
    first_if, second_if = function.body[:2]
    reads = [node for node in function.walk() if node.kind == "GuardedBindingRead"]
    slots = _guarded_slots(reads)
    # The augmented read of the old ``body`` is guarded by the first ``if``
    # (bound only under ``c``); the final read by the second.
    assert first_if.branch_result_slot_id in slots, slots
    assert second_if.branch_result_slot_id in slots, slots

    halted, completed = _partition(
        _out(
            "def f(c, foot):\n"
            " if c:\n"
            "  body = 1\n"
            " if foot:\n"
            "  body += foot\n"
            " return body\n"
        )
    )
    assert any(isinstance(face.effect, NameErrorEffect) for face in halted)
    returned = [_return(face).value for face in completed]
    assert TermValue(1) in returned, returned  # c, not foot
    assert any(value != TermValue(1) for value in returned), returned  # the sum


def test_pandas_converter_if_augassign_reads_the_unpack_binding() -> None:
    source = (
        "def f(locs):\n"
        " vmin, vmax = locs\n"
        " if vmin == vmax:\n"
        "  vmin -= 1\n"
        "  vmax += 1\n"
        " return vmin\n"
    )
    function = _substituted(source)
    reads = [node for node in function.walk() if node.kind == "GuardedBindingRead"]
    names = {read.name for read in reads if isinstance(read.state, UnboundBinding)}
    # The unpack binds both names on its completed face (#7661): no read of
    # either is unbound.
    assert not ({"vmin", "vmax"} & names), names
    # #6316 drained this refusal. The unpack no longer declines to have a
    # meaning: the RHS is a plain name with no authenticated cardinality, so the
    # arity demand is RETAINED as a typed effect carrying the exact obligation.
    # Pinning the replacement is strictly stronger than pinning the refusal --
    # it names the effect, the arity, and that nothing bound.
    _assert_unpack_arity_obligation(_out(source), arity=2)


def test_augassign_over_explicitly_unbound_local_builds_guarded_read() -> None:
    out = _out("def f():\n x += 1\n return x\n")
    assert out.halts() == out.exits
    (halt,) = out.halts()
    assert isinstance(halt.effect, NameErrorEffect)
    assert halt.effect.name == "x"


def test_bound_augassign_control_remains_completed_value() -> None:
    out = _out("def f():\n x = 1\n x += 2\n return x\n")
    value = out.completed_value()
    assert value is not None
    returns = [
        entry for entry in value.record.statements if isinstance(entry, ReturnValue)
    ]
    assert returns[0].value == TermValue(3)


def test_binding_state_is_never_an_ast_child_or_node_protocol_value() -> None:
    unbound = UnboundBinding(name="x", cause=_substituted("def f():\n pass\n").fragment)
    guarded = GuardedBinding(
        slot=BranchResultSlot("test-slot"),
        when_true=unbound,
        when_false=unbound,
    )
    for state in (unbound, guarded):
        assert not isinstance(state, Node)
        assert not hasattr(state, "ref")
        # A state projects through the one binding door
        # (``_project_binding_state_sugar``), never ``Node.sugar``.
        assert type(state).sugar is not Node.sugar

    target = _substituted("def f(x):\n x += 1\n").body[0].target
    with pytest.raises(BackendDefect, match="non-Node operands"):
        target._make_binop(unbound, None, target)


def test_try_handler_binding_exports_on_the_handler_completion_edge() -> None:
    out = _out(
        "def f():\n"
        " try:\n  raise ValueError\n"
        " except ValueError as first:\n  a=first\n"
        " return a\n"
    )
    value = out.completed_value()
    assert value is not None
    assert isinstance(value, UniverseValue)
    assert not any(
        isinstance(entry, NameErrorEffect) for entry in value.record.statements
    )


def test_try_exception_alias_is_tombstoned_after_handler() -> None:
    out = _out(
        "def f():\n"
        " try:\n  raise ValueError\n"
        " except ValueError as first:\n  pass\n"
        " return first\n"
    )
    assert out.halts() == out.exits
    (halt,) = out.halts()
    assert isinstance(halt.effect, NameErrorEffect)
    assert halt.effect.name == "first"


def test_try_uncaught_raise_remains_a_halted_face() -> None:
    out = _out(
        "def f():\n" " try:\n  raise TypeError\n" " except ValueError:\n  pass\n"
    )
    assert out.halts() == out.exits
    (halt,) = out.halts()
    assert isinstance(halt.effect, RaiseEffect)
    assert halt.effect.exception_name == "TypeError"


def test_try_finally_rebinding_applies_to_normal_and_handler_completions() -> None:
    out = _out(
        "def f(c):\n x=0\n"
        " try:\n  if c:\n   raise ValueError\n  x=1\n"
        " except ValueError:\n  x=2\n"
        " finally:\n  x=9\n"
        " return x\n"
    )
    # Both the normal and the handler completion leave through the finally.
    for value in _completed_values(out):
        returns = [e for e in value.record.statements if isinstance(e, ReturnValue)]
        assert returns[0].value == TermValue(9)


def test_try_conditional_raise_routes_to_handler_and_joins_bindings() -> None:
    out = _out(
        "def f(c):\n"
        " try:\n  if c:\n   raise ValueError\n  x=1\n"
        " except ValueError:\n  x=2\n"
        " return x\n"
    )
    # ``x`` is bound on the body's and the handler's completion alike: no
    # read of it halts.
    for value in _completed_values(out):
        assert isinstance(value, UniverseValue)
