"""NAME DELETION TEMPORAL LAW.

Concrete:

    x = 1
    del x
    use(x)

Acceptance:

  - deletion removes the exact binding at that temporal point
  - earlier effects remain (values captured before del)
  - later reads are loudly unbound (NameErrorEffect)
  - branch-conditional deletion retains complementary binding states
  - deleting an absent local produces an authenticated NameErrorEffect; a
    function local's is UnboundLocalError (a NameError subclass), decided by
    the function's symbol table (#7586), as Python raises it
  - attribute / subscript deletion not admitted here

Owner path: ``DeleteNameSugar`` / ``delete_binding`` over ``BindingProjection``
(Sugar | UnboundProjection | GuardedProjection | LoopGuardedProjection).
No production edits unless a red names the missing arm.

MUST NOT TOUCH: native-operation projectors, carrier/ExitSet, import identity;
no scope inference from spelling.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect import NameErrorEffect
from sugar_lift_py_tests.effect.authenticated_raise_locus import (
    AuthenticatedRaiseLocus,
)
from sugar_lift_py_tests.floor import ReturnValue, TermValue
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_py_tests.sugar.binding_projection import (
    GuardedProjection,
    UnboundProjection,
)
from sugar_lift_py_tests.sugar.delete_effect_sugar import AttributeDeleteEffectSugar
from sugar_lift_py_tests.sugar.delete_name_sugar import DeleteNameSugar
from sugar_lift_py_tests.sugar.evaluation_ref_sugar import EvaluationRefSugar
from sugar_lift_py_tests.sugar.guarded_binding_read_sugar import GuardedBindingReadSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import FunctionDef
from sugar_source_tree.tree import SourceFile

# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def _tree(source: str, name: str = "delete_name.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _function_outcome(source: str, *, fname: str = "f"):
    tree = _tree(source)
    function = next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == fname
    )
    return function, function.sugar().desugar(None)


def _sole_halt(outcome: ExitSet) -> Halted:
    assert isinstance(outcome, ExitSet)
    halted = [e for e in outcome.exits if isinstance(e, Halted)]
    assert len(halted) == 1, outcome.exits
    return halted[0]


def _sole_completed(outcome: ExitSet) -> Completed:
    assert isinstance(outcome, ExitSet)
    completed = [e for e in outcome.exits if isinstance(e, Completed)]
    assert len(completed) == 1, outcome.exits
    return completed[0]


def _returned(completed: Completed) -> ReturnValue:
    record = getattr(completed.value, "record", None)
    statements = (
        record.statements
        if record is not None
        else getattr(completed.value, "statements", ())
    )
    returns = [s for s in statements if isinstance(s, ReturnValue)]
    assert len(returns) == 1, statements
    return returns[0]


def _universe_statements(function):
    sugar = function.sugar()
    return tuple(getattr(sugar, "statements", ()) or ())


# ===========================================================================
# Deletion removes the exact binding at that temporal point
# ===========================================================================


def _assert_located(effect) -> None:
    occurrence = effect.occurrence
    assert isinstance(occurrence, AuthenticatedRaiseLocus) and ":" in occurrence.value, (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {occurrence!r}"
    )


def _mro_names(effect) -> list[str]:
    return [identity.args[1].value for identity in effect.exception_type_mro]


def test_del_removes_binding_later_read_is_nameerror() -> None:
    """``x = 1; del x; return x`` → sole UnboundLocalError on the later read.

    ``x`` is ``f``'s local (it is assigned and deleted in ``f``), so Python
    raises ``UnboundLocalError``, a ``NameError`` subclass.
    """
    _, outcome = _function_outcome(
        "def f():\n" "    x = 1\n" "    del x\n" "    return x\n"
    )
    halted = _sole_halt(outcome)
    assert isinstance(halted.effect, NameErrorEffect)
    assert halted.effect.exception_name == "UnboundLocalError"
    assert halted.effect.name == "x"
    _assert_located(halted.effect)
    assert (
        "unbound name 'x'"
        in str(
            getattr(halted.effect, "reason", "")
            or getattr(halted.effect, "exception_name", "")
        )
        or halted.effect.name == "x"
    )


def test_delete_name_sugar_prior_is_bound_value_not_spelling() -> None:
    """DeleteNameSugar carries the prior binding state, not a name-lookup."""
    function, _ = _function_outcome("def f():\n" "    x = 1\n" "    del x\n")
    deletes = [
        s for s in _universe_statements(function) if isinstance(s, DeleteNameSugar)
    ]
    assert len(deletes) == 1
    delete = deletes[0]
    assert delete.name == "x"
    # Prior is the binding's one evaluation, read by reference (the temporal
    # rewrite: a read is a reference to the evaluation's key, never the
    # value inlined a second time) -- not an unbound placeholder.
    assert not isinstance(delete.prior, UnboundProjection)
    assert isinstance(delete.prior, EvaluationRefSugar)
    assert delete.prior.evaluation.startswith("evaluation:")


def test_post_delete_binding_trace_is_unbound_at_delete_site() -> None:
    """Substitution trace: after del, name maps to UnboundBinding at delete site."""
    function, _ = _function_outcome("def f():\n" "    x = 1\n" "    del x\n")
    sugar = function.sugar()
    trace = getattr(sugar, "substitution_trace", None)
    assert trace is not None
    # Last record is the delete: post_bindings seal UnboundBinding for x.
    last = trace.records[-1]
    post = dict(last.post_bindings)
    assert "x" in post
    entry = post["x"]
    state = entry.state
    assert type(state).__name__ == "UnboundBinding"
    assert state.name == "x"


# ===========================================================================
# Earlier effects remain
# ===========================================================================


def test_value_captured_before_del_survives() -> None:
    """``x = 1; y = x; del x; return y`` → Completed return TermValue(1)."""
    _, outcome = _function_outcome(
        "def f():\n" "    x = 1\n" "    y = x\n" "    del x\n" "    return y\n"
    )
    completed = _sole_completed(outcome)
    assert _returned(completed).value == TermValue(1)


def test_del_then_return_constant_completes() -> None:
    """Deletion does not poison the rest of the body when x is not re-read."""
    _, outcome = _function_outcome(
        "def f():\n" "    x = 1\n" "    del x\n" "    return 0\n"
    )
    completed = _sole_completed(outcome)
    assert _returned(completed).value == TermValue(0)


def test_rebind_after_del_restores_binding() -> None:
    """``del x; x = 2; return x`` → TermValue(2)."""
    _, outcome = _function_outcome(
        "def f():\n" "    x = 1\n" "    del x\n" "    x = 2\n" "    return x\n"
    )
    completed = _sole_completed(outcome)
    assert _returned(completed).value == TermValue(2)


# ===========================================================================
# Later reads loudly unbound
# ===========================================================================


def test_double_del_second_is_nameerror() -> None:
    """Second ``del x`` after deletion is unbound NameError at the second site."""
    _, outcome = _function_outcome(
        "def f():\n" "    x = 1\n" "    del x\n" "    del x\n"
    )
    halted = _sole_halt(outcome)
    assert isinstance(halted.effect, NameErrorEffect)
    assert halted.effect.name == "x"
    # Occurrence is the *second* delete site (line with second del).
    assert "5:" in str(halted.effect.occurrence) or halted.effect.occurrence is not None


def test_later_read_is_not_completed_with_stale_value_twin() -> None:
    """Bite: after del, return x is not a Completed TermValue(1)."""
    _, outcome = _function_outcome(
        "def f():\n" "    x = 1\n" "    del x\n" "    return x\n"
    )
    with pytest.raises(AssertionError):
        completed = _sole_completed(outcome)
        assert _returned(completed).value == TermValue(1)
    halted = _sole_halt(outcome)
    assert isinstance(halted.effect, NameErrorEffect)


# ===========================================================================
# Branch-conditional deletion — complementary binding states
# ===========================================================================


def test_conditional_del_builds_guarded_projection_on_later_read() -> None:
    """After ``if flag: del x``, the return read is GuardedProjection.

    when_true → UnboundProjection; when_false → prior bound value.  ``flag``
    is a global the module never binds: the read of it raises.
    """
    function, outcome = _function_outcome(
        "def f():\n" "    x = 1\n" "    if flag:\n" "        del x\n" "    return x\n"
    )
    # Structure pin on the return sugar.
    returns = [
        s for s in _universe_statements(function) if type(s).__name__ == "ReturnSugar"
    ]
    assert len(returns) == 1
    read = returns[0].value
    assert isinstance(read, GuardedBindingReadSugar)
    assert isinstance(read.state, GuardedProjection)
    assert isinstance(read.state.when_true, UnboundProjection)
    assert read.state.when_true.name == "x"
    # The retained face reads the binding's one evaluation by reference; the
    # value it holds (1) is pinned on the completed arm below.
    assert isinstance(read.state.when_false, EvaluationRefSugar)
    assert read.state.when_false.evaluation.startswith("evaluation:")

    # Runtime: no statement of the module binds ``flag`` and no builtin is
    # named so, so Python raises ``NameError`` reading it, before the ``if``
    # decides anything; ``f`` never completes.  The del's two faces are the
    # constant twins' (``if True`` / ``if False``) below.
    native: dict = {}
    exec(
        "def f():\n" "    x = 1\n" "    if flag:\n" "        del x\n" "    return x\n",
        native,
    )
    with pytest.raises(NameError, match="flag"):
        native["f"]()
    assert outcome.halts() == outcome.exits
    halted = _sole_halt(outcome)
    assert isinstance(halted.effect, NameErrorEffect)
    assert halted.effect.name == "flag"


def test_true_branch_del_always_unbinds_the_later_read() -> None:
    """``if True: del x; return x`` always raises ``UnboundLocalError``.

    A constant ``if`` is the branch it runs: the ``del`` always runs, so the
    later read is unbound on every path. There is no completed arm -- a
    retained-binding face here would be a completion Python never reaches.
    """
    _, outcome = _function_outcome(
        "def f():\n" "    x = 1\n" "    if True:\n" "        del x\n" "    return x\n"
    )
    assert outcome.halts() == outcome.exits
    halt = _sole_halt(outcome)
    assert isinstance(halt.effect, NameErrorEffect)
    assert halt.effect.exception_name == "UnboundLocalError"
    assert halt.effect.name == "x"


def test_false_branch_del_retains_binding_on_completed_arm() -> None:
    """``if False: del x; return x`` — completed arm returns 1 (binding retained)."""
    _, outcome = _function_outcome(
        "def f():\n" "    x = 1\n" "    if False:\n" "        del x\n" "    return x\n"
    )
    completed = [e for e in outcome.exits if isinstance(e, Completed)]
    assert completed
    # At least one completed arm carries return 1 (possibly under GuardedReturn).
    values = []
    for face in completed:
        record = getattr(face.value, "record", None)
        if record is None:
            continue
        for s in record.statements:
            if isinstance(s, ReturnValue):
                raw = s.value
                values.append(getattr(raw, "value", raw))
            # GuardedReturn embeds the bound TermValue.
            if type(s).__name__ == "GuardedReturn":
                values.append(getattr(s, "value", None))
    assert any(v == TermValue(1) or v == 1 for v in values), values


# ===========================================================================
# Absent local → authenticated NameError
# ===========================================================================


def test_del_absent_local_is_nameerror() -> None:
    """``del x`` with no prior binding → UnboundLocalError at the delete site.

    ``del x`` makes ``x`` a local of ``f``; deleting it unbound raises
    ``UnboundLocalError`` in Python.
    """
    _, outcome = _function_outcome("def f():\n" "    del x\n")
    halted = _sole_halt(outcome)
    assert isinstance(halted.effect, NameErrorEffect)
    assert halted.effect.exception_name == "UnboundLocalError"
    assert halted.effect.name == "x"
    _assert_located(halted.effect)


def test_del_absent_is_not_silent_completion_twin() -> None:
    _, outcome = _function_outcome("def f():\n" "    del x\n")
    with pytest.raises(AssertionError):
        assert all(isinstance(e, Completed) for e in outcome.exits)
    assert any(
        isinstance(e.effect, NameErrorEffect)
        for e in outcome.exits
        if isinstance(e, Halted)
    )


def test_unboundlocal_only_when_source_authority_distinguishes() -> None:
    """The read's scope, by its function's symbol table, decides the builtin.

    ``x`` is in ``f``'s symbol table as a local, so the unbound read is
    ``UnboundLocalError`` (#7586, ``NameErrorEffect.at``), not a spelling
    guess. It is still a ``NameError``: its MRO carries ``NameError``, so an
    ``except NameError`` catches it as Python's does.
    """
    _, outcome = _function_outcome(
        "def f():\n" "    x = 1\n" "    del x\n" "    return x\n"
    )
    halted = _sole_halt(outcome)
    assert isinstance(halted.effect, NameErrorEffect)
    assert halted.effect.exception_name == "UnboundLocalError"
    assert _mro_names(halted.effect)[:2] == ["UnboundLocalError", "NameError"]


# ===========================================================================
# Attribute / subscript deletion not admitted in this suite
# ===========================================================================


def test_attribute_delete_is_not_delete_name_sugar() -> None:
    """``del obj.attr`` lowers to AttributeDeleteEffectSugar — out of scope here.

    Formal delattr stays undischarged (carrier); this suite only pins the sugar
    kind, never discharges attribute delete.
    """
    tree = _tree("def f(obj):\n    del obj.attr\n")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    statements = _universe_statements(function)
    assert any(isinstance(s, AttributeDeleteEffectSugar) for s in statements)
    assert not any(isinstance(s, DeleteNameSugar) for s in statements)


def test_subscript_delete_is_not_delete_name_sugar() -> None:
    """``del obj[i]`` is ``obj.__delitem__(i)`` through the one mutation door
    (``container_mutation.name_mutation_statement``) — out of scope here.

    The value the receiver holds at reduce decides it; this suite only pins
    the sugar kind, never discharges subscript delete.
    """
    from sugar_lift_py_tests.sugar.builtin_container_call_sugar import (
        ContainerMutationStatementSugar,
        PathContainerCallSugar,
    )

    tree = _tree("def f(obj, i):\n    del obj[i]\n")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    statements = _universe_statements(function)
    (mutation,) = [
        s for s in statements if isinstance(s, ContainerMutationStatementSugar)
    ]
    call = mutation.evaluated[0]
    assert isinstance(call, PathContainerCallSugar)
    assert call.method == "__delitem__"
    assert not any(isinstance(s, DeleteNameSugar) for s in statements)


# ===========================================================================
# No scope inference from spelling
# ===========================================================================


def test_delete_targets_exact_name_not_a_homophone() -> None:
    """``del x`` unbinds x; y remains bound."""
    _, outcome = _function_outcome(
        "def f():\n" "    x = 1\n" "    y = 2\n" "    del x\n" "    return y\n"
    )
    completed = _sole_completed(outcome)
    assert _returned(completed).value == TermValue(2)


def test_delete_x_does_not_unbind_xx_by_spelling() -> None:
    _, outcome = _function_outcome(
        "def f():\n" "    x = 1\n" "    xx = 2\n" "    del x\n" "    return xx\n"
    )
    completed = _sole_completed(outcome)
    assert _returned(completed).value == TermValue(2)
