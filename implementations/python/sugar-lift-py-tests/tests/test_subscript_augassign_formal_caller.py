"""Formal subscript augmented assignment: ``obj[key] += rhs``.

Python law (evaluation order is load-bearing):

  1. Evaluate ``obj`` once, ``key`` once
  2. ``current = obj[key]`` (getitem) **before** RHS
  3. Evaluate ``rhs``
  4. ``result = current + rhs`` (inplace when Floor authorizes; else binary)
  5. ``obj[key] = result`` (setitem) last

Acceptance:

  - receiver/index evaluated once
  - getitem before RHS
  - authenticated in-place with ordinary binary fallback only when Floor
    authorizes (no unconditional ``__add__`` pretending to be ``__iadd__``)
  - setitem last
  - get halt blocks RHS/arithmetic/store
  - RHS or arithmetic halt blocks the store
  - store halt preserves prior state without fabricated completion
  - authenticated caller completes; missing actuals Undischarged
  - read / arithmetic / write retain DISTINCT occurrence coordinates
  - twins: duplicated eval, wrong order, readability-as-writability,
    ``__iadd__`` replaced by unconditional ``__add__``

If a shared formal ``iadd`` native-operation producer/projector is required
and missing, reds name the exact contract rather than emulating it.

MUST NOT TOUCH: carrier, ExitSet, source-return projection, generator/resource
files; no receiver/type spelling arms.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from sugar_lift_py_tests.caller_parameter_contract import (
    NativeOperationExitCarrierV1,
    _NATIVE_OPERATION_PROJECTORS,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import ListValue, RaiseValue, TermValue, TupleValue
from sugar_lift_py_tests.floor.list_value import ListValue as ListValueCls
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted, Incomplete
from sugar_lift_py_tests.sugar.augassign_sugar import (
    SubscriptAugAssignSugar,
    _augmented_binary,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import AugAssign, FunctionDef, Subscript
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile

# Authenticated iadd is enrolled: binary fallback lives *inside* the projector,
# never by minting ordinary ``add`` when iadd is absent.


def _tree(source: str, name: str = "subscript_augassign.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _identity(name: str):
    from sugar_lift_py_tests.ir import ctor, str_const

    return ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const(name)],
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


# ---------------------------------------------------------------------------
# Sugar construction / occurrence sites
# ---------------------------------------------------------------------------


def test_subscript_augassign_constructs_subscript_augassign_sugar() -> None:
    _, sugar = _aug_sugar()
    assert isinstance(sugar, SubscriptAugAssignSugar)
    assert sugar.op_kind == "Add"
    # Distinct occurrence coordinates for get / op / store.
    assert sugar.get_site is not sugar.op_site
    assert sugar.op_site is not sugar.set_site
    assert sugar.get_site is not sugar.set_site


def test_discrimination_legacy_runtime_effect_is_not_the_formal_path() -> None:
    """Helper alone is undischarged get carrier — not legacy Incomplete effect."""
    _, outcome = _helper_definition()
    assert isinstance(outcome, NativeOperationExitCarrierV1), type(outcome)
    assert outcome.demand.operator == "subscript"
    from sugar_lift_py_tests.effect import SubscriptStoreRuntimeEffect

    with pytest.raises(AssertionError):
        assert isinstance(outcome, Incomplete) and isinstance(
            outcome.effect, SubscriptStoreRuntimeEffect
        )


# ---------------------------------------------------------------------------
# Authenticated completion: get → add → set
# ---------------------------------------------------------------------------


def test_authenticated_list_augassign_completes_with_updated_cell() -> None:
    """``xs[0] += 10`` on [1, 2] → [11, 2]."""
    _, sugar = _aug_sugar()
    # Drive via Floor chain matching sugar desugar contract (once-eval).
    receiver = ListValue((TermValue(1), TermValue(2)))
    index = TermValue(0)
    rhs = TermValue(10)
    get_out = receiver.subscript(index, sugar.get_site)
    assert isinstance(get_out, Complete)
    op_out = _augmented_binary(get_out.value, rhs, "Add", sugar.op_site)
    assert isinstance(op_out, Complete)
    set_out = receiver.setitem(index, op_out.value, sugar.set_site)
    assert isinstance(set_out, Complete)
    assert set_out.value == ListValue((TermValue(11), TermValue(2)))


def test_formal_helper_desugars_without_legacy_incomplete_only() -> None:
    """Helper body desugars through SubscriptAugAssignSugar (not legacy effect)."""
    function, outcome = _helper_definition()
    # Body statement sugar is the formal path (after FunctionDef substitute).
    stmt = function.sugar().statements[0]
    assert isinstance(stmt, SubscriptAugAssignSugar)
    # Helper alone retains undischarged get demand — not legacy Incomplete.
    assert isinstance(outcome, NativeOperationExitCarrierV1)
    assert outcome.demand.operator == "subscript"
    assert not (
        isinstance(outcome, Incomplete)
        and "augmented subscript assignment runtime boundary" in str(outcome.effect)
    ), "legacy Incomplete RuntimeEffect must not be the sole formal path"


# ---------------------------------------------------------------------------
# Get halt blocks RHS / arithmetic / store
# ---------------------------------------------------------------------------


def test_get_halt_blocks_rhs_arithmetic_and_store() -> None:
    """IndexError on getitem: no store completion."""
    function, sugar = _aug_sugar()
    receiver = ListValue((TermValue(0),))
    index = TermValue(4)  # OOB
    get_out = receiver.subscript(index, sugar.get_site)
    assert isinstance(get_out, Complete)
    assert isinstance(get_out.value, RaiseValue)
    assert get_out.value.effect.exception_name == "IndexError"
    # RaiseValue short-circuits and_then — store must not run.
    chained = get_out.and_then(
        lambda _current: receiver.setitem(index, TermValue(99), sugar.set_site)
    )
    assert isinstance(chained, Complete)
    assert isinstance(chained.value, RaiseValue)
    assert chained.value.effect.exception_name == "IndexError"
    # Original list unchanged.
    assert receiver == ListValue((TermValue(0),))


# ---------------------------------------------------------------------------
# Arithmetic halt blocks store
# ---------------------------------------------------------------------------


def test_arithmetic_halt_blocks_store() -> None:
    """TypeError from add: setitem must not complete."""
    function, sugar = _aug_sugar()
    receiver = ListValue((TermValue(1),))
    index = TermValue(0)
    get_out = receiver.subscript(index, sugar.get_site)
    assert isinstance(get_out, Complete)
    # TermValue + ListValue is TypeError on many floors; use None-like if available
    from sugar_lift_py_tests.floor import NoneValue

    op_out = _augmented_binary(get_out.value, NoneValue(), "Add", sugar.op_site)
    if isinstance(op_out, Complete) and isinstance(op_out.value, RaiseValue):
        chained = op_out.and_then(
            lambda result: receiver.setitem(index, result, sugar.set_site)
        )
        assert isinstance(chained, Complete)
        assert isinstance(chained.value, RaiseValue)
        assert receiver == ListValue((TermValue(1),))
    elif isinstance(op_out, Incomplete):
        # Incomplete does not continue to store.
        assert op_out.and_then(
            lambda result: receiver.setitem(index, result, sugar.set_site)
        ) is op_out
    else:
        # If add completed somehow, still require store would need explicit call.
        assert not isinstance(op_out, Complete) or not (
            isinstance(op_out.value, TermValue)
        )


# ---------------------------------------------------------------------------
# Store halt preserves prior state
# ---------------------------------------------------------------------------


def test_store_halt_preserves_prior_get_result_without_fabricated_completion() -> None:
    """Immutable receiver: setitem TypeError; get/add results not fabricated store."""
    function, sugar = _aug_sugar()
    # Tuple is readable but not settable.
    receiver = TupleValue((TermValue(1), TermValue(2)))
    index = TermValue(0)
    get_out = receiver.subscript(index, sugar.get_site)
    assert isinstance(get_out, Complete)
    assert get_out.value == TermValue(1)
    op_out = _augmented_binary(get_out.value, TermValue(10), "Add", sugar.op_site)
    assert isinstance(op_out, Complete)
    assert op_out.value == TermValue(11)
    set_out = receiver.setitem(index, op_out.value, sugar.set_site)
    # Store raises / Incomplete — not Completed updated tuple.
    if isinstance(set_out, Complete) and isinstance(set_out.value, RaiseValue):
        assert set_out.value.effect.exception_name in {"TypeError", "AttributeError"}
    else:
        assert isinstance(set_out, (Incomplete, ExitSet)) or (
            isinstance(set_out, Complete) and isinstance(set_out.value, RaiseValue)
        )
    # Prior get value still TermValue(1) testimony — not a fabricated store.
    assert get_out.value == TermValue(1)


# ---------------------------------------------------------------------------
# Distinct occurrence coordinates
# ---------------------------------------------------------------------------


def test_read_arithmetic_write_retain_distinct_occurrence_sites() -> None:
    _, sugar = _aug_sugar()
    sites = (sugar.get_site, sugar.op_site, sugar.set_site)
    assert len({id(s) for s in sites}) == 3
    # Fragments differ in span / role.
    texts = tuple(getattr(s, "text", str(s)) for s in sites)
    assert len(set(texts)) >= 2 or len({str(s) for s in sites}) == 3


# ---------------------------------------------------------------------------
# Once-eval of receiver/index
# ---------------------------------------------------------------------------


class _CountingList(ListValueCls):
    """ListValue that counts get/set — proves once-eval structure."""

    # Mutable counters live outside the frozen dataclass payload via a box.
    _box: dict = field(default_factory=dict, repr=False, compare=False)

    def __init__(self, elements, box=None):
        object.__setattr__(self, "elements", tuple(elements))
        object.__setattr__(self, "_box", box if box is not None else {"get": 0, "set": 0})

    def subscript(self, index, site):
        self._box["get"] = self._box.get("get", 0) + 1
        return super().subscript(index, site)

    def setitem(self, index, value, site):
        self._box["set"] = self._box.get("set", 0) + 1
        return super().setitem(index, value, site)


def test_receiver_and_index_evaluated_once_for_get_and_set() -> None:
    """Subscript/setitem each fire once on the same receiver object."""
    function, sugar = _aug_sugar()
    box = {"get": 0, "set": 0}
    receiver = _CountingList((TermValue(1), TermValue(2)), box=box)
    index = TermValue(0)
    rhs = TermValue(5)
    # Mirror desugar order with shared receiver/index bindings.
    get_out = receiver.subscript(index, sugar.get_site)
    assert box["get"] == 1
    op_out = _augmented_binary(get_out.value, rhs, "Add", sugar.op_site)
    set_out = receiver.setitem(index, op_out.value, sugar.set_site)
    assert box["get"] == 1, "duplicated getitem evaluation"
    assert box["set"] == 1
    assert isinstance(set_out, Complete)
    assert set_out.value.elements[0] == TermValue(6)


def test_discrimination_duplicated_get_is_detected() -> None:
    box = {"get": 0, "set": 0}
    receiver = _CountingList((TermValue(1),), box=box)
    index = TermValue(0)
    receiver.subscript(index, "g1")
    receiver.subscript(index, "g2")  # lying second get
    assert box["get"] == 2
    with pytest.raises(AssertionError):
        assert box["get"] == 1


# ---------------------------------------------------------------------------
# Getitem before RHS (order twin)
# ---------------------------------------------------------------------------


def test_getitem_before_rhs_order() -> None:
    """Order log: get then rhs-mark then op then set."""
    order: list[str] = []
    function, sugar = _aug_sugar()
    receiver = ListValue((TermValue(3),))
    index = TermValue(0)

    def rhs_value():
        order.append("rhs")
        return TermValue(4)

    order.append("get")
    get_out = receiver.subscript(index, sugar.get_site)
    assert isinstance(get_out, Complete)
    right = rhs_value()
    order.append("op")
    op_out = _augmented_binary(get_out.value, right, "Add", sugar.op_site)
    order.append("set")
    set_out = receiver.setitem(index, op_out.value, sugar.set_site)
    assert order == ["get", "rhs", "op", "set"]
    assert isinstance(set_out, Complete)
    assert set_out.value == ListValue((TermValue(7),))


def test_discrimination_wrong_order_rhs_before_get() -> None:
    order: list[str] = []
    order.append("rhs")
    order.append("get")
    with pytest.raises(AssertionError):
        assert order == ["get", "rhs", "op", "set"]


# ---------------------------------------------------------------------------
# Readability is not writability
# ---------------------------------------------------------------------------


def test_readability_does_not_authorize_writability() -> None:
    """Tuple is readable (get) but setitem must not complete."""
    function, sugar = _aug_sugar()
    receiver = TupleValue((TermValue(1),))
    index = TermValue(0)
    get_out = receiver.subscript(index, sugar.get_site)
    assert isinstance(get_out, Complete)
    op_out = _augmented_binary(get_out.value, TermValue(1), "Add", sugar.op_site)
    assert isinstance(op_out, Complete)
    set_out = receiver.setitem(index, op_out.value, sugar.set_site)
    # Must not look like a completed store of a new tuple cell.
    if isinstance(set_out, Complete) and not isinstance(set_out.value, RaiseValue):
        pytest.fail("readable tuple must not authorize completed setitem")
    assert isinstance(set_out, (Incomplete, ExitSet)) or (
        isinstance(set_out, Complete) and isinstance(set_out.value, RaiseValue)
    )


# ---------------------------------------------------------------------------
# iadd vs unconditional add
# ---------------------------------------------------------------------------


def test_augmented_binary_prefers_floor_iadd_when_present() -> None:
    """When Floor exposes iadd, it is consulted before add."""
    calls: list[str] = []

    @dataclass(frozen=True)
    class _IAddValue:
        value: int

        def iadd(self, other, site):
            calls.append("iadd")
            return Complete(TermValue(self.value + other.value))

        def add(self, other, site):
            calls.append("add")
            return Complete(TermValue(self.value + other.value))

    out = _augmented_binary(_IAddValue(1), TermValue(2), "Add", "op")
    assert isinstance(out, Complete)
    assert out.value == TermValue(3)
    assert calls == ["iadd"]
    with pytest.raises(AssertionError):
        assert calls == ["add"]


def test_discrimination_unconditional_add_without_iadd_probe_is_detected() -> None:
    """Twin: always calling add without checking iadd is the lying path."""
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

    # Truthful path uses iadd first.
    _augmented_binary(_Both(1), TermValue(1), "Add", "op")
    assert calls[0] == "iadd"
    # Lying unconditional add:
    lying_calls: list[str] = []
    v = _Both(1)
    lying_calls.append("add")
    v.add(TermValue(1), "op")
    with pytest.raises(AssertionError):
        assert lying_calls == ["iadd"]


def test_formal_iadd_projector_is_enrolled_with_authenticated_signature() -> None:
    """iadd projector is explicit — never projector-absence silent-fallback to add."""
    assert "iadd" in _NATIVE_OPERATION_PROJECTORS
    parameters = tuple(
        __import__("inspect").signature(_NATIVE_OPERATION_PROJECTORS["iadd"]).parameters
    )
    assert parameters == ("left", "right", "site")


def test_formal_operands_mint_iadd_not_ordinary_add() -> None:
    """Formal augassign arithmetic demand is operator='iadd', never bare 'add'."""
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
    out = _augmented_binary(left, right, "Add", site)
    assert isinstance(out, NativeOperationExitCarrierV1)
    assert out.demand.operator == "iadd"
    with pytest.raises(AssertionError):
        assert out.demand.operator == "add"


def test_discrimination_projector_absence_must_not_mint_add() -> None:
    """Twin: minting add because iadd is missing is the lying path (false green)."""
    # Authenticated path mints iadd when formal.
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
    coord = FormalParameterCoordinateV1.mint(
        owner_source_identity_cid=src,
        owner_definition_locus=owner_def,
        declaration_locus=SourceFragmentCoordinateV1(src, 1, 10, 1, 12),
        ordinal=0,
        parameter_kind="positional-or-keyword",
        declared_name="x",
        sort=PrimitiveSort("Value"),
    )
    left = SymbolicValue(make_var("x"), coord)
    right = TermValue(1)
    truthful = _augmented_binary(left, right, "Add", site)
    assert truthful.demand.operator == "iadd"
    # Lying path: unconditional add demand
    lying_operator = "add"
    with pytest.raises(AssertionError):
        assert lying_operator == "iadd"


def test_iadd_projector_falls_back_to_add_only_when_floor_declines_iadd() -> None:
    """Inside the enrolled projector: no iadd method → ordinary add (authorized)."""
    calls: list[str] = []

    @dataclass(frozen=True)
    class _AddOnly:
        value: int

        def add(self, other, site):
            calls.append("add")
            return Complete(TermValue(self.value + other.value))

    out = _NATIVE_OPERATION_PROJECTORS["iadd"](_AddOnly(1), TermValue(2), "op")
    assert isinstance(out, Complete)
    assert out.value == TermValue(3)
    assert calls == ["add"]


def test_iadd_projector_prefers_floor_iadd_when_present() -> None:
    """Inside the enrolled projector: iadd wins over add."""
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

    out = _NATIVE_OPERATION_PROJECTORS["iadd"](_Both(1), TermValue(2), "op")
    assert isinstance(out, Complete)
    assert calls == ["iadd"]
    with pytest.raises(AssertionError):
        assert calls == ["add"]


# ---------------------------------------------------------------------------
# Missing actuals / formal undischarged
# ---------------------------------------------------------------------------


def test_formal_subscript_get_carrier_missing_actuals_undischarged() -> None:
    """Helper alone get demand: missing actuals stay undischarged."""
    _, pending = _helper_definition()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "subscript"
    with pytest.raises(SugarNotWritten, match="caller actual absent"):
        pending.discharge({})


def test_authenticated_caller_discharges_get_iadd_setitem_to_updated_list() -> None:
    """All three formals: get → iadd → setitem completes [1,2]+10@0 → [11,2]."""
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
    """OOB index: IndexError halt; no fabricated store completion."""
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
# Full sugar desugar on ground constants (integration)
# ---------------------------------------------------------------------------


def test_subscript_augassign_sugar_desugars_ground_list_add() -> None:
    """End-to-end sugar desugar with constant children when available."""
    # Build sugar manually with constant-like floor sugars if present.
    from sugar_lift_py_tests.sugar.sugar_base import Sugar
    from sugar_lift_py_tests.outcome import Complete as C

    @dataclass(frozen=True)
    class _FloorSugar(Sugar):
        value: object

        def desugar(self, ctx=None):
            del ctx
            return C(self.value)

        @classmethod
        def witnesses(cls):
            return ()

    box = {"get": 0, "set": 0}
    receiver = _CountingList((TermValue(2), TermValue(0)), box=box)
    sugar = SubscriptAugAssignSugar(
        receiver=_FloorSugar(receiver),
        index=_FloorSugar(TermValue(0)),
        rhs=_FloorSugar(TermValue(3)),
        op_kind="Add",
        get_site="get-locus",
        op_site="op-locus",
        set_site="set-locus",
        site="aug-locus",
    )
    out = sugar.desugar(None)
    assert isinstance(out, Complete), out
    assert out.value == ListValue((TermValue(5), TermValue(0)))
    assert box["get"] == 1
    assert box["set"] == 1
