from __future__ import annotations

import tempfile

import pytest

from sugar_lift_py_tests.effect import NameErrorEffect, RaiseEffect
from sugar_lift_py_tests.floor import ReturnValue, TermValue, UniverseValue
from sugar_lift_py_tests.ir import and_, make_var, not_, or_, py_truthy
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted, Incomplete
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.binding_state import (
    BranchResultSlot,
    GuardedBinding,
    UnboundBinding,
)
from sugar_source_tree.nodes import Node
from sugar_source_tree.panic import BackendDefect, SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _out(source: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(source)
        path = f.name
    return next(SourceFile(path_source(path)).functions()).sugar().desugar()


def _substituted(source: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(source)
        path = f.name
    return next(SourceFile(path_source(path)).functions()).substitute({})


def _assert_unpack_effect(effect, *, arity: int, names: tuple[str, ...]):
    """The typed arity obligation itself: the effect names the count it demands
    and the targets it demands it for, and it binds nothing."""
    from sugar_lift_py_tests.effect import SequenceUnpackRuntimeEffect
    from sugar_lift_py_tests.floor.scope_rebind import ScopeRebinds

    assert isinstance(effect, SequenceUnpackRuntimeEffect)
    reason = effect.reason
    assert f"exactly {arity} members" in reason, reason
    assert ", ".join(names) in reason, reason
    assert not isinstance(getattr(effect, "value", None), ScopeRebinds)
    return effect


def _assert_unpack_arity_obligation(out, *, arity: int, names: tuple[str, ...]):
    """The typed arity obligation a non-display unpack retains, and NO binding.

    `a, b = <name>` has no lift-time cardinality: the count belongs to Python's
    `__iter__` at runtime. The lift keeps the demand as one typed effect rather
    than refusing to have a meaning (#6316) and rather than assuming the count
    matched (which would be the one forbidden move). CPython binds nothing when
    `UNPACK_SEQUENCE` raises, so this asserts nothing bound too.
    """
    assert isinstance(out, Incomplete), type(out).__name__
    return _assert_unpack_effect(out.effect, arity=arity, names=names)


def _return(exit_):
    assert isinstance(exit_, Completed)
    assert isinstance(exit_.value, UniverseValue)
    returns = [e for e in exit_.value.record.statements if isinstance(e, ReturnValue)]
    assert len(returns) == 1
    return returns[0]


def _partition(out):
    assert isinstance(out, ExitSet)
    halted = [e for e in out.exits if isinstance(e, Halted)]
    completed = [e for e in out.exits if isinstance(e, Completed)]
    return halted, completed


def test_delete_one_branch_then_read_has_exact_guard_partition() -> None:
    out = _out("def f(c):\n x=1\n if c:\n  del x\n return x\n")
    halted, completed = _partition(out)
    guard = py_truthy(make_var("c"))
    assert len(halted) == len(completed) == 1
    assert halted[0].guard != guard
    assert isinstance(halted[0].effect, NameErrorEffect)
    assert completed[0].guard == not_(halted[0].guard)
    assert _return(completed[0]).value == TermValue(1)

    reverse = _out("def f(c):\n x=1\n if c:\n  pass\n else:\n  del x\n return x\n")
    halted, completed = _partition(reverse)
    assert halted[0].guard == not_(completed[0].guard)


def test_delete_both_branches_then_read_is_unconditionally_unbound() -> None:
    out = _out("def f(c):\n x=1\n if c:\n  del x\n else:\n  del x\n return x\n")
    assert isinstance(out, Incomplete)
    assert isinstance(out.effect, NameErrorEffect)


def test_neither_branch_deletes_keeps_ordinary_value_phi() -> None:
    out = _out("def f(c):\n x=1\n if c:\n  x=2\n else:\n  x=3\n return x\n")
    assert isinstance(out, Complete)
    assert isinstance(out.value, UniverseValue)
    assert not any(isinstance(e, NameErrorEffect) for e in out.value.record.statements)


def test_unconditional_reassignment_replaces_tombstone_but_read_rhs_does_not() -> None:
    out = _out("def f(c):\n x=1\n if c:\n  del x\n x=2\n return x\n")
    assert isinstance(out, Complete)
    returns = [e for e in out.value.record.statements if isinstance(e, ReturnValue)]
    assert returns[0].value == TermValue(2)

    bad = _out("def f(c):\n x=1\n if c:\n  del x\n x=x+1\n return x\n")
    halted, completed = _partition(bad)
    assert isinstance(halted[0].effect, NameErrorEffect)
    assert completed[0].guard == not_(halted[0].guard)


def test_delete_after_halt_does_not_create_a_reachable_name_error() -> None:
    out = _out("def f(c, E):\n x=1\n if c:\n  raise E\n  del x\n return x\n")
    halted, completed = _partition(out)
    assert len(halted) == len(completed) == 1
    assert isinstance(halted[0].effect, RaiseEffect)
    assert not isinstance(halted[0].effect, NameErrorEffect)
    assert completed[0].guard == not_(halted[0].guard)


def test_delete_already_unbound_and_second_delete_are_loud() -> None:
    out = _out("def f():\n del x\n")
    assert isinstance(out, Incomplete)
    assert isinstance(out.effect, NameErrorEffect)
    twice = _out("def f():\n x=1\n del x\n del x\n")
    assert isinstance(twice, Incomplete)
    assert isinstance(twice.effect, NameErrorEffect)


def test_nested_conditional_delete_retains_both_source_guards() -> None:
    out = _out("def f(a,b):\n x=1\n if a:\n  if b:\n   del x\n return x\n")
    halted, completed = _partition(out)
    ga = py_truthy(make_var("a"))
    gb = py_truthy(make_var("b"))
    assert halted[0].guard.kind == "and"
    outer, inner = halted[0].guard.operands
    assert outer != inner
    assert completed[0].guard == or_([not_(outer), and_([outer, not_(inner)])])


def test_pandas_blocks_nested_if_augassign_reads_unbound_binding_as_a_node() -> None:
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
    assert any(isinstance(read.state, UnboundBinding) for read in reads)
    # #6316 drained this refusal too. Here the unpack sits INSIDE an `if`, so the
    # arity obligation is one HALTED face of the partition and the complementary
    # face still completes -- the guard and the obligation coexist, which is the
    # whole point of retaining the demand instead of refusing the statement.
    out = _out(source)
    assert isinstance(out, ExitSet)
    halted = [exit_ for exit_ in out.exits if isinstance(exit_, Halted)]
    completed = [exit_ for exit_ in out.exits if isinstance(exit_, Completed)]
    assert len(halted) == 1
    assert len(completed) == 1
    _assert_unpack_effect(halted[0].effect, arity=2, names=("col", "loc"))


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
    outer = next(read for read in reads if isinstance(read.state, GuardedBinding))
    addition = outer.state.when_true
    old_read = addition.left
    assert old_read.kind == "GuardedBindingRead"
    assert isinstance(old_read.state, GuardedBinding)
    assert old_read.state.slot.slot_id == first_if.branch_result_slot_id
    assert outer.state.slot.slot_id == second_if.branch_result_slot_id

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
    assert any(
        getattr(getattr(_return(face).value, "term", None), "name", None) == "+"
        for face in completed
    )


def test_pandas_converter_if_augassign_reads_unbound_binding_as_a_node() -> None:
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
    assert {"vmin", "vmax"} <= names
    # #6316 drained this refusal. The unpack no longer declines to have a
    # meaning: the RHS is a plain name with no authenticated cardinality, so the
    # arity demand is RETAINED as a typed effect carrying the exact obligation.
    # Pinning the replacement is strictly stronger than pinning the refusal --
    # it names the effect, the arity, and that nothing bound.
    _assert_unpack_arity_obligation(_out(source), arity=2, names=("vmin", "vmax"))


def test_augassign_over_explicitly_unbound_local_builds_guarded_read() -> None:
    out = _out("def f():\n x += 1\n return x\n")
    assert isinstance(out, Incomplete)
    assert isinstance(out.effect, NameErrorEffect)
    assert out.effect.name == "x"


def test_bound_augassign_control_remains_completed_value() -> None:
    out = _out("def f():\n x = 1\n x += 2\n return x\n")
    assert isinstance(out, Complete)
    returns = [
        entry for entry in out.value.record.statements if isinstance(entry, ReturnValue)
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
        assert not hasattr(state, "sugar")

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
    assert isinstance(out, Complete)
    assert isinstance(out.value, UniverseValue)
    assert not any(
        isinstance(entry, NameErrorEffect) for entry in out.value.record.statements
    )


def test_try_exception_alias_is_tombstoned_after_handler() -> None:
    out = _out(
        "def f():\n"
        " try:\n  raise ValueError\n"
        " except ValueError as first:\n  pass\n"
        " return first\n"
    )
    assert isinstance(out, Incomplete)
    assert isinstance(out.effect, NameErrorEffect)
    assert out.effect.name == "first"


def test_try_uncaught_raise_remains_a_halted_face() -> None:
    out = _out(
        "def f():\n" " try:\n  raise TypeError\n" " except ValueError:\n  pass\n"
    )
    assert isinstance(out, Incomplete)
    assert isinstance(out.effect, RaiseEffect)
    assert out.effect.exception_name == "TypeError"


def test_try_finally_rebinding_applies_to_normal_and_handler_completions() -> None:
    out = _out(
        "def f(c):\n x=0\n"
        " try:\n  if c:\n   raise ValueError\n  x=1\n"
        " except ValueError:\n  x=2\n"
        " finally:\n  x=9\n"
        " return x\n"
    )
    assert isinstance(out, Complete)
    returns = [e for e in out.value.record.statements if isinstance(e, ReturnValue)]
    assert returns[0].value == TermValue(9)


def test_try_conditional_raise_routes_to_handler_and_joins_bindings() -> None:
    out = _out(
        "def f(c):\n"
        " try:\n  if c:\n   raise ValueError\n  x=1\n"
        " except ValueError:\n  x=2\n"
        " return x\n"
    )
    assert isinstance(out, Complete)
    assert isinstance(out.value, UniverseValue)
