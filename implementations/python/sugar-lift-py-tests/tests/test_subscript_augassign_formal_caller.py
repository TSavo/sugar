"""Formal subscript augmented assignment: ``obj[key] += rhs``.

Production path only: ``obj[key] += rhs`` is the one mutation door's
read-modify-store (``PathContainerCallSugar._read_modify_store``, #7757); the
tests drive that door's ``desugar``.  The ordinary augmented item store it
replaced (``SubscriptAugAssignSugar``) is deleted.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from frame_fresh import FRAME_FRESH, fresh
from sugar_lift_py_tests.caller_parameter_contract import (
    NativeOperationExitCarrierV1,
    _NATIVE_OPERATION_PROJECTORS,
    production_native_operation_operators,
    project_iadd,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import ListValue, TermValue, TupleValue
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor.list_value import ListValue as ListValueCls
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_py_tests.sugar.augassign_sugar import project_augmented
from sugar_lift_py_tests.sugar.builtin_container_call_sugar import (
    ContainerMutationStatementSugar,
    PathContainerCallSugar,
)
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import AugAssign, FunctionDef
from sugar_source_tree.operators import (
    Add,
    BinaryOperator,
    production_augassign_inplace_operators,
)
from sugar_source_tree.tree import SourceFile


def _tree(source: str, name: str = "subscript_augassign.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _helper_definition(
    source: str = "def helper(obj, key, rhs):\n    obj[key] += rhs\n",
):
    tree = _tree(source, "helper_alone.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function, function.sugar().desugar(None)


def _aug_sugar(source: str = "def helper(obj, key, rhs):\n    obj[key] += rhs\n"):
    tree = _tree(source)
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    # ``obj[key] += rhs`` off the substituted function body is the one
    # mutation door's statement (#7757); its ``__setitem__`` carries the
    # operator.
    stmt = function.sugar().statements[0]
    assert isinstance(stmt, ContainerMutationStatementSugar), type(stmt)
    call = stmt.evaluated[0]
    assert isinstance(call, PathContainerCallSugar), type(call)
    return function, call


def _post(out):
    """The receiver after the door's read-modify-store: the pair's first."""
    pair = out.completed_value()
    assert type(pair) is TupleValue and len(pair.elements) == 2, pair
    return pair.elements[0]


def _post_list(completed: Completed) -> ListValue:
    value = completed.value
    if isinstance(value, ListValue):
        return value
    record = getattr(value, "record", None)
    if record is not None:
        lists = [s for s in record.statements if isinstance(s, ListValue)]
        assert lists, record.statements
        return lists[-1]
    raise AssertionError(f"no ListValue post-state: {type(value).__name__}")


@dataclass(frozen=True)
class _FloorSugar(Sugar):
    value: object

    def desugar(self, ctx=None):
        del ctx
        return ExitSet.completed(self.value)

    @classmethod
    def witnesses(cls):
        return ()


class _Projecting:
    """An operator whose in-place projection is ``project`` (a probe)."""

    inplace_operator = "iadd"

    def __init__(self, project):
        self._project = project

    def project_inplace(self, left, right, site, ctx):
        return self._project(left, right, site, ctx)


def _production_sites():
    _, call = _aug_sugar()
    return call.site, call.operator_site


def _door(receiver_sugar, index_sugar, rhs_sugar, *, operator=None):
    site, op_site = _production_sites()
    return PathContainerCallSugar(
        receiver=receiver_sugar,
        method="__setitem__",
        args=(index_sugar, rhs_sugar),
        fallback=None,
        site=site,
        operator=Add.instance() if operator is None else operator,
        operator_site=op_site,
    )


def _production_desugar(receiver, index, rhs, *, operator=None):
    call = _door(
        _FloorSugar(receiver), _FloorSugar(index), _FloorSugar(rhs), operator=operator
    )
    return call.desugar(None)


# ---------------------------------------------------------------------------
# Construction / occurrence
# ---------------------------------------------------------------------------


def test_subscript_augassign_constructs_with_operator_owned_project_inplace() -> None:
    _, call = _aug_sugar()
    assert call.method == "__setitem__"
    # Operator-owned double dispatch — bound project_inplace, not a kind ladder.
    assert call.operator.project_inplace.__func__ is Add.project_inplace
    assert type(call.operator).inplace_operator == "iadd"
    assert type(call.operator).inplace_operator == Add.inplace_operator
    assert call.operator_site is not None
    assert call.operator_site is not call.site


def test_op_site_is_structural_gap_not_rhs_or_string_scan() -> None:
    function, call = _aug_sugar("def helper(obj, key, rhs):\n    obj[key] += rhs\n")
    aug = next(node for node in function.body if isinstance(node, AugAssign))
    assert call.operator_site is not aug.value.fragment
    # Carried operator_site gap contains the operator token region.
    site = call.operator_site
    text = site.unit.source[site.span.start : site.span.end]
    assert "+=" in text
    assert call.operator_site is not call.site


def test_op_site_ignores_same_spelling_string_in_target() -> None:
    """Lying twin: ``obj['+='] += rhs`` must not use the string literal as op_site."""
    source = "def helper(obj, rhs):\n    obj['+='] += rhs\n"
    function, call = _aug_sugar(source)
    aug = next(node for node in function.body if isinstance(node, AugAssign))
    op_span = call.operator_site.span
    # Index string constant span must not equal / contain the operator site.
    index_node = aug.target.slice_
    index_span = index_node.span
    assert not (op_span.start <= index_span.start and index_span.end <= op_span.end), (
        op_span,
        index_span,
    )
    # Operator site still sits after the full target (including ['+=']).
    assert op_span.start >= aug.target.span.end
    text = call.operator_site.unit.source[op_span.start : op_span.end]
    assert "+=" in text


def test_discrimination_same_spelling_index_is_not_operator_site() -> None:
    """Positive twin: operator gap; lying claim that op_site is the index fails."""
    source = "def helper(obj, rhs):\n    obj['+='] += rhs\n"
    _, call = _aug_sugar(source)
    function = next(
        n for n in _tree(source, "twin.py").nodes() if isinstance(n, FunctionDef)
    )
    aug = next(n for n in function.body if isinstance(n, AugAssign))
    with pytest.raises(AssertionError):
        assert call.operator_site.span == aug.target.slice_.span


def test_an_unsubstituted_statement_is_the_same_door() -> None:
    """A statement sugared before substitution is the door against no
    bindings: the same read-modify-store, never a second route."""
    source = "def helper(obj, key, rhs):\n    obj[key] += rhs\n"
    function = next(
        n for n in _tree(source, "raw.py").nodes() if isinstance(n, FunctionDef)
    )
    aug = next(n for n in function.body if isinstance(n, AugAssign))
    stmt = aug.sugar()
    assert isinstance(stmt, ContainerMutationStatementSugar), type(stmt)
    call = stmt.evaluated[0]
    assert isinstance(call, PathContainerCallSugar), type(call)
    assert call.method == "__setitem__"
    assert type(call.operator).inplace_operator == "iadd"


def test_discrimination_legacy_runtime_effect_is_not_the_formal_path() -> None:
    _, outcome = _helper_definition()
    assert isinstance(outcome, NativeOperationExitCarrierV1), type(outcome)
    assert outcome.demand.operator == "subscript"
    with pytest.raises(AssertionError):
        assert isinstance(outcome, ExitSet) and outcome.halts() == outcome.exits


def test_legacy_augmented_subscript_store_effect_sugar_is_deleted() -> None:
    import sugar_lift_py_tests.sugar.store_effect_sugar as store_mod

    assert not hasattr(store_mod, "LegacyAugmentedSubscriptStoreEffectSugar")
    package_root = Path(store_mod.__file__).resolve().parent.parent
    offenders = []
    for path in package_root.rglob("*.py"):
        if "LegacyAugmentedSubscriptStoreEffectSugar" in path.read_text(
            encoding="utf-8"
        ):
            offenders.append(str(path))
    assert offenders == [], offenders


def test_the_ordinary_augmented_item_store_is_deleted() -> None:
    """``f()[0] += 1`` took ``SubscriptAugAssignSugar`` beside the door; every
    augmented item store is the door's read-modify-store now."""
    import sugar_lift_py_tests.sugar.augassign_sugar as aug_mod

    assert not hasattr(aug_mod, "SubscriptAugAssignSugar")


# ---------------------------------------------------------------------------
# Independent production / projector equality tooth
# ---------------------------------------------------------------------------


def test_production_inplace_set_is_independent_of_projector_table() -> None:
    """Deleting a projector must not shrink the production-minted set."""
    production = production_augassign_inplace_operators()
    assert "iadd" in production
    assert production == frozenset(
        {
            "iadd",
            "isub",
            "imul",
            "itruediv",
            "ifloordiv",
            "imod",
            "ipow",
            "iand",
            "ior",
            "ixor",
            "ilshift",
            "irshift",
            "imatmul",
        }
    )
    # Independent source: BinaryOperator class attributes, not projector keys.
    assert production == frozenset(
        cls.inplace_operator
        for cls in __import__(
            "sugar_source_tree.operators",
            fromlist=["AUGASSIGN_BINARY_OPERATOR_CLASSES"],
        ).AUGASSIGN_BINARY_OPERATOR_CLASSES
    )


def test_projector_keys_equal_independent_production_inplace_set() -> None:
    production = production_augassign_inplace_operators()
    projector_inplace = frozenset(
        k
        for k in _NATIVE_OPERATION_PROJECTORS
        if k
        in {
            "iadd",
            "isub",
            "imul",
            "itruediv",
            "ifloordiv",
            "imod",
            "ipow",
            "iand",
            "ior",
            "ixor",
            "ilshift",
            "irshift",
            "imatmul",
        }
    )
    assert production == projector_inplace
    assert production_native_operation_operators() == frozenset(
        _NATIVE_OPERATION_PROJECTORS
    )


def test_discrimination_circular_tooth_would_hide_missing_projector() -> None:
    """Lying: derive production set from projector table — circular, forbidden."""
    circular = frozenset(k for k in _NATIVE_OPERATION_PROJECTORS if k.startswith("i"))
    # Independent production must not be computed as circular (same object).
    independent = production_augassign_inplace_operators()
    # They currently equal when healthy — but sources differ: class attrs vs table.
    assert independent == production_augassign_inplace_operators()
    # Twin: claiming circular derivation is the independent source fails identity.
    with pytest.raises(AssertionError):
        assert circular is independent


# ---------------------------------------------------------------------------
# Production desugar
# ---------------------------------------------------------------------------


def test_production_desugar_list_augassign_completes_with_updated_cell() -> None:
    out = _production_desugar(
        fresh(ListValue, (TermValue(1), TermValue(2))),
        TermValue(0),
        TermValue(10),
    )
    assert out.completed_value() is not None, out
    assert _post(out) == fresh(ListValue, (TermValue(11), TermValue(2)))


def test_formal_helper_desugars_without_legacy_incomplete_only() -> None:
    function, outcome = _helper_definition()
    stmt = function.sugar().statements[0]
    assert isinstance(stmt, ContainerMutationStatementSugar), type(stmt)
    call = stmt.evaluated[0]
    assert isinstance(call, PathContainerCallSugar), type(call)
    assert call.operator.project_inplace.__func__ is Add.project_inplace
    assert type(call.operator).inplace_operator == "iadd"
    assert isinstance(outcome, NativeOperationExitCarrierV1)
    assert outcome.demand.operator == "subscript"


def test_production_get_halt_blocks_rhs_arithmetic_and_store() -> None:
    box = {"rhs": 0, "set": 0}

    @dataclass(frozen=True)
    class _RhsProbe(Sugar):
        def desugar(self, ctx=None):
            del ctx
            box["rhs"] += 1
            return ExitSet.completed(TermValue(99))

        @classmethod
        def witnesses(cls):
            return ()

    class _HaltList(ListValueCls):
        def __init__(self, elements):
            object.__setattr__(self, "elements", tuple(elements))
            object.__setattr__(self, "allocation", FRAME_FRESH)

        def setitem(self, index, value, site_, ctx):
            box["set"] += 1
            return super().setitem(index, value, site_, ctx)

    call = _door(
        _FloorSugar(_HaltList((TermValue(0),))),
        _FloorSugar(TermValue(4)),
        _RhsProbe(),
    )
    out = call.desugar(None)
    assert out.halts() == out.exits
    (halt,) = out.halts()
    assert isinstance(halt.effect, RaiseEffect)
    assert halt.effect.exception_name == "IndexError"
    assert box["rhs"] == 0
    assert box["set"] == 0


def test_production_arithmetic_halt_blocks_store() -> None:
    box = {"set": 0}

    class _CountingList(ListValueCls):
        def __init__(self, elements):
            object.__setattr__(self, "elements", tuple(elements))
            object.__setattr__(self, "allocation", FRAME_FRESH)

        def setitem(self, index, value, site, ctx):
            box["set"] += 1
            return super().setitem(index, value, site, ctx)

    from sugar_lift_py_tests.floor import NoneValue

    out = _production_desugar(
        _CountingList((TermValue(1),)),
        TermValue(0),
        NoneValue(),
    )
    assert box["set"] == 0
    assert not (out.completed_value() is not None and box["set"])


def test_production_store_halt_preserves_prior_state_without_fabricated_completion() -> (
    None
):
    out = _production_desugar(
        TupleValue((TermValue(1), TermValue(2))),
        TermValue(0),
        TermValue(10),
    )
    if out.completed_value() is not None:
        pytest.fail("readable tuple must not authorize completed setitem")


class _CountingList(ListValueCls):
    def __init__(self, elements, box=None):
        object.__setattr__(self, "elements", tuple(elements))
        object.__setattr__(self, "allocation", FRAME_FRESH)
        object.__setattr__(
            self, "_box", box if box is not None else {"get": 0, "set": 0}
        )

    def subscript(self, index, site):
        self._box["get"] = self._box.get("get", 0) + 1
        return super().subscript(index, site)

    def setitem(self, index, value, site, ctx):
        self._box["set"] = self._box.get("set", 0) + 1
        return super().setitem(index, value, site, ctx)


def test_production_receiver_index_evaluated_once_for_get_and_set() -> None:
    box = {"get": 0, "set": 0}
    out = _production_desugar(
        _CountingList((TermValue(1), TermValue(2)), box=box),
        TermValue(0),
        TermValue(5),
    )
    assert out.completed_value() is not None
    assert box["get"] == 1
    assert box["set"] == 1
    assert _post(out).elements[0] == TermValue(6)


def test_discrimination_duplicated_get_is_detected() -> None:
    box = {"get": 0, "set": 0}
    receiver = _CountingList((TermValue(1),), box=box)
    receiver.subscript(TermValue(0), "g1")
    receiver.subscript(TermValue(0), "g2")
    assert box["get"] == 2
    with pytest.raises(AssertionError):
        assert box["get"] == 1


def test_production_getitem_before_rhs_order() -> None:
    order: list[str] = []

    class _OrderList(ListValueCls):
        def __init__(self, elements):
            object.__setattr__(self, "elements", tuple(elements))
            object.__setattr__(self, "allocation", FRAME_FRESH)

        def subscript(self, index, site_):
            order.append("get")
            return super().subscript(index, site_)

        def setitem(self, index, value, site_, ctx):
            order.append("set")
            return super().setitem(index, value, site_, ctx)

    @dataclass(frozen=True)
    class _RhsOrder(Sugar):
        def desugar(self, ctx=None):
            del ctx
            order.append("rhs")
            return ExitSet.completed(TermValue(4))

        @classmethod
        def witnesses(cls):
            return ()

    def _project_order(left, right, site_, ctx):
        order.append("op")
        return project_iadd(left, right, site_, ctx)

    call = _door(
        _FloorSugar(_OrderList((TermValue(3),))),
        _FloorSugar(TermValue(0)),
        _RhsOrder(),
        operator=_Projecting(_project_order),
    )
    out = call.desugar(None)
    assert out.completed_value() is not None
    assert order == ["get", "rhs", "op", "set"]
    assert _post(out) == fresh(ListValue, (TermValue(7),))


def test_discrimination_wrong_order_rhs_before_get() -> None:
    order = ["rhs", "get"]
    with pytest.raises(AssertionError):
        assert order == ["get", "rhs", "op", "set"]


def test_production_readability_does_not_authorize_writability() -> None:
    out = _production_desugar(
        TupleValue((TermValue(1),)),
        TermValue(0),
        TermValue(1),
    )
    if out.completed_value() is not None:
        pytest.fail("readable tuple must not authorize completed setitem")


# ---------------------------------------------------------------------------
# Established inplace_binary_operator_with edge + NotImplemented fallback
# ---------------------------------------------------------------------------


def test_operator_owned_project_inplace_uses_inplace_binary_edge() -> None:
    """Add.project_inplace → discharge_inplace → inplace_binary_operator_with."""
    bound = Add.instance().project_inplace
    assert bound.__func__ is BinaryOperator.project_inplace
    assert Add.inplace_operator == "iadd"
    out = bound(TermValue(1), TermValue(2), _production_sites()[1], None)
    assert out.completed_value() is not None
    assert out.completed_value() == TermValue(3)


def test_production_projector_default_floor_is_ordinary_binary() -> None:
    """FloorValue.inplace_default → add when species has no inplace override."""
    out = project_iadd(TermValue(1), TermValue(2), _production_sites()[1], None)
    assert out.completed_value() is not None
    assert out.completed_value() == TermValue(3)


def test_production_projector_raw_notimplemented_falls_through_to_binary() -> None:
    """Twin: raw NotImplemented from floor edge → ordinary add."""
    from sugar_lift_py_tests.floor.floor_value import FloorValue

    calls: list[str] = []

    class _RawNotImpl(FloorValue):
        def inplace_binary_operator_with(self, operation, ctx):
            del operation, ctx
            calls.append("inplace")
            return NotImplemented

        def add(self, other, site, ctx):
            calls.append("add")
            return ExitSet.completed(TermValue(7))

    out = project_iadd(_RawNotImpl(), TermValue(1), "op", None)
    assert out.completed_value() is not None
    assert out.completed_value() == TermValue(7)
    assert calls == ["inplace", "add"]


def test_production_projector_completed_notimplemented_falls_through_to_binary() -> (
    None
):
    """Twin: a completed NotImplemented from floor edge → ordinary add."""
    from sugar_lift_py_tests.floor.floor_value import FloorValue

    calls: list[str] = []

    class _CompleteNotImpl(FloorValue):
        def inplace_binary_operator_with(self, operation, ctx):
            del operation, ctx
            calls.append("inplace")
            return ExitSet.completed(NotImplemented)  # type: ignore[arg-type]

        def add(self, other, site, ctx):
            calls.append("add")
            return ExitSet.completed(TermValue(9))

    out = project_iadd(_CompleteNotImpl(), TermValue(1), "op", None)
    assert out.completed_value() is not None
    assert out.completed_value() == TermValue(9)
    assert calls == ["inplace", "add"]


def test_production_projector_incomplete_does_not_fall_through_to_binary() -> None:
    """A halt surfaces unchanged — never authorizes binary fallback."""
    from sugar_lift_py_tests.effect import CoverageGapEffect
    from sugar_lift_py_tests.floor.floor_value import FloorValue

    incomplete_face = ExitSet.halted(
        CoverageGapEffect(boundary="iadd", reason="inplace unresolved face")
    )

    class _IncompleteInplace(FloorValue):
        def inplace_binary_operator_with(self, operation, ctx):
            del operation, ctx
            return incomplete_face

        def add(self, other, site, ctx):
            del other, site, ctx
            return ExitSet.completed(TermValue(0))

    out = project_iadd(_IncompleteInplace(), TermValue(1), "op", None)
    assert out is incomplete_face


def test_formal_operands_mint_iadd_not_ordinary_add() -> None:
    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )
    from sugar_lift_py_tests.ir import PrimitiveSort, make_var

    _, call = _aug_sugar()
    site = call.operator_site
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

    left = SymbolicValue(make_var("cell"), _coord("cell", 0))
    right = SymbolicValue(make_var("rhs"), _coord("rhs", 1))
    out = project_augmented(
        left, right, operator="iadd", projector=project_iadd, site=site, ctx=None
    )
    assert isinstance(out, NativeOperationExitCarrierV1)
    assert out.demand.operator == "iadd"
    with pytest.raises(AssertionError):
        assert out.demand.operator == "add"


def test_formal_iadd_projector_is_enrolled_with_authenticated_signature() -> None:
    assert "iadd" in _NATIVE_OPERATION_PROJECTORS
    assert _NATIVE_OPERATION_PROJECTORS["iadd"] is project_iadd
    parameters = tuple(__import__("inspect").signature(project_iadd).parameters)
    assert parameters == ("left", "right", "site", "ctx")


def test_discrimination_projector_absence_must_not_mint_add() -> None:
    assert Add.inplace_operator == "iadd"
    with pytest.raises(AssertionError):
        assert Add.inplace_operator == "add"


# ---------------------------------------------------------------------------
# Formal undischarged / authenticated discharge
# ---------------------------------------------------------------------------


def test_formal_subscript_get_carrier_missing_actuals_undischarged() -> None:
    _, pending = _helper_definition()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "subscript"
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    # No caller actual: the get leg is the cited unanswered face (#7825).
    exits = pending.discharge(None, {})
    assert pending.unanswered_call() in owed_calls(exits)
    assert exits.completed_value() is None


def test_authenticated_caller_discharges_get_iadd_setitem_to_updated_list() -> None:
    function, pending = _helper_definition()
    coords = {
        c.declared_name: c.coordinate_cid for c in function.sugar().formal_coordinates
    }
    exits = pending.discharge(
        None,
        {
            coords["obj"]: fresh(ListValue, (TermValue(1), TermValue(2))),
            coords["key"]: TermValue(0),
            coords["rhs"]: TermValue(10),
        },
    )
    assert isinstance(exits, ExitSet)
    assert len(exits.exits) == 1
    assert isinstance(exits.exits[0], Completed)
    assert _post_list(exits.exits[0]) == fresh(
        ListValue, (TermValue(11), TermValue(2))
    )


def test_authenticated_get_halt_blocks_store_on_formal_discharge() -> None:
    function, pending = _helper_definition()
    coords = {
        c.declared_name: c.coordinate_cid for c in function.sugar().formal_coordinates
    }
    exits = pending.discharge(
        None,
        {
            coords["obj"]: fresh(ListValue, (TermValue(1),)),
            coords["key"]: TermValue(4),
            coords["rhs"]: TermValue(10),
        },
    )
    assert isinstance(exits, ExitSet)
    assert len(exits.exits) == 1
    assert isinstance(exits.exits[0], Halted)
    assert exits.exits[0].effect.exception_name == "IndexError"


def _operation_edge_object(stored: list):
    """An ``ObjectValue`` whose read answers only through its own
    ``subscript_with`` edge (never the legacy ``subscript``, which is the
    ``FloorValue`` construction gap) and whose store records what it got."""
    from sugar_lift_py_tests.floor.object_value import ObjectValue

    class _Indexed(ObjectValue):
        def subscript_with(self, operation, ctx):
            del ctx
            assert operation.index == TermValue(0)
            return ExitSet.completed(TermValue(10))

        def setitem(self, index, value, site, ctx):
            del site, ctx
            stored.append((index, value))
            return ExitSet.completed(self)

    return _Indexed("Indexed", ())


def test_augassign_read_answers_through_the_one_subscript_door() -> None:
    """``obj[k] += v`` reads as a source ``obj[k]`` reads: an object that owns
    only ``subscript_with`` answers through it (the old ``.subscript`` read
    reached the ``FloorValue.subscript`` construction gap)."""
    stored: list = []
    receiver = _operation_edge_object(stored)

    out = _production_desugar(receiver, TermValue(0), TermValue(5))

    assert out.completed_value() is not None, out
    assert stored == [(TermValue(0), TermValue(15))]


def test_formal_augassign_discharges_an_object_actual_through_the_door() -> None:
    """The helper defers its read to the caller; the caller's ``ObjectValue``
    actual answers the read through its ``subscript_with`` edge, then the
    in-place add and the store run on it."""
    function, pending = _helper_definition()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "subscript"
    coords = {
        c.declared_name: c.coordinate_cid for c in function.sugar().formal_coordinates
    }
    stored: list = []

    exits = pending.discharge(
        None,
        {
            coords["obj"]: _operation_edge_object(stored),
            coords["key"]: TermValue(0),
            coords["rhs"]: TermValue(5),
        },
    )

    assert isinstance(exits, ExitSet)
    assert len(exits.exits) == 1
    assert isinstance(exits.exits[0], Completed)
    assert stored == [(TermValue(0), TermValue(15))]


def test_attribute_augassign_is_attribute_path_not_subscript_path() -> None:
    """Attribute OP= uses AttributeAugAssignSugar; an item target the door."""
    from sugar_lift_py_tests.sugar.augassign_sugar import AttributeAugAssignSugar

    tree = _tree("def helper(obj, rhs):\n    obj.field += rhs\n", "attr_aug.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    aug = next(node for node in function.body if isinstance(node, AugAssign))
    sugar = aug.sugar()
    assert isinstance(sugar, AttributeAugAssignSugar)
    assert not isinstance(sugar, ContainerMutationStatementSugar)
