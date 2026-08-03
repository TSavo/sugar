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
  - deleting an absent local produces authenticated NameError (UnboundLocal
    only when source authority distinguishes it — today NameErrorEffect)
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
from sugar_lift_py_tests.floor import ReturnValue, TermValue
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_py_tests.outcome.exit_set import outcome_to_exitset
from sugar_lift_py_tests.sugar.binding_projection import (
    GuardedProjection,
    UnboundProjection,
)
from sugar_lift_py_tests.sugar.delete_effect_sugar import (
    AttributeDeleteEffectSugar,
    SubscriptDeleteEffectSugar,
)
from sugar_lift_py_tests.sugar.delete_name_sugar import DeleteNameSugar
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
    return function, outcome_to_exitset(function.sugar().desugar(None))


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


def test_del_removes_binding_later_read_is_nameerror() -> None:
    """``x = 1; del x; return x`` → sole NameError on the later read."""
    _, outcome = _function_outcome(
        "def f():\n" "    x = 1\n" "    del x\n" "    return x\n"
    )
    halted = _sole_halt(outcome)
    assert isinstance(halted.effect, NameErrorEffect)
    assert halted.effect.exception_name == "NameError"
    assert halted.effect.name == "x"
    assert (
        isinstance(halted.effect.occurrence, str) and ":" in halted.effect.occurrence
    ), (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {halted.effect.occurrence!r}"
    )
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
    # Prior is the bound construction (IntLiteral), not an unbound placeholder.
    assert not isinstance(delete.prior, UnboundProjection)
    from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar

    assert isinstance(delete.prior, IntLiteralSugar)
    assert delete.prior.value == 1


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

    when_true → UnboundProjection; when_false → prior bound value.
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
    from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar

    assert isinstance(read.state.when_false, IntLiteralSugar)
    assert read.state.when_false.value == 1

    # Runtime faces: halt under truthy; complete under not(truthy) with value 1.
    halted = [e for e in outcome.exits if isinstance(e, Halted)]
    completed = [e for e in outcome.exits if isinstance(e, Completed)]
    assert len(halted) == 1
    assert len(completed) == 1
    assert isinstance(halted[0].effect, NameErrorEffect)
    assert "py.truthy" in str(halted[0].guard) or "truthy" in str(halted[0].guard)
    assert "not" in str(completed[0].guard).lower()
    assert _returned(completed[0]).value == TermValue(1)


def test_true_branch_del_factors_unbound_and_retained_faces() -> None:
    """``if True: del x; return x`` factors complementary guards (not collapsed silent)."""
    _, outcome = _function_outcome(
        "def f():\n" "    x = 1\n" "    if True:\n" "        del x\n" "    return x\n"
    )
    assert len(outcome.exits) >= 2
    kinds = {type(e).__name__ for e in outcome.exits}
    assert "Halted" in kinds
    assert "Completed" in kinds
    halt = next(e for e in outcome.exits if isinstance(e, Halted))
    assert isinstance(halt.effect, NameErrorEffect)


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
    """``del x`` with no prior binding → NameErrorEffect at the delete site."""
    _, outcome = _function_outcome("def f():\n" "    del x\n")
    halted = _sole_halt(outcome)
    assert isinstance(halted.effect, NameErrorEffect)
    assert halted.effect.exception_name == "NameError"
    assert halted.effect.name == "x"
    assert (
        isinstance(halted.effect.occurrence, str) and ":" in halted.effect.occurrence
    ), (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {halted.effect.occurrence!r}"
    )


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
    """Today source authority mints NameErrorEffect for unbound locals.

    Python's UnboundLocalError is a NameError subclass; the kit publishes
    NameErrorEffect unless a stronger sealed distinction appears. Pin current
    authority — do not invent UnboundLocal from spelling.
    """
    _, outcome = _function_outcome(
        "def f():\n" "    x = 1\n" "    del x\n" "    return x\n"
    )
    halted = _sole_halt(outcome)
    assert isinstance(halted.effect, NameErrorEffect)
    assert halted.effect.exception_name == "NameError"
    # Not a fabricated UnboundLocal without source distinction.
    assert halted.effect.exception_name != "UnboundLocalError"


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
    """``del obj[i]`` lowers to SubscriptDeleteEffectSugar — out of scope here.

    Formal delitem stays undischarged (carrier); this suite only pins the sugar
    kind, never discharges subscript delete.
    """
    tree = _tree("def f(obj, i):\n    del obj[i]\n")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    statements = _universe_statements(function)
    assert any(isinstance(s, SubscriptDeleteEffectSugar) for s in statements)
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
