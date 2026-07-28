"""Name-target AugAssign laws: ``x += rhs``.

Lexical rebind (not setattr/setitem):

  - binding update: after successful ``x OP= rhs``, later reads see the new value
  - halt preserves prior binding: arithmetic/RHS halt is the outcome — never a
    fabricated Completed return of the pre-update value
  - formal alone undischarged; authenticated discharge completes
  - arithmetic uses the same ``project_inplace`` / ``iadd`` substrate as
    attribute and subscript AugAssign (not bare BinOp ``add`` as a silent stand-in)

No second dispatch table; composition is outcome/carrier ``and_then`` only.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.caller_parameter_contract import (
    NativeOperationExitCarrierV1,
    project_iadd,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted
from sugar_lift_py_tests.sugar.augassign_sugar import AugAssignSugar
from sugar_lift_py_tests.sugar.binop_sugar import BinOpSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import AugAssign, Call, FunctionDef
from sugar_source_tree.operators import Add, BinaryOperator
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _tree(source: str, name: str = "name_augassign.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _helper_definition(
    source: str = "def helper(x, rhs):\n    x += rhs\n    return x\n",
):
    tree = _tree(source, "helper_alone.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function, function.sugar().desugar(None)


def _call_outcome(body: str, actuals: str, signature: str = "x"):
    source = f"def f({signature}):\n{body}\n\nf({actuals})\n"
    tree = _tree(source, "call.py")
    call = tuple(node for node in tree.nodes() if isinstance(node, Call))[-1]
    return call.sugar().desugar(None)


def _returned_value(outcome):
    assert isinstance(outcome, ExitSet), type(outcome)
    assert len(outcome.exits) == 1
    face = outcome.exits[0]
    assert isinstance(face, Completed), type(face)
    value = face.value
    # CallSiteValue: force_floor materializes the body return.
    force = getattr(value, "force_floor", None)
    if callable(force):
        forced = force(None, owner="name_augassign_test")
        from sugar_lift_py_tests.floor.block_value import BlockValue
        from sugar_lift_py_tests.floor.return_value import ReturnValue

        if isinstance(forced, BlockValue):
            returns = [s for s in forced.statements if isinstance(s, ReturnValue)]
            assert returns, forced.statements
            return returns[-1].value
        return forced
    record = getattr(value, "record", None)
    if record is not None:
        from sugar_lift_py_tests.floor.return_value import ReturnValue

        returns = [s for s in record.statements if isinstance(s, ReturnValue)]
        if returns:
            return returns[-1].value
    return value


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_name_augassign_constructs_augassign_sugar_with_inplace_operator() -> None:
    tree = _tree("def f(x):\n    x += 1\n")
    function = next(n for n in tree.nodes() if isinstance(n, FunctionDef))
    stmt = function.sugar().statements[0]
    assert isinstance(stmt, AugAssignSugar)
    assert stmt.operator == "iadd"
    assert stmt.operation.__func__ is BinaryOperator.project_inplace
    assert isinstance(stmt.read_op, BinOpSugar) or hasattr(stmt, "left")
    # Distinct op site from statement when minted.
    assert stmt.op_site is not None
    assert stmt.site is not None


def test_discrimination_name_path_is_not_subscript_or_attribute_sugar() -> None:
    from sugar_lift_py_tests.sugar.augassign_sugar import (
        AttributeAugAssignSugar,
        SubscriptAugAssignSugar,
    )

    tree = _tree("def f(x):\n    x += 1\n")
    function = next(n for n in tree.nodes() if isinstance(n, FunctionDef))
    stmt = function.sugar().statements[0]
    assert isinstance(stmt, AugAssignSugar)
    assert not isinstance(stmt, AttributeAugAssignSugar)
    assert not isinstance(stmt, SubscriptAugAssignSugar)


# ---------------------------------------------------------------------------
# Binding update
# ---------------------------------------------------------------------------


def test_binding_update_return_sees_augmented_value() -> None:
    """``x += 2; return x`` with x=3 → 5."""
    outcome = _call_outcome("    x += 2\n    return x\n", "3")
    returned = _returned_value(outcome)
    assert returned == TermValue(5)


def test_authenticated_formal_discharge_updates_binding() -> None:
    function, pending = _helper_definition()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "iadd"
    coords = {
        c.declared_name: c.coordinate_cid
        for c in function.sugar().formal_coordinates
    }
    exits = pending.discharge(
        {coords["x"]: TermValue(3), coords["rhs"]: TermValue(4)}
    )
    assert isinstance(exits, ExitSet)
    assert len(exits.exits) == 1
    assert isinstance(exits.exits[0], Completed)
    from sugar_lift_py_tests.floor.return_value import ReturnValue

    record = exits.exits[0].value.record
    rets = [s for s in record.statements if isinstance(s, ReturnValue)]
    assert rets and rets[-1].value == TermValue(7)


# ---------------------------------------------------------------------------
# Halt preserves prior binding (no fabricated green with old value)
# ---------------------------------------------------------------------------


def test_arithmetic_halt_is_not_completed_return_of_prior_binding() -> None:
    """``x += None`` TypeError — not Completed return of pre-update x."""
    outcome = _call_outcome("    x += None\n    return x\n", "3")
    assert isinstance(outcome, ExitSet)
    # At least one Halted TypeError face; no sole Completed TermValue(3).
    halted = [e for e in outcome.exits if isinstance(e, Halted)]
    assert halted, outcome.exits
    assert any(
        getattr(e.effect, "exception_name", None) == "TypeError" for e in halted
    )
    completed = [e for e in outcome.exits if isinstance(e, Completed)]
    for face in completed:
        from sugar_lift_py_tests.floor.return_value import ReturnValue

        record = getattr(face.value, "record", None)
        if record is None:
            continue
        for stmt in record.statements:
            if isinstance(stmt, ReturnValue) and stmt.value == TermValue(3):
                pytest.fail(
                    "halt must not fabricate Completed return of prior binding TermValue(3)"
                )


def test_discrimination_successful_update_is_not_prior_value() -> None:
    """Positive twin: successful += must not equal the pre-update value alone."""
    outcome = _call_outcome("    x += 2\n    return x\n", "3")
    returned = _returned_value(outcome)
    assert returned == TermValue(5)
    with pytest.raises(AssertionError):
        assert returned == TermValue(3)


# ---------------------------------------------------------------------------
# Formal undischarged
# ---------------------------------------------------------------------------


def test_helper_alone_is_undischarged_iadd_carrier() -> None:
    _, pending = _helper_definition()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "iadd"
    with pytest.raises(SugarNotWritten, match="caller actual absent"):
        pending.discharge({})


def test_discrimination_helper_alone_is_not_completed_binding() -> None:
    _, pending = _helper_definition()
    with pytest.raises(AssertionError):
        assert isinstance(pending, Completed)


def test_partial_actuals_stay_undischarged() -> None:
    function, pending = _helper_definition()
    coords = {
        c.declared_name: c.coordinate_cid
        for c in function.sugar().formal_coordinates
    }
    with pytest.raises(SugarNotWritten, match="caller actual absent"):
        pending.discharge({coords["x"]: TermValue(1)})


# ---------------------------------------------------------------------------
# Substrate: same project_inplace as attr/subscript
# ---------------------------------------------------------------------------


def test_name_path_shares_project_inplace_with_add_operator() -> None:
    tree = _tree("def f(x):\n    x += 1\n")
    function = next(n for n in tree.nodes() if isinstance(n, FunctionDef))
    stmt = function.sugar().statements[0]
    assert stmt.operator == Add.inplace_operator
    assert stmt.operation.__func__ is BinaryOperator.project_inplace
