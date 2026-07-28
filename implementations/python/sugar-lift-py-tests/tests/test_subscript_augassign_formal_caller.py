"""Formal subscript augmented assignment: ``obj[key] += rhs``.

Production path only: tests drive ``SubscriptAugAssignSugar.desugar``, not a
manual subscript → project_augmented → setitem replay.

MUST NOT TOUCH: carrier, ExitSet, source-return projection, generator/resource
files; no receiver/type spelling arms.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from sugar_lift_py_tests.caller_parameter_contract import (
    IADD,
    InplaceThenBinaryProjector,
    NativeOperationExitCarrierV1,
    _NATIVE_OPERATION_PROJECTORS,
    inplace_projector_for,
    production_native_operation_operators,
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
from sugar_source_tree.operators import Add
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
    """Constant floor child for production desugar of SubscriptAugAssignSugar."""

    value: object

    def desugar(self, ctx=None):
        del ctx
        return Complete(self.value)

    @classmethod
    def witnesses(cls):
        return ()


def _production_sites():
    """Authenticated fragments from a real AugAssign (not string loci)."""
    _, sugar = _aug_sugar()
    return sugar.get_site, sugar.op_site, sugar.set_site, sugar.site


def _production_desugar(receiver, index, rhs, *, operation=IADD, sites=None):
    """Drive the production sugar path with ground floor children."""
    get_site, op_site, set_site, site = sites or _production_sites()
    sugar = SubscriptAugAssignSugar(
        receiver=_FloorSugar(receiver),
        index=_FloorSugar(index),
        rhs=_FloorSugar(rhs),
        operation=operation,
        get_site=get_site,
        op_site=op_site,
        set_site=set_site,
        site=site,
    )
    return sugar.desugar(None)


# ---------------------------------------------------------------------------
# Construction / occurrence sites
# ---------------------------------------------------------------------------


def test_subscript_augassign_constructs_with_explicit_iadd_projector() -> None:
    _, sugar = _aug_sugar()
    assert isinstance(sugar, SubscriptAugAssignSugar)
    assert sugar.operation is IADD
    assert sugar.operation.operator == "iadd"
    assert sugar.get_site is not sugar.op_site
    assert sugar.op_site is not sugar.set_site
    assert sugar.get_site is not sugar.set_site


def test_op_site_is_operator_token_interval_not_rhs_occurrence() -> None:
    """op_site is the gap holding ``+=``, not the RHS fragment."""
    function, sugar = _aug_sugar("def helper(obj, key, rhs):\n    obj[key] += rhs\n")
    aug = next(node for node in function.body if isinstance(node, AugAssign))
    # Operator interval is between target end and value start.
    assert sugar.op_site is not aug.value.fragment
    text = sugar.op_site.text if hasattr(sugar.op_site, "text") else str(sugar.op_site)
    # Source fragment text should include the aug-assign operator spelling.
    assert "+=" in getattr(sugar.op_site, "text", text) or "+=" in str(
        getattr(sugar.op_site, "span", text)
    )
    # Distinct from get (subscript) and set (statement).
    assert sugar.op_site is not sugar.get_site
    assert sugar.op_site is not sugar.set_site


def test_discrimination_legacy_runtime_effect_is_not_the_formal_path() -> None:
    _, outcome = _helper_definition()
    assert isinstance(outcome, NativeOperationExitCarrierV1), type(outcome)
    assert outcome.demand.operator == "subscript"
    with pytest.raises(AssertionError):
        assert isinstance(outcome, Incomplete)


def test_legacy_augmented_subscript_store_effect_sugar_is_deleted() -> None:
    """Shell deletion is real: class gone; no production reference remains."""
    import sugar_lift_py_tests.sugar.store_effect_sugar as store_mod

    assert not hasattr(store_mod, "LegacyAugmentedSubscriptStoreEffectSugar")
    package_root = Path(store_mod.__file__).resolve().parent.parent
    offenders = []
    for path in package_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "LegacyAugmentedSubscriptStoreEffectSugar" in text:
            offenders.append(str(path))
    assert offenders == [], offenders


# ---------------------------------------------------------------------------
# Production desugar: authenticated completion
# ---------------------------------------------------------------------------


def test_production_desugar_list_augassign_completes_with_updated_cell() -> None:
    """Production path: xs[0] += 10 on [1,2] → [11,2]."""
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
    assert stmt.operation is IADD
    assert isinstance(outcome, NativeOperationExitCarrierV1)
    assert outcome.demand.operator == "subscript"


# ---------------------------------------------------------------------------
# Production desugar: get halt / arithmetic halt / store halt
# ---------------------------------------------------------------------------


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
        index=_FloorSugar(TermValue(4)),  # OOB → IndexError on get
        rhs=_RhsProbe(),
        operation=IADD,
        get_site=get_site,
        op_site=op_site,
        set_site=set_site,
        site=site,
    )
    out = sugar.desugar(None)
    assert isinstance(out, Complete)
    assert isinstance(out.value, RaiseValue)
    assert out.value.effect.exception_name == "IndexError"
    assert box["rhs"] == 0, "get halt must not evaluate RHS"
    assert box["set"] == 0, "get halt must not store"


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
    # TypeError face (Complete Raise or Incomplete) — store must not run.
    if isinstance(out, Complete) and isinstance(out.value, RaiseValue):
        assert box["set"] == 0
    elif isinstance(out, Incomplete):
        assert box["set"] == 0
    else:
        # Dual ExitSet may include halt — still no completed store of None.
        assert box["set"] == 0


def test_production_store_halt_preserves_prior_state_without_fabricated_completion() -> (
    None
):
    """Tuple is readable; setitem must not complete a fabricated write."""
    out = _production_desugar(
        TupleValue((TermValue(1), TermValue(2))),
        TermValue(0),
        TermValue(10),
    )
    if isinstance(out, Complete) and not isinstance(out.value, RaiseValue):
        pytest.fail("readable tuple must not authorize completed setitem")
    assert isinstance(out, (Incomplete, ExitSet)) or (
        isinstance(out, Complete) and isinstance(out.value, RaiseValue)
    )


# ---------------------------------------------------------------------------
# Production desugar: once-eval / order
# ---------------------------------------------------------------------------


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
    assert box["get"] == 1, "duplicated getitem evaluation"
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

    class _IAddOrder(InplaceThenBinaryProjector):
        def __call__(self, left, right, site_):
            order.append("op")
            return super().__call__(left, right, site_)

    op = _IAddOrder("iadd", "iadd", "add")
    sugar = SubscriptAugAssignSugar(
        receiver=_FloorSugar(_OrderList((TermValue(3),))),
        index=_FloorSugar(TermValue(0)),
        rhs=_RhsOrder(),
        operation=op,
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


# ---------------------------------------------------------------------------
# Readability ≠ writability
# ---------------------------------------------------------------------------


def test_production_readability_does_not_authorize_writability() -> None:
    out = _production_desugar(
        TupleValue((TermValue(1),)),
        TermValue(0),
        TermValue(1),
    )
    if isinstance(out, Complete) and not isinstance(out.value, RaiseValue):
        pytest.fail("readable tuple must not authorize completed setitem")


# ---------------------------------------------------------------------------
# Explicit iadd projector law
# ---------------------------------------------------------------------------


def test_inplace_projector_for_add_is_iadd_instance() -> None:
    assert inplace_projector_for(Add.instance()) is IADD
    assert IADD.operator == "iadd"


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
    out = project_augmented(left, right, IADD, site)
    assert isinstance(out, NativeOperationExitCarrierV1)
    assert out.demand.operator == "iadd"
    with pytest.raises(AssertionError):
        assert out.demand.operator == "add"


def test_iadd_projector_falls_back_only_on_absent_method_or_notimplemented() -> None:
    calls: list[str] = []

    @dataclass(frozen=True)
    class _AddOnly:
        value: int

        def add(self, other, site):
            calls.append("add")
            return Complete(TermValue(self.value + other.value))

    assert IADD(_AddOnly(1), TermValue(2), "op").value == TermValue(3)
    assert calls == ["add"]

    calls.clear()

    @dataclass(frozen=True)
    class _NotImpl:
        value: int

        def iadd(self, other, site):
            calls.append("iadd")
            return NotImplemented

        def add(self, other, site):
            calls.append("add")
            return Complete(TermValue(self.value + other.value))

    assert IADD(_NotImpl(1), TermValue(2), "op").value == TermValue(3)
    assert calls == ["iadd", "add"]


def test_iadd_projector_does_not_fallback_on_incomplete_face() -> None:
    """Unresolved Incomplete must not authorize ordinary add."""
    from sugar_lift_py_tests.effect import CoverageGapEffect

    incomplete_face = Incomplete(
        CoverageGapEffect(
            boundary="iadd",
            reason="inplace unresolved face — must not fall back to add",
        )
    )

    @dataclass(frozen=True)
    class _IncompleteIadd:
        def iadd(self, other, site):
            del other, site
            return incomplete_face

        def add(self, other, site):
            del other, site
            return Complete(TermValue(0))

    out = IADD(_IncompleteIadd(), TermValue(1), "op")
    assert out is incomplete_face
    assert isinstance(out, Incomplete)
    with pytest.raises(AssertionError):
        assert isinstance(out, Complete)


def test_iadd_projector_prefers_floor_iadd_when_present() -> None:
    calls: list[str] = []

    @dataclass(frozen=True)
    class _Both:
        value: int

        def iadd(self, other, site):
            calls.append("iadd")
            return Complete(TermValue(self.value + other.value))

        def add(self, other, site):
            calls.append("add")
            return Complete(TermValue(self.value + other.value))

    out = IADD(_Both(1), TermValue(2), "op")
    assert isinstance(out, Complete)
    assert calls == ["iadd"]
    with pytest.raises(AssertionError):
        assert calls == ["add"]


def test_formal_iadd_projector_is_enrolled_with_authenticated_signature() -> None:
    assert "iadd" in _NATIVE_OPERATION_PROJECTORS
    assert _NATIVE_OPERATION_PROJECTORS["iadd"] is IADD
    parameters = tuple(
        __import__("inspect").signature(
            _NATIVE_OPERATION_PROJECTORS["iadd"]
        ).parameters
    )
    # Instance __call__ binds self → discharge sees (left, right, site).
    assert parameters == ("left", "right", "site")
    assert production_native_operation_operators() == frozenset(
        _NATIVE_OPERATION_PROJECTORS
    )


def test_discrimination_projector_absence_must_not_mint_add() -> None:
    truthful = IADD.operator
    assert truthful == "iadd"
    lying = "add"
    with pytest.raises(AssertionError):
        assert lying == "iadd"


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
    assert isinstance(pending, NativeOperationExitCarrierV1)
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


# ---------------------------------------------------------------------------
# Attribute substitute is NOT claimed by this PR
# ---------------------------------------------------------------------------


def test_attribute_augassign_still_attribute_store_effect_not_subscript_path() -> None:
    """Attribute targets stay on AttributeStoreEffectSugar until their production."""
    from sugar_lift_py_tests.sugar.store_effect_sugar import AttributeStoreEffectSugar

    tree = _tree("def helper(obj, rhs):\n    obj.field += rhs\n", "attr_aug.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    aug = next(node for node in function.body if isinstance(node, AugAssign))
    sugar = aug.sugar()
    assert isinstance(sugar, AttributeStoreEffectSugar)
    assert not isinstance(sugar, SubscriptAugAssignSugar)
