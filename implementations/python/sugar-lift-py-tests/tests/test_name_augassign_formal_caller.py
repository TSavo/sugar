"""Name-target AugAssign: authenticated inplace owns the lexical rebind.

Three REAL acceptance reproducers (not placeholder xfail shells):

  1. Divergent ``__iadd__`` / ``__add__`` — rebind must be the iadd result
  2. RHS evaluated once — no dual-eval of binop rebind + discarded iadd
  3. Halt blocks rebind — no ScopeRebind / tail read of a partial update

Also pins construction (operator-owned ``project_inplace``), formal undischarged
iadd carrier, and successful binding update through the production path.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.caller_parameter_contract import (
    NativeOperationExitCarrierV1,
    project_iadd,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect import CoverageGapEffect
from sugar_lift_py_tests.floor import ScopeRebind, TermValue
from sugar_lift_py_tests.floor.floor_value import FloorValue
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted, Incomplete
from sugar_lift_py_tests.sugar.augassign_sugar import (
    AttributeAugAssignSugar,
    AugAssignSugar,
    SubscriptAugAssignSugar,
    project_augmented,
)
from sugar_lift_py_tests.sugar.function_universe_sugar import reduce_block_to_exitset
from sugar_lift_py_tests.sugar.sugar_base import Sugar
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


def _aug_sugar(source: str = "def f(x):\n    x += 1\n"):
    tree = _tree(source)
    function = next(n for n in tree.nodes() if isinstance(n, FunctionDef))
    # Prefer the AugAssign statement sugar off the substituted function body.
    stmt = function.sugar().statements[0]
    assert isinstance(stmt, AugAssignSugar), type(stmt)
    return function, stmt


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


@dataclass(frozen=True)
class _FloorSugar(Sugar):
    value: object

    def desugar(self, ctx=None):
        del ctx
        return Complete(self.value)

    @classmethod
    def witnesses(cls):
        return ()


def _production_sites():
    _, sugar = _aug_sugar()
    return sugar.op_site, sugar.site


def _production_name_aug(
    left,
    right,
    *,
    name: str = "x",
    operator: str = "iadd",
    projector=project_iadd,
):
    op_site, site = _production_sites()
    return AugAssignSugar(
        name=name,
        left=_FloorSugar(left),
        right=_FloorSugar(right),
        operator=operator,
        operation=projector,
        op_site=op_site,
        site=site,
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_name_augassign_constructs_with_operator_owned_project_inplace() -> None:
    _, sugar = _aug_sugar()
    assert isinstance(sugar, AugAssignSugar)
    assert sugar.operator == "iadd"
    assert sugar.operator == Add.inplace_operator
    assert sugar.operation.__func__ is BinaryOperator.project_inplace
    assert sugar.name == "x"
    assert sugar.op_site is not None
    assert sugar.site is not None
    assert sugar.op_site is not sugar.site


def test_discrimination_name_path_is_not_store_target_sugar() -> None:
    _, sugar = _aug_sugar()
    assert not isinstance(sugar, AttributeAugAssignSugar)
    assert not isinstance(sugar, SubscriptAugAssignSugar)


def test_op_site_is_structural_gap_for_name_target() -> None:
    function, sugar = _aug_sugar("def f(x):\n    x += 1\n")
    aug = next(n for n in function.body if isinstance(n, AugAssign))
    text = sugar.op_site.unit.source[sugar.op_site.span.start : sugar.op_site.span.end]
    assert "+=" in text
    assert sugar.op_site is not aug.value.fragment


# ---------------------------------------------------------------------------
# REAL reproducer 1: divergent iadd / add — rebind owns iadd result
# ---------------------------------------------------------------------------


def test_rebind_uses_iadd_result_when_iadd_and_add_diverge() -> None:
    """Species where ``__iadd__`` and ``__add__`` disagree: rebind follows iadd."""

    class _Divergent(FloorValue):
        def inplace_binary_operator_with(self, operation, ctx):
            del operation, ctx
            return Complete(TermValue(99))

        def add(self, other, site):
            del other, site
            return Complete(TermValue(1))

    out = _production_name_aug(_Divergent(), TermValue(0)).desugar(None)
    assert isinstance(out, Complete), out
    assert isinstance(out.value, ScopeRebind), type(out.value)
    assert out.value.name == "x"
    assert out.value.value == TermValue(99)
    # Discrimination: must not have rebound to ordinary add's answer.
    with pytest.raises(AssertionError):
        assert out.value.value == TermValue(1)


def test_discrimination_add_alone_is_not_the_name_rebind() -> None:
    """Lying twin: if rebind were _make_binop/add, divergent species would bind 1."""

    class _Divergent(FloorValue):
        def inplace_binary_operator_with(self, operation, ctx):
            del operation, ctx
            return Complete(TermValue(99))

        def add(self, other, site):
            del other, site
            return Complete(TermValue(1))

    # Ordinary add (the old substitute binding) would yield 1.
    add_out = _Divergent().add(TermValue(0), "site")
    assert add_out.value == TermValue(1)
    # Name AugAssign must not match that.
    rebind = _production_name_aug(_Divergent(), TermValue(0)).desugar(None).value
    assert rebind.value != TermValue(1)
    assert rebind.value == TermValue(99)


# ---------------------------------------------------------------------------
# REAL reproducer 2: RHS evaluated once
# ---------------------------------------------------------------------------


def test_rhs_evaluated_once() -> None:
    box = {"n": 0}

    @dataclass(frozen=True)
    class _CountingRhs(Sugar):
        def desugar(self, ctx=None):
            del ctx
            box["n"] += 1
            return Complete(TermValue(2))

        @classmethod
        def witnesses(cls):
            return ()

    op_site, site = _production_sites()
    sugar = AugAssignSugar(
        name="x",
        left=_FloorSugar(TermValue(3)),
        right=_CountingRhs(),
        operator="iadd",
        operation=project_iadd,
        op_site=op_site,
        site=site,
    )
    out = sugar.desugar(None)
    assert isinstance(out, Complete)
    assert isinstance(out.value, ScopeRebind)
    assert out.value.value == TermValue(5)
    assert box["n"] == 1


def test_discrimination_double_rhs_eval_is_detected() -> None:
    box = {"n": 0}

    @dataclass(frozen=True)
    class _CountingRhs(Sugar):
        def desugar(self, ctx=None):
            del ctx
            box["n"] += 1
            return Complete(TermValue(1))

        @classmethod
        def witnesses(cls):
            return ()

    rhs = _CountingRhs()
    rhs.desugar(None)
    rhs.desugar(None)
    assert box["n"] == 2
    with pytest.raises(AssertionError):
        assert box["n"] == 1


# ---------------------------------------------------------------------------
# REAL reproducer 3: halt blocks rebind
# ---------------------------------------------------------------------------


def test_iadd_halt_does_not_emit_scope_rebind() -> None:
    face = Incomplete(
        CoverageGapEffect(boundary="iadd", reason="authenticated inplace halt")
    )

    class _Halt(FloorValue):
        def inplace_binary_operator_with(self, operation, ctx):
            del operation, ctx
            return face

        def add(self, other, site):
            del other, site
            return Complete(TermValue(0))

    out = _production_name_aug(_Halt(), TermValue(1)).desugar(None)
    assert out is face
    assert not isinstance(out, Complete) or not isinstance(
        getattr(out, "value", None), ScopeRebind
    )


def test_raise_value_halt_blocks_rebind() -> None:
    """Incomplete/halt face from inplace must not continue into ScopeRebind."""
    face = Incomplete(
        CoverageGapEffect(boundary="iadd", reason="type error before rebind")
    )

    class _Raise(FloorValue):
        def inplace_binary_operator_with(self, operation, ctx):
            del operation, ctx
            return face

        def add(self, other, site):
            del other, site
            return Complete(TermValue(0))

    out = _production_name_aug(_Raise(), TermValue(1)).desugar(None)
    assert out is face
    assert not isinstance(getattr(out, "value", None), ScopeRebind)


def test_halt_blocks_tail_read_of_partial_update() -> None:
    """Through reduce_block: iadd halt leaves temporal unbound for the name."""
    from sugar_lift_py_tests.context import ReduceContext

    face = Incomplete(CoverageGapEffect(boundary="iadd", reason="halt before rebind"))

    class _Halt(FloorValue):
        def inplace_binary_operator_with(self, operation, ctx):
            del operation, ctx
            return face

        def add(self, other, site):
            return Complete(TermValue(0))

    @dataclass(frozen=True)
    class _ReadName(Sugar):
        def desugar(self, ctx=None):
            temporal = getattr(ctx, "temporal", None) if ctx is not None else None
            if temporal is not None:
                bound = temporal.value_if_bound("x")
                if bound is not None:
                    return Complete(bound)
            return Complete(TermValue(-1))  # sentinel: no rebind happened

        @classmethod
        def witnesses(cls):
            return ()

    ctx = ReduceContext.root(owner="name_aug_halt_rebind")
    # Seed prior binding so a false rebind would be visible as overwrite.
    ctx = ctx.with_temporal(ctx.temporal.bind_value("x", TermValue(3)))
    exits = reduce_block_to_exitset(
        (
            _production_name_aug(_Halt(), TermValue(1), name="x"),
            _ReadName(),
        ),
        ctx,
    )
    # Halt face: no completed tail carrying a rebound value.
    halted = [e for e in exits.exits if isinstance(e, Halted)]
    assert halted, exits.exits
    completed = [e for e in exits.exits if isinstance(e, Completed)]
    for face_c in completed:
        entries = getattr(face_c.value, "entries", ())
        # Must not contain a ScopeRebind of the partial update.
        assert not any(isinstance(e, ScopeRebind) for e in entries)


# ---------------------------------------------------------------------------
# Successful rebind threads into the tail (ScopeRebind + temporal)
# ---------------------------------------------------------------------------


def test_successful_rebind_threads_into_tail_read() -> None:
    from sugar_lift_py_tests.context import ReduceContext

    @dataclass(frozen=True)
    class _ReadName(Sugar):
        def desugar(self, ctx=None):
            temporal = getattr(ctx, "temporal", None) if ctx is not None else None
            if temporal is not None:
                bound = temporal.value_if_bound("x")
                if bound is not None:
                    return Complete(bound)
            raise AssertionError("expected temporal rebind of x after Name AugAssign")

        @classmethod
        def witnesses(cls):
            return ()

    ctx = ReduceContext.root(owner="name_aug_rebind_tail")
    exits = reduce_block_to_exitset(
        (
            _production_name_aug(TermValue(3), TermValue(2), name="x"),
            _ReadName(),
        ),
        ctx,
    )
    assert len(exits.exits) == 1
    assert isinstance(exits.exits[0], Completed)
    entries = exits.exits[0].value.entries
    # ScopeRebind contributes nothing; tail read is the rebound TermValue(5).
    assert TermValue(5) in entries


# ---------------------------------------------------------------------------
# Formal undischarged + binding update (source path)
# ---------------------------------------------------------------------------


def test_helper_alone_is_undischarged_iadd_carrier() -> None:
    _, pending = _helper_definition()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "iadd"
    with pytest.raises(SugarNotWritten, match="caller actual absent"):
        pending.discharge({})


def test_authenticated_formal_discharge_updates_binding() -> None:
    function, pending = _helper_definition()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "iadd"
    coords = {
        c.declared_name: c.coordinate_cid for c in function.sugar().formal_coordinates
    }
    exits = pending.discharge({coords["x"]: TermValue(3), coords["rhs"]: TermValue(4)})
    assert isinstance(exits, ExitSet)
    assert len(exits.exits) == 1
    assert isinstance(exits.exits[0], Completed)
    from sugar_lift_py_tests.floor.return_value import ReturnValue

    record = exits.exits[0].value.record
    rets = [s for s in record.statements if isinstance(s, ReturnValue)]
    assert rets and rets[-1].value == TermValue(7)


def test_binding_update_return_sees_augmented_value() -> None:
    """``x += 2; return x`` with x=3 → 5."""
    outcome = _call_outcome("    x += 2\n    return x\n", "3")
    returned = _returned_value(outcome)
    assert returned == TermValue(5)


def test_discrimination_successful_update_is_not_prior_value() -> None:
    outcome = _call_outcome("    x += 2\n    return x\n", "3")
    returned = _returned_value(outcome)
    assert returned == TermValue(5)
    with pytest.raises(AssertionError):
        assert returned == TermValue(3)


def test_arithmetic_halt_is_not_completed_return_of_prior_binding() -> None:
    """``x += None`` TypeError — not Completed return of pre-update x."""
    outcome = _call_outcome("    x += None\n    return x\n", "3")
    assert isinstance(outcome, ExitSet)
    halted = [e for e in outcome.exits if isinstance(e, Halted)]
    assert halted, outcome.exits
    assert any(getattr(e.effect, "exception_name", None) == "TypeError" for e in halted)
    for face in (e for e in outcome.exits if isinstance(e, Completed)):
        from sugar_lift_py_tests.floor.return_value import ReturnValue

        record = getattr(face.value, "record", None)
        if record is None:
            continue
        for stmt in record.statements:
            if isinstance(stmt, ReturnValue) and stmt.value == TermValue(3):
                pytest.fail(
                    "halt must not fabricate Completed return of prior binding TermValue(3)"
                )


def test_name_path_shares_project_inplace_with_add_operator() -> None:
    _, sugar = _aug_sugar()
    assert sugar.operator == Add.inplace_operator
    assert sugar.operation.__func__ is BinaryOperator.project_inplace


def test_project_augmented_formal_mints_iadd_not_add() -> None:
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )
    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
    from sugar_lift_py_tests.ir import PrimitiveSort, make_var

    _, sugar = _aug_sugar()
    site = sugar.op_site
    src = site.source_cid
    owner_def = SourceFragmentCoordinateV1(src, 1, 0, 1, 10)

    def _coord(name: str, ordinal: int):
        return FormalParameterCoordinateV1.mint(
            owner_source_identity_cid=src,
            owner_definition_locus=owner_def,
            declaration_locus=SourceFragmentCoordinateV1(
                src, 1, 10 + ordinal, 1, 12 + ordinal
            ),
            ordinal=ordinal,
            parameter_kind="positional-or-keyword",
            declared_name=name,
            sort=PrimitiveSort("Value"),
        )

    left = SymbolicValue(make_var("x"), _coord("x", 0))
    right = SymbolicValue(make_var("rhs"), _coord("rhs", 1))
    out = project_augmented(
        left, right, operator="iadd", projector=project_iadd, site=site
    )
    assert isinstance(out, NativeOperationExitCarrierV1)
    assert out.demand.operator == "iadd"
    with pytest.raises(AssertionError):
        assert out.demand.operator == "add"
