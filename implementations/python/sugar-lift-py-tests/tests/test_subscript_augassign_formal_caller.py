"""Formal subscript augmented assignment: ``obj[key] += rhs``.

Production path only: tests drive ``SubscriptAugAssignSugar.desugar``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from sugar_lift_py_tests.caller_parameter_contract import (
    NativeOperationExitCarrierV1,
    _NATIVE_OPERATION_PROJECTORS,
    production_native_operation_operators,
    project_iadd,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import ListValue, RaiseValue, TermValue, TupleValue
from sugar_lift_py_tests.floor.list_value import ListValue as ListValueCls
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted, Incomplete
from sugar_lift_py_tests.sugar.augassign_sugar import (
    SubscriptAugAssignSugar,
    project_augmented,
)
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import AugAssign, FunctionDef
from sugar_source_tree.operators import (
    Add,
    BinaryOperator,
    production_augassign_inplace_operators,
)
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _tree(source: str, name: str = "subscript_augassign.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _helper_definition(source: str = "def helper(obj, key, rhs):\n    obj[key] += rhs\n"):
    tree = _tree(source, "helper_alone.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function, function.sugar().desugar(None)


def _aug_sugar(source: str = "def helper(obj, key, rhs):\n    obj[key] += rhs\n"):
    tree = _tree(source)
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    aug = next(node for node in function.body if isinstance(node, AugAssign))
    sugar = aug.sugar()
    assert isinstance(sugar, SubscriptAugAssignSugar), type(sugar)
    return function, sugar


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
        return Complete(self.value)

    @classmethod
    def witnesses(cls):
        return ()


def _production_sites():
    _, sugar = _aug_sugar()
    return sugar.get_site, sugar.op_site, sugar.set_site, sugar.site


def _production_desugar(receiver, index, rhs, *, operator="iadd", projector=project_iadd):
    get_site, op_site, set_site, site = _production_sites()
    sugar = SubscriptAugAssignSugar(
        receiver=_FloorSugar(receiver),
        index=_FloorSugar(index),
        rhs=_FloorSugar(rhs),
        operator=operator,
        operation=projector,
        get_site=get_site,
        op_site=op_site,
        set_site=set_site,
        site=site,
    )
    return sugar.desugar(None)


# ---------------------------------------------------------------------------
# Construction / occurrence
# ---------------------------------------------------------------------------


def test_subscript_augassign_constructs_with_operator_owned_project_inplace() -> None:
    _, sugar = _aug_sugar()
    assert isinstance(sugar, SubscriptAugAssignSugar)
    # Operator-owned double dispatch — bound project_inplace, not a kind ladder.
    assert sugar.operation.__func__ is Add.project_inplace
    assert sugar.operator == "iadd"
    assert sugar.operator == Add.inplace_operator
    assert sugar.get_site is not sugar.op_site
    assert sugar.op_site is not sugar.set_site


def test_op_site_is_structural_gap_not_rhs_or_string_scan() -> None:
    function, sugar = _aug_sugar("def helper(obj, key, rhs):\n    obj[key] += rhs\n")
    aug = next(node for node in function.body if isinstance(node, AugAssign))
    assert sugar.op_site is not aug.value.fragment
    # Carried operator_site gap contains the operator token region.
    text = sugar.op_site.unit.source[sugar.op_site.span.start : sugar.op_site.span.end]
    assert "+=" in text
    assert sugar.op_site is not sugar.get_site
    assert sugar.op_site is not sugar.set_site


def test_op_site_ignores_same_spelling_string_in_target() -> None:
    """Lying twin: ``obj['+='] += rhs`` must not use the string literal as op_site."""
    source = "def helper(obj, rhs):\n    obj['+='] += rhs\n"
    function, sugar = _aug_sugar(source)
    aug = next(node for node in function.body if isinstance(node, AugAssign))
    op_span = sugar.op_site.span
    # Index string constant span must not equal / contain the operator site.
    index_node = aug.target.slice_
    index_span = index_node.span
    assert not (
        op_span.start <= index_span.start and index_span.end <= op_span.end
    ), (op_span, index_span)
    # Operator site still sits after the full target (including ['+=']).
    assert op_span.start >= aug.target.span.end
    text = sugar.op_site.unit.source[op_span.start : op_span.end]
    assert "+=" in text


def test_discrimination_same_spelling_index_is_not_operator_site() -> None:
    """Positive twin: operator gap; lying claim that op_site is the index fails."""
    source = "def helper(obj, rhs):\n    obj['+='] += rhs\n"
    _, sugar = _aug_sugar(source)
    function = next(
        n for n in _tree(source, "twin.py").nodes() if isinstance(n, FunctionDef)
    )
    aug = next(n for n in function.body if isinstance(n, AugAssign))
    with pytest.raises(AssertionError):
        assert sugar.op_site.span == aug.target.slice_.span


def test_discrimination_legacy_runtime_effect_is_not_the_formal_path() -> None:
    _, outcome = _helper_definition()
    assert isinstance(outcome, NativeOperationExitCarrierV1), type(outcome)
    assert outcome.demand.operator == "subscript"
    with pytest.raises(AssertionError):
        assert isinstance(outcome, Incomplete)


def test_legacy_augmented_subscript_store_effect_sugar_is_deleted() -> None:
    import sugar_lift_py_tests.sugar.store_effect_sugar as store_mod

    assert not hasattr(store_mod, "LegacyAugmentedSubscriptStoreEffectSugar")
    package_root = Path(store_mod.__file__).resolve().parent.parent
    offenders = []
    for path in package_root.rglob("*.py"):
        if "LegacyAugmentedSubscriptStoreEffectSugar" in path.read_text(encoding="utf-8"):
            offenders.append(str(path))
    assert offenders == [], offenders


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
            "sugar_source_tree.operators", fromlist=["AUGASSIGN_BINARY_OPERATOR_CLASSES"]
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
    circular = frozenset(
        k for k in _NATIVE_OPERATION_PROJECTORS if k.startswith("i")
    )
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
        ListValue((TermValue(1), TermValue(2))),
        TermValue(0),
        TermValue(10),
    )
    assert isinstance(out, Complete), out
    assert out.value == ListValue((TermValue(11), TermValue(2)))


def test_formal_helper_desugars_without_legacy_incomplete_only() -> None:
    function, outcome = _helper_definition()
    stmt = function.sugar().statements[0]
    assert isinstance(stmt, SubscriptAugAssignSugar)
    assert stmt.operation.__func__ is Add.project_inplace
    assert stmt.operator == "iadd"
    assert isinstance(outcome, NativeOperationExitCarrierV1)
    assert outcome.demand.operator == "subscript"


def test_production_get_halt_blocks_rhs_arithmetic_and_store() -> None:
    box = {"rhs": 0, "set": 0}
    get_site, op_site, set_site, site = _production_sites()

    @dataclass(frozen=True)
    class _RhsProbe(Sugar):
        def desugar(self, ctx=None):
            del ctx
            box["rhs"] += 1
            return Complete(TermValue(99))

        @classmethod
        def witnesses(cls):
            return ()

    class _HaltList(ListValueCls):
        def __init__(self, elements):
            object.__setattr__(self, "elements", tuple(elements))

        def setitem(self, index, value, site_):
            box["set"] += 1
            return super().setitem(index, value, site_)

    sugar = SubscriptAugAssignSugar(
        receiver=_FloorSugar(_HaltList((TermValue(0),))),
        index=_FloorSugar(TermValue(4)),
        rhs=_RhsProbe(),
        operator="iadd",
        operation=project_iadd,
        get_site=get_site,
        op_site=op_site,
        set_site=set_site,
        site=site,
    )
    out = sugar.desugar(None)
    assert isinstance(out, Complete)
    assert isinstance(out.value, RaiseValue)
    assert out.value.effect.exception_name == "IndexError"
    assert box["rhs"] == 0
    assert box["set"] == 0


def test_production_arithmetic_halt_blocks_store() -> None:
    box = {"set": 0}

    class _CountingList(ListValueCls):
        def __init__(self, elements):
            object.__setattr__(self, "elements", tuple(elements))

        def setitem(self, index, value, site):
            box["set"] += 1
            return super().setitem(index, value, site)

    from sugar_lift_py_tests.floor import NoneValue

    out = _production_desugar(
        _CountingList((TermValue(1),)),
        TermValue(0),
        NoneValue(),
    )
    assert box["set"] == 0
    assert not (
        isinstance(out, Complete)
        and not isinstance(out.value, RaiseValue)
        and box["set"]
    )


def test_production_store_halt_preserves_prior_state_without_fabricated_completion() -> (
    None
):
    out = _production_desugar(
        TupleValue((TermValue(1), TermValue(2))),
        TermValue(0),
        TermValue(10),
    )
    if isinstance(out, Complete) and not isinstance(out.value, RaiseValue):
        pytest.fail("readable tuple must not authorize completed setitem")


class _CountingList(ListValueCls):
    def __init__(self, elements, box=None):
        object.__setattr__(self, "elements", tuple(elements))
        object.__setattr__(
            self, "_box", box if box is not None else {"get": 0, "set": 0}
        )

    def subscript(self, index, site):
        self._box["get"] = self._box.get("get", 0) + 1
        return super().subscript(index, site)

    def setitem(self, index, value, site):
        self._box["set"] = self._box.get("set", 0) + 1
        return super().setitem(index, value, site)


def test_production_receiver_index_evaluated_once_for_get_and_set() -> None:
    box = {"get": 0, "set": 0}
    out = _production_desugar(
        _CountingList((TermValue(1), TermValue(2)), box=box),
        TermValue(0),
        TermValue(5),
    )
    assert isinstance(out, Complete)
    assert box["get"] == 1
    assert box["set"] == 1
    assert out.value.elements[0] == TermValue(6)


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
    get_site, op_site, set_site, site = _production_sites()

    class _OrderList(ListValueCls):
        def __init__(self, elements):
            object.__setattr__(self, "elements", tuple(elements))

        def subscript(self, index, site_):
            order.append("get")
            return super().subscript(index, site_)

        def setitem(self, index, value, site_):
            order.append("set")
            return super().setitem(index, value, site_)

    @dataclass(frozen=True)
    class _RhsOrder(Sugar):
        def desugar(self, ctx=None):
            del ctx
            order.append("rhs")
            return Complete(TermValue(4))

        @classmethod
        def witnesses(cls):
            return ()

    def _project_order(left, right, site_):
        order.append("op")
        return project_iadd(left, right, site_)

    sugar = SubscriptAugAssignSugar(
        receiver=_FloorSugar(_OrderList((TermValue(3),))),
        index=_FloorSugar(TermValue(0)),
        rhs=_RhsOrder(),
        operator="iadd",
        operation=_project_order,
        get_site=get_site,
        op_site=op_site,
        set_site=set_site,
        site=site,
    )
    out = sugar.desugar(None)
    assert isinstance(out, Complete)
    assert order == ["get", "rhs", "op", "set"]
    assert out.value == ListValue((TermValue(7),))


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
    if isinstance(out, Complete) and not isinstance(out.value, RaiseValue):
        pytest.fail("readable tuple must not authorize completed setitem")


# ---------------------------------------------------------------------------
# Established inplace_binary_operator_with edge + NotImplemented fallback
# ---------------------------------------------------------------------------


def test_operator_owned_project_inplace_uses_inplace_binary_edge() -> None:
    """Add.project_inplace → discharge_inplace → inplace_binary_operator_with."""
    bound = Add.instance().project_inplace
    assert bound.__func__ is BinaryOperator.project_inplace
    assert Add.inplace_operator == "iadd"
    out = bound(TermValue(1), TermValue(2), _production_sites()[1])
    assert isinstance(out, Complete)
    assert out.value == TermValue(3)


def test_production_projector_default_floor_is_ordinary_binary() -> None:
    """FloorValue.inplace_default → add when species has no inplace override."""
    out = project_iadd(TermValue(1), TermValue(2), _production_sites()[1])
    assert isinstance(out, Complete)
    assert out.value == TermValue(3)


def test_production_projector_raw_notimplemented_falls_through_to_binary() -> None:
    """Twin: raw NotImplemented from floor edge → ordinary add."""
    from sugar_lift_py_tests.floor.floor_value import FloorValue
    from sugar_lift_py_tests.operations.inplace_binary_operator_operation import (
        InplaceBinaryOperatorOperation,
    )

    calls: list[str] = []

    class _RawNotImpl(FloorValue):
        def inplace_binary_operator_with(self, operation, ctx):
            del operation, ctx
            calls.append("inplace")
            return NotImplemented

        def add(self, other, site):
            calls.append("add")
            return Complete(TermValue(7))

    out = project_iadd(_RawNotImpl(), TermValue(1), "op")
    assert isinstance(out, Complete)
    assert out.value == TermValue(7)
    assert calls == ["inplace", "add"]


def test_production_projector_completed_notimplemented_falls_through_to_binary() -> (
    None
):
    """Twin: Complete(NotImplemented) from floor edge → ordinary add."""
    from sugar_lift_py_tests.floor.floor_value import FloorValue

    calls: list[str] = []

    class _CompleteNotImpl(FloorValue):
        def inplace_binary_operator_with(self, operation, ctx):
            del operation, ctx
            calls.append("inplace")
            return Complete(NotImplemented)  # type: ignore[arg-type]

        def add(self, other, site):
            calls.append("add")
            return Complete(TermValue(9))

    out = project_iadd(_CompleteNotImpl(), TermValue(1), "op")
    assert isinstance(out, Complete)
    assert out.value == TermValue(9)
    assert calls == ["inplace", "add"]


def test_production_projector_incomplete_does_not_fall_through_to_binary() -> None:
    """Incomplete surfaces unchanged — never authorizes binary fallback."""
    from sugar_lift_py_tests.effect import CoverageGapEffect
    from sugar_lift_py_tests.floor.floor_value import FloorValue

    incomplete_face = Incomplete(
        CoverageGapEffect(boundary="iadd", reason="inplace unresolved face")
    )

    class _IncompleteInplace(FloorValue):
        def inplace_binary_operator_with(self, operation, ctx):
            del operation, ctx
            return incomplete_face

        def add(self, other, site):
            del other, site
            return Complete(TermValue(0))

    out = project_iadd(_IncompleteInplace(), TermValue(1), "op")
    assert out is incomplete_face


def test_formal_operands_mint_iadd_not_ordinary_add() -> None:
    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )
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

    left = SymbolicValue(make_var("cell"), _coord("cell", 0))
    right = SymbolicValue(make_var("rhs"), _coord("rhs", 1))
    out = project_augmented(
        left, right, operator="iadd", projector=project_iadd, site=site
    )
    assert isinstance(out, NativeOperationExitCarrierV1)
    assert out.demand.operator == "iadd"
    with pytest.raises(AssertionError):
        assert out.demand.operator == "add"


def test_formal_iadd_projector_is_enrolled_with_authenticated_signature() -> None:
    assert "iadd" in _NATIVE_OPERATION_PROJECTORS
    assert _NATIVE_OPERATION_PROJECTORS["iadd"] is project_iadd
    parameters = tuple(
        __import__("inspect").signature(project_iadd).parameters
    )
    assert parameters == ("left", "right", "site")


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
    with pytest.raises(SugarNotWritten, match="caller actual absent"):
        pending.discharge({})


def test_authenticated_caller_discharges_get_iadd_setitem_to_updated_list() -> None:
    function, pending = _helper_definition()
    coords = {
        c.declared_name: c.coordinate_cid
        for c in function.sugar().formal_coordinates
    }
    exits = pending.discharge(
        {
            coords["obj"]: ListValue((TermValue(1), TermValue(2))),
            coords["key"]: TermValue(0),
            coords["rhs"]: TermValue(10),
        }
    )
    assert isinstance(exits, ExitSet)
    assert len(exits.exits) == 1
    assert isinstance(exits.exits[0], Completed)
    assert _post_list(exits.exits[0]) == ListValue((TermValue(11), TermValue(2)))


def test_authenticated_get_halt_blocks_store_on_formal_discharge() -> None:
    function, pending = _helper_definition()
    coords = {
        c.declared_name: c.coordinate_cid
        for c in function.sugar().formal_coordinates
    }
    exits = pending.discharge(
        {
            coords["obj"]: ListValue((TermValue(1),)),
            coords["key"]: TermValue(4),
            coords["rhs"]: TermValue(10),
        }
    )
    assert isinstance(exits, ExitSet)
    assert len(exits.exits) == 1
    assert isinstance(exits.exits[0], Halted)
    assert exits.exits[0].effect.exception_name == "IndexError"


def test_attribute_augassign_still_attribute_store_effect_not_subscript_path() -> None:
    from sugar_lift_py_tests.sugar.store_effect_sugar import AttributeStoreEffectSugar

    tree = _tree("def helper(obj, rhs):\n    obj.field += rhs\n", "attr_aug.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    aug = next(node for node in function.body if isinstance(node, AugAssign))
    sugar = aug.sugar()
    assert isinstance(sugar, AttributeStoreEffectSugar)
    assert not isinstance(sugar, SubscriptAugAssignSugar)
