from __future__ import annotations

import tempfile

from sugar_lift_py_tests.effect import NameErrorEffect, RaiseEffect
from sugar_lift_py_tests.floor import ReturnValue, TermValue, UniverseValue
from sugar_lift_py_tests.ir import and_, make_var, not_, or_, py_truthy
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted, Incomplete
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile


def _out(source: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(source)
        path = f.name
    return next(SourceFile(path_source(path)).functions()).sugar().desugar()


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
        "def f():\n"
        " try:\n  raise TypeError\n"
        " except ValueError:\n  pass\n"
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
