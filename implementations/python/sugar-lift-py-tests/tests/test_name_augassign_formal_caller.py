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
from pathlib import Path

import pytest

from frame_fresh import fresh
from sugar_lift_py_tests.caller_parameter_contract import (
    NativeOperationExitCarrierV1,
    project_iadd,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect import CoverageGapEffect
from sugar_lift_py_tests.floor import ScopeRebind, TermValue
from sugar_lift_py_tests.floor.floor_value import FloorValue
from sugar_lift_py_tests.floor.list_value import ListValue
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_py_tests.sugar.augassign_sugar import (
    AttributeAugAssignSugar,
    AugAssignSugar,
    project_augmented,
)
from sugar_lift_py_tests.sugar.builtin_container_call_sugar import (
    ContainerMutationStatementSugar,
    PathContainerCallSugar,
)
from sugar_lift_py_tests.sugar.function_universe_sugar import reduce_block_to_exitset
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import AugAssign, FunctionDef
from sugar_source_tree.operators import Add, BinaryOperator
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
    # ``x += e`` off the substituted function body is the one mutation door's
    # statement (#7757); its in-place call carries the operator.
    stmt = function.sugar().statements[0]
    assert isinstance(stmt, ContainerMutationStatementSugar), type(stmt)
    call = stmt.evaluated[0]
    assert isinstance(call, PathContainerCallSugar), type(call)
    return function, call


def _row_outcome(body: str, bound: str):
    """``f``'s own contract row (``function_universe_outcome``), with ``x``
    bound to ``bound`` in the body before ``body`` runs.

    A same-file call ``f(3)`` is its coordinate and edge, joined at prove
    (#7757 steps 5 and 6, #8705): the lifter no longer applies ``f``'s body
    at the call, so what the update does to the binding is read off the row
    of a body that binds ``x`` itself.  The formal's own discharge is
    ``test_authenticated_formal_discharge_updates_binding``."""
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    source = f"def f():\n    x = {bound}\n{body}\n"
    tree = _tree(source, "row.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function_universe_outcome(function)


def _returned_value(outcome):
    """The value the one completed face of ``outcome`` returned."""
    from sugar_lift_py_tests.floor.named_expression_value import peel_walrus_binds

    assert isinstance(outcome, ExitSet), type(outcome)
    assert len(outcome.exits) == 1
    face = outcome.exits[0]
    assert isinstance(face, Completed), type(face)
    _carried, value = peel_walrus_binds(face.value)
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


def _workspace_tree(tmp_path: Path, source: str, name: str) -> SourceFile:
    """``source`` seated as ``name`` under the workspace ``tmp_path``: each
    definition names its join symbol (``bridge_source_symbol``), as every
    lifted file's does."""
    from sugar_lift_py_tests.lift_rpc import tree_construction_context_for_workspace
    from sugar_lift_python_source.source_oracle import workspace_path_source

    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return SourceFile(
        workspace_path_source(str(path), root=str(tmp_path)),
        construction_context=tree_construction_context_for_workspace(tmp_path),
    )


def _caller_returned(source: str, tree: SourceFile | None = None):
    """What the first function of ``source`` returns on the face where its
    call of the helper completes, reduced as its own universe.  The call is
    its coordinate and edge (#8705): it completes under its ``completes``
    atom and halts under the complement, so the row has one completed face."""
    from sugar_lift_py_tests.floor.return_value import ReturnValue
    from sugar_lift_py_tests.floor.universe_value import UniverseValue
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    if tree is None:
        tree = _tree(source, "caller_reads_after.py")
    caller = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    outcome = function_universe_outcome(caller)
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert len(completed) == 1, outcome
    universe = completed[0].value
    assert isinstance(universe, UniverseValue), universe
    (returned,) = [
        entry for entry in universe.record.statements if isinstance(entry, ReturnValue)
    ]
    return returned.value


@dataclass(frozen=True)
class _FloorSugar(Sugar):
    value: object

    def desugar(self, ctx=None):
        del ctx
        return ExitSet.completed(self.value)

    @classmethod
    def witnesses(cls):
        return ()


def _production_sites():
    _, sugar = _aug_sugar()
    return sugar.operator_site, sugar.site


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
    assert isinstance(sugar, PathContainerCallSugar)
    assert sugar.method == "__iadd__"
    assert type(sugar.operator).inplace_operator == "iadd"
    assert type(sugar.operator).inplace_operator == Add.inplace_operator
    assert sugar.operator.project_inplace.__func__ is BinaryOperator.project_inplace
    assert sugar.label == "x"
    assert sugar.operator_site is not None
    assert sugar.site is not None
    assert sugar.operator_site is not sugar.site


def test_discrimination_name_path_is_not_store_target_sugar() -> None:
    _, sugar = _aug_sugar()
    assert not isinstance(sugar, AttributeAugAssignSugar)
    assert sugar.method != "__setitem__"


def test_op_site_is_structural_gap_for_name_target() -> None:
    function, sugar = _aug_sugar("def f(x):\n    x += 1\n")
    aug = next(n for n in function.body if isinstance(n, AugAssign))
    op_site = sugar.operator_site
    text = op_site.unit.source[op_site.span.start : op_site.span.end]
    assert "+=" in text
    assert op_site is not aug.value.fragment


# ---------------------------------------------------------------------------
# REAL reproducer 1: divergent iadd / add — rebind owns iadd result
# ---------------------------------------------------------------------------


def test_rebind_uses_iadd_result_when_iadd_and_add_diverge() -> None:
    """Species where ``__iadd__`` and ``__add__`` disagree: rebind follows iadd."""

    class _Divergent(FloorValue):
        def inplace_binary_operator_with(self, operation, ctx):
            del operation, ctx
            return ExitSet.completed(TermValue(99))

        def add(self, other, site, ctx):
            del other, site, ctx
            return ExitSet.completed(TermValue(1))

    out = _production_name_aug(_Divergent(), TermValue(0)).desugar(None)
    rebind = out.completed_value()
    assert rebind is not None, out
    assert isinstance(rebind, ScopeRebind), type(rebind)
    assert rebind.name == "x"
    assert rebind.value == TermValue(99)
    # Discrimination: must not have rebound to ordinary add's answer.
    with pytest.raises(AssertionError):
        assert rebind.value == TermValue(1)


def test_discrimination_add_alone_is_not_the_name_rebind() -> None:
    """Lying twin: if rebind were _make_binop/add, divergent species would bind 1."""

    class _Divergent(FloorValue):
        def inplace_binary_operator_with(self, operation, ctx):
            del operation, ctx
            return ExitSet.completed(TermValue(99))

        def add(self, other, site, ctx):
            del other, site, ctx
            return ExitSet.completed(TermValue(1))

    # Ordinary add (the old substitute binding) would yield 1.
    add_out = _Divergent().add(TermValue(0), "site", None)
    assert add_out.completed_value() == TermValue(1)
    # Name AugAssign must not match that.
    rebind = (
        _production_name_aug(_Divergent(), TermValue(0)).desugar(None).completed_value()
    )
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
            return ExitSet.completed(TermValue(2))

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
    rebind = out.completed_value()
    assert isinstance(rebind, ScopeRebind)
    assert rebind.value == TermValue(5)
    assert box["n"] == 1


def test_discrimination_double_rhs_eval_is_detected() -> None:
    box = {"n": 0}

    @dataclass(frozen=True)
    class _CountingRhs(Sugar):
        def desugar(self, ctx=None):
            del ctx
            box["n"] += 1
            return ExitSet.completed(TermValue(1))

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
    face = ExitSet.halted(
        CoverageGapEffect(boundary="iadd", reason="authenticated inplace halt")
    )

    class _Halt(FloorValue):
        def inplace_binary_operator_with(self, operation, ctx):
            del operation, ctx
            return face

        def add(self, other, site, ctx):
            del other, site, ctx
            return ExitSet.completed(TermValue(0))

    out = _production_name_aug(_Halt(), TermValue(1)).desugar(None)
    # The statement's outcome is that halt and nothing else: the same effect
    # under the same guard, and no arm completes, so nothing rebinds.  It is
    # composed through the one sequencing, so it is equal, not the same object.
    assert out == face
    assert out.halts() == out.exits
    assert not isinstance(out.completed_value(), ScopeRebind)


def test_raise_value_halt_blocks_rebind() -> None:
    """A halted face from inplace must not continue into ScopeRebind."""
    face = ExitSet.halted(
        CoverageGapEffect(boundary="iadd", reason="type error before rebind")
    )

    class _Raise(FloorValue):
        def inplace_binary_operator_with(self, operation, ctx):
            del operation, ctx
            return face

        def add(self, other, site, ctx):
            del other, site, ctx
            return ExitSet.completed(TermValue(0))

    out = _production_name_aug(_Raise(), TermValue(1)).desugar(None)
    assert out == face
    assert out.halts() == out.exits
    assert not isinstance(out.completed_value(), ScopeRebind)


def test_halt_blocks_tail_read_of_partial_update() -> None:
    """Through reduce_block: iadd halt leaves temporal unbound for the name."""
    from sugar_lift_py_tests.context import ReduceContext

    face = ExitSet.halted(CoverageGapEffect(boundary="iadd", reason="halt before rebind"))

    class _Halt(FloorValue):
        def inplace_binary_operator_with(self, operation, ctx):
            del operation, ctx
            return face

        def add(self, other, site, ctx):
            return ExitSet.completed(TermValue(0))

    @dataclass(frozen=True)
    class _ReadName(Sugar):
        def desugar(self, ctx=None):
            temporal = getattr(ctx, "temporal", None) if ctx is not None else None
            if temporal is not None:
                bound = temporal.value_if_bound("x")
                if bound is not None:
                    return ExitSet.completed(bound)
            return ExitSet.completed(TermValue(-1))  # sentinel: no rebind happened

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
                    return ExitSet.completed(bound)
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
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    # No caller actual: the iadd is the cited unanswered face (#7825).
    exits = pending.discharge(None, {})
    assert pending.unanswered_call() in owed_calls(exits)
    assert exits.completed_value() is None


def test_authenticated_formal_discharge_updates_binding() -> None:
    function, pending = _helper_definition()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "iadd"
    coords = {
        c.declared_name: c.coordinate_cid for c in function.sugar().formal_coordinates
    }
    exits = pending.discharge(
        None, {coords["x"]: TermValue(3), coords["rhs"]: TermValue(4)}
    )
    assert isinstance(exits, ExitSet)
    assert len(exits.exits) == 1
    assert isinstance(exits.exits[0], Completed)
    from sugar_lift_py_tests.floor.return_value import ReturnValue

    record = exits.exits[0].value.record
    rets = [s for s in record.statements if isinstance(s, ReturnValue)]
    assert rets and rets[-1].value == TermValue(7)


def test_binding_update_return_sees_augmented_value() -> None:
    """``x += 2; return x`` with x=3 → 5."""
    outcome = _row_outcome("    x += 2\n    return x\n", "3")
    returned = _returned_value(outcome)
    assert returned == TermValue(5)


def test_discrimination_successful_update_is_not_prior_value() -> None:
    outcome = _row_outcome("    x += 2\n    return x\n", "3")
    returned = _returned_value(outcome)
    assert returned == TermValue(5)
    with pytest.raises(AssertionError):
        assert returned == TermValue(3)


# ---------------------------------------------------------------------------
# A rebind of a formal is the callee's local; a mutation of a shared object
# is the caller's too (#7757).  The call is its coordinate and edge (#8705):
# the caller reads its objects as the one exposure rule leaves them
# (``ReceiverAfterCall``): an immutable value is kept, a mutable one the call
# may change is unknown until prove joins the callee's post-call state
# (#7757 step 7).  The tests that read the writes a followed frame carried
# out under ``actual:<index>`` (``caller_visible_values``) were deleted with
# that projection (#8739).
# ---------------------------------------------------------------------------


def test_a_caller_name_keeps_its_immutable_value_after_the_call() -> None:
    """The caller's ``n`` is bound to ``3`` and handed to a helper that
    rebinds its formal: ``n`` reads ``3`` after the call, never ``5``."""
    returned = _caller_returned(
        "def f():\n"
        "    n = 1 + 2\n"
        "    g(n)\n"
        "    return n\n"
        "def g(x):\n"
        "    x += 2\n"
    )
    assert returned == TermValue(3)
    with pytest.raises(AssertionError):
        assert returned == TermValue(5)


_EXTENDS_IN_PLACE = (
    "def f():\n"
    "    acc = [1]\n"
    "    g(acc)\n"
    "    return acc\n"
    "def g(x):\n"
    "    x += [2]\n"
)


def test_a_caller_name_reads_the_list_its_helper_extended_in_place(
    tmp_path: Path,
) -> None:
    """The same helper shape on a list: the caller's ``acc`` is the object
    the helper's ``x += [2]`` changes.

    Expected value changed (#7757 steps 5 and 6, #8705): it was ``[1, 2]``,
    read off the followed body.  On the call's completed face the list reads
    as the formal ``g``'s binder bound it to, after the call
    (``python:after(<call result>, "x")``, keyed on the call, #7757 step 7,
    #8796: ``g(acc)`` is a simple statement that runs the call once), never
    the ``[1]`` before it; prove decides it once the callee's contract
    states what ``x += [2]`` left in ``x``.  The file is seated under a
    workspace so ``g`` names its join symbol: the record of what the call
    left is bound only for a callee the edge joins
    (``lambda_callable.definition_edge_call``'s ``after_labels``)."""
    from sugar_lift_py_tests.floor import SymbolicValue

    returned = _caller_returned(
        _EXTENDS_IN_PLACE,
        _workspace_tree(tmp_path, _EXTENDS_IN_PLACE, "caller_reads_after.py"),
    )
    assert isinstance(returned, SymbolicValue), returned
    assert returned.term.name == "python:after", returned
    assert returned.term.args[0].name == "python:call_result", returned
    assert returned.term.args[1].value == "x", returned
    assert returned != fresh(ListValue, (TermValue(1),))


def test_a_caller_name_after_a_helper_no_edge_joins_stays_undecided() -> None:
    """With no workspace root ``g`` names no join symbol: its call joins no
    contract (``definition_edge_call``: no symbol, no ``after_labels``), so
    nothing can state what it left in ``acc``.  The list is the undecided
    value after the call (``python:receiver_after_call``, #7757 step 7,
    #8796), never the ``[1]`` before it."""
    from sugar_lift_py_tests.floor import SymbolicValue

    returned = _caller_returned(_EXTENDS_IN_PLACE)
    assert isinstance(returned, SymbolicValue), returned
    assert returned.term.name == "python:receiver_after_call", returned
    assert returned.term.args[1].value == "acc", returned
    assert returned != fresh(ListValue, (TermValue(1),))


def test_arithmetic_halt_is_not_completed_return_of_prior_binding() -> None:
    """``x += None`` TypeError — not Completed return of pre-update x."""
    outcome = _row_outcome("    x += None\n    return x\n", "3")
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
    assert type(sugar.operator).inplace_operator == Add.inplace_operator
    assert sugar.operator.project_inplace.__func__ is BinaryOperator.project_inplace


def test_project_augmented_formal_mints_iadd_not_add() -> None:
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )
    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
    from sugar_lift_py_tests.ir import PrimitiveSort, make_var

    _, sugar = _aug_sugar()
    site = sugar.operator_site
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
        left, right, operator="iadd", projector=project_iadd, site=site, ctx=None
    )
    assert isinstance(out, NativeOperationExitCarrierV1)
    assert out.demand.operator == "iadd"
    with pytest.raises(AssertionError):
        assert out.demand.operator == "add"
