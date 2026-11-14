"""Formal attribute augmented assignment: ``obj.field += rhs``.

Same substrate as subscript AugAssign (#6712): once-eval, get before RHS,
``project_augmented`` / ``InplaceBinaryOperatorOperation`` edge, setattr last,
halt blocking, distinct get/op/set sites, NotImplemented fallback via production
projector.  No second dispatch table or control ladder.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.caller_parameter_contract import (
    NativeOperationExitCarrierV1,
    project_iadd,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import (
    ObjectField,
    ObjectValue,
    TermValue,
)
from sugar_lift_py_tests.outcome import Completed, ExitSet
from sugar_lift_py_tests.sugar.augassign_sugar import (
    AttributeAugAssignSugar,
    project_augmented,
)
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import AugAssign, FunctionDef
from sugar_source_tree.operators import Add, BinaryOperator
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.effect import RaiseEffect

from frame_fresh import FRAME_FRESH


def _tree(source: str, name: str = "attribute_augassign.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _helper_definition(
    source: str = "def helper(obj, rhs):\n    obj.field += rhs\n",
):
    tree = _tree(source, "helper_alone.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function, function.sugar().desugar(None)


def _aug_sugar(source: str = "def helper(obj, rhs):\n    obj.field += rhs\n"):
    tree = _tree(source)
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    aug = next(node for node in function.body if isinstance(node, AugAssign))
    sugar = aug.sugar()
    assert isinstance(sugar, AttributeAugAssignSugar), type(sugar)
    return function, sugar


def _production_sites():
    _, sugar = _aug_sugar()
    return sugar.get_site, sugar.op_site, sugar.set_site, sugar.site


@dataclass(frozen=True)
class _FloorSugar(Sugar):
    value: object

    def desugar(self, ctx=None):
        del ctx
        return ExitSet.completed(self.value)

    @classmethod
    def witnesses(cls):
        return ()


def _obj_with_field(n: int = 1) -> ObjectValue:
    return ObjectValue(
        "Widget",
        (ObjectField("field", TermValue(n)),),
        (),
        (),
        "w0",
        allocation=FRAME_FRESH,
    )


def _production_desugar(receiver, rhs, *, attr="field"):
    get_site, op_site, set_site, site = _production_sites()
    sugar = AttributeAugAssignSugar(
        receiver=_FloorSugar(receiver),
        attr=attr,
        rhs=_FloorSugar(rhs),
        operator="iadd",
        operation=project_iadd,
        get_site=get_site,
        op_site=op_site,
        set_site=set_site,
        site=site,
    )
    return sugar.desugar(None)


# ---------------------------------------------------------------------------
# Construction / occurrence
# ---------------------------------------------------------------------------


def test_attribute_augassign_constructs_attribute_augassign_sugar() -> None:
    _, sugar = _aug_sugar()
    assert isinstance(sugar, AttributeAugAssignSugar)
    assert sugar.attr == "field"
    assert sugar.operator == "iadd"
    assert sugar.operation.__func__ is BinaryOperator.project_inplace
    assert sugar.get_site is not sugar.op_site
    assert sugar.op_site is not sugar.set_site
    assert sugar.get_site is not sugar.set_site


def test_op_site_is_structural_gap_not_rhs() -> None:
    function, sugar = _aug_sugar()
    aug = next(node for node in function.body if isinstance(node, AugAssign))
    assert sugar.op_site is not aug.value.fragment
    text = sugar.op_site.unit.source[sugar.op_site.span.start : sugar.op_site.span.end]
    assert "+=" in text


def test_discrimination_not_plain_attribute_store_effect() -> None:
    """AugAssign attribute is AttributeAugAssignSugar, not bare store-of-RHS."""
    from sugar_lift_py_tests.sugar.store_effect_sugar import AttributeStoreEffectSugar

    _, sugar = _aug_sugar()
    assert not isinstance(sugar, AttributeStoreEffectSugar)


# ---------------------------------------------------------------------------
# Production desugar: complete / once / order / halt
# ---------------------------------------------------------------------------


def test_production_desugar_object_field_augassign_completes() -> None:
    """``obj.field += 10`` on field=1 → field=11."""
    out = _production_desugar(_obj_with_field(1), TermValue(10))
    assert out.completed_value() is not None, out
    assert isinstance(out.completed_value(), ObjectValue)
    fields = {f.name: f.value for f in out.completed_value().fields}
    assert fields["field"] == TermValue(11)


def test_production_receiver_evaluated_once_for_get_and_set() -> None:
    box = {"get": 0, "set": 0}

    class _CountingObject(ObjectValue):
        def attribute(self, name, site, ctx):
            box["get"] += 1
            return super().attribute(name, site, ctx)

        def setattr(self, name, value, site, ctx):
            box["set"] += 1
            return super().setattr(name, value, site, ctx)

    receiver = _CountingObject(
        "Widget",
        (ObjectField("field", TermValue(2)),),
        (),
        (),
        "c0",
        allocation=FRAME_FRESH,
    )
    out = _production_desugar(receiver, TermValue(3))
    assert out.completed_value() is not None
    assert box["get"] == 1
    assert box["set"] == 1
    fields = {f.name: f.value for f in out.completed_value().fields}
    assert fields["field"] == TermValue(5)


def test_discrimination_duplicated_get_is_detected() -> None:
    box = {"get": 0}

    class _CountingObject(ObjectValue):
        def attribute(self, name, site, ctx):
            box["get"] += 1
            return super().attribute(name, site, ctx)

    r = _CountingObject(
        "Widget",
        (ObjectField("field", TermValue(1)),),
        (),
        (),
        "d0",
        allocation=FRAME_FRESH,
    )
    r.attribute("field", "g1", None)
    r.attribute("field", "g2", None)
    assert box["get"] == 2
    with pytest.raises(AssertionError):
        assert box["get"] == 1


def test_production_getattr_before_rhs_order() -> None:
    order: list[str] = []
    get_site, op_site, set_site, site = _production_sites()

    class _OrderObject(ObjectValue):
        def attribute(self, name, site_, ctx):
            order.append("get")
            return super().attribute(name, site_, ctx)

        def setattr(self, name, value, site_, ctx):
            order.append("set")
            return super().setattr(name, value, site_, ctx)

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

    sugar = AttributeAugAssignSugar(
        receiver=_FloorSugar(
            _OrderObject(
                "Widget",
                (ObjectField("field", TermValue(3)),),
                (),
                (),
                "o0",
                allocation=FRAME_FRESH,
            )
        ),
        attr="field",
        rhs=_RhsOrder(),
        operator="iadd",
        operation=_project_order,
        get_site=get_site,
        op_site=op_site,
        set_site=set_site,
        site=site,
    )
    out = sugar.desugar(None)
    assert out.completed_value() is not None
    assert order ==["get", "rhs", "op", "set"]


def test_discrimination_wrong_order_rhs_before_get() -> None:
    order = ["rhs", "get"]
    with pytest.raises(AssertionError):
        assert order == ["get", "rhs", "op", "set"]


def test_production_get_halt_blocks_rhs_arithmetic_and_store() -> None:
    """Missing field → AttributeError undecided or halt; no store."""
    box = {"rhs": 0, "set": 0}
    get_site, op_site, set_site, site = _production_sites()

    @dataclass(frozen=True)
    class _RhsProbe(Sugar):
        def desugar(self, ctx=None):
            del ctx
            box["rhs"] += 1
            return ExitSet.completed(TermValue(99))

        @classmethod
        def witnesses(cls):
            return ()

    class _StoreCounting(ObjectValue):
        def setattr(self, name, value, site_, ctx):
            box["set"] += 1
            return super().setattr(name, value, site_, ctx)

    # Empty fields — attribute read is undecided / AttributeError path
    receiver = _StoreCounting(
        "Widget", (), (), (), "empty", allocation=FRAME_FRESH
    )
    sugar = AttributeAugAssignSugar(
        receiver=_FloorSugar(receiver),
        attr="field",
        rhs=_RhsProbe(),
        operator="iadd",
        operation=project_iadd,
        get_site=get_site,
        op_site=op_site,
        set_site=set_site,
        site=site,
    )
    # Undecided attribute raises SugarNotWritten — get halt blocks RHS.
    with pytest.raises(SugarNotWritten):
        sugar.desugar(None)
    assert box["rhs"] == 0
    assert box["set"] == 0


def test_production_arithmetic_halt_blocks_store() -> None:
    box = {"set": 0}

    class _StoreCounting(ObjectValue):
        def setattr(self, name, value, site, ctx):
            box["set"] += 1
            return super().setattr(name, value, site, ctx)

    from sugar_lift_py_tests.floor import NoneValue

    receiver = _StoreCounting(
        "Widget",
        (ObjectField("field", TermValue(1)),),
        (),
        (),
        "a0",
        allocation=FRAME_FRESH,
    )
    out = _production_desugar(receiver, NoneValue())
    assert box["set"] == 0
    assert not (
        out.completed_value() is not None
        and isinstance(out.completed_value(), ObjectValue)
        and box["set"]
    )


def test_production_store_halt_is_incomplete_not_complete_raisevalue() -> None:
    """Store AttributeError via shared project_setattr: one halted arm, never a completion."""
    from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

    class _RefuseSet(ObjectValue):
        def setattr(self, name, value, site_, ctx):
            return ground_exceptional_exit(
                exception_name="AttributeError",
                site=site_,
                owner="_RefuseSet.setattr",
            )

    receiver = _RefuseSet(
        "Widget",
        (ObjectField("field", TermValue(5)),),
        (),
        (),
        "refuse0",
        allocation=FRAME_FRESH,
    )
    out = _production_desugar(receiver, TermValue(1))
    # Shared AttributeStoreEffectSugar.project_setattr hands the floor's halt on.
    assert (
        len(out.exits) == 1 and out.halts() == out.exits
    ), f"store halt must be one halted arm (halted store face), not {out}"
    (halt,) = out.halts()
    assert isinstance(halt.effect, RaiseEffect)
    # Discrimination: a completed store would greenwash statement completion.
    with pytest.raises(AssertionError):
        assert out.completed_value() is not None and isinstance(
            out.completed_value(), ObjectValue
        )


# ---------------------------------------------------------------------------
# Formal undischarged / authenticated discharge
# ---------------------------------------------------------------------------


def test_helper_alone_is_undischarged_attribute_named_get_carrier() -> None:
    _, pending = _helper_definition()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    # First demand is the get leg (attribute_named), not setattr.
    assert pending.demand.operator == "attribute_named"
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    # No caller actual: the get leg is the cited unanswered face (#7825).
    exits = pending.discharge(None, {})
    assert pending.unanswered_call() in owed_calls(exits)
    assert exits.completed_value() is None


def test_authenticated_discharge_get_iadd_setattr_updates_field() -> None:
    function, pending = _helper_definition()
    assert isinstance(pending, NativeOperationExitCarrierV1)
    coords = {
        c.declared_name: c.coordinate_cid for c in function.sugar().formal_coordinates
    }
    receiver = _obj_with_field(1)
    exits = pending.discharge(
        None,
        {
            coords["obj"]: receiver,
            coords["rhs"]: TermValue(10),
        },
    )
    assert isinstance(exits, ExitSet)
    assert len(exits.exits) == 1
    assert isinstance(exits.exits[0], Completed)
    value = exits.exits[0].value
    # Universe or ObjectValue post-state
    if isinstance(value, ObjectValue):
        fields = {f.name: f.value for f in value.fields}
        assert fields["field"] == TermValue(11)
    else:
        record = getattr(value, "record", None)
        assert record is not None
        objs = [s for s in record.statements if isinstance(s, ObjectValue)]
        assert objs, record.statements
        fields = {f.name: f.value for f in objs[-1].fields}
        assert fields["field"] == TermValue(11)


def test_enum_attribute_augassign_uses_one_authenticated_read_op_store(
    monkeypatch,
) -> None:
    """Production path: CPython ``enum.py:292`` retains the exact operation chain."""
    from sugar_lift_python_source.dependency_artifact import DependencyArtifactGraph
    from sugar_lift_py_tests.sugar import augassign_sugar as aug_module
    from sugar_lift_py_tests.sugar.attribute_sugar import AttributeSugar
    from sugar_lift_py_tests.sugar.store_effect_sugar import AttributeStoreEffectSugar

    graph = DependencyArtifactGraph.authenticate_stdlib_module("enum")
    module = graph.modules["enum"]
    source = SourceFile(
        (module.source, module.source_seat, module.source_cid),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    owner = min(
        (
            node
            for node in source.nodes()
            if isinstance(node, FunctionDef)
            and node.line_col_span().start_line < 292
            and node.line_col_span().end_line >= 292
        ),
        key=lambda node: node.line_col_span().end_line
        - node.line_col_span().start_line,
    )
    events = []
    original_read = AttributeSugar.project_attribute
    original_op = aug_module.project_augmented
    original_store = AttributeStoreEffectSugar.project_setattr

    def at_target(site) -> bool:
        return site.line_col_span().start_line == 292

    def read(receiver, member, site, ctx):
        if at_target(site):
            events.append(("read", receiver, member, site))
        return original_read(receiver, member, site, ctx)

    def operate(left, right, *, operator, projector, site, ctx):
        if at_target(site):
            events.append(("operate", left, operator, site))
        return original_op(
            left,
            right,
            operator=operator,
            projector=projector,
            site=site,
            ctx=ctx,
        )

    def store(receiver, member, value, site, ctx):
        if at_target(site):
            events.append(("store", receiver, member, site))
        return original_store(receiver, member, value, site, ctx)

    monkeypatch.setattr(AttributeSugar, "project_attribute", staticmethod(read))
    monkeypatch.setattr(aug_module, "project_augmented", operate)
    monkeypatch.setattr(
        AttributeStoreEffectSugar, "project_setattr", staticmethod(store)
    )

    owner.sugar().desugar(None)

    assert tuple(event[0] for event in events) == ("read", "operate", "store")
    read_event, op_event, store_event = events
    assert read_event[1] is store_event[1]
    assert read_event[2] == store_event[2] == "_flag_mask_"
    assert op_event[2] == "ior"
    assert len({event[3].source_cid for event in events}) == 1


def test_unrelated_source_attribute_augassign_uses_the_same_projection() -> None:
    """A renamed source helper uses the same read/inplace/store carrier chain."""
    function, pending = _helper_definition(
        "def renamed(receiver, increment):\n" "    receiver.total += increment\n"
    )
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "attribute_named"
    coordinates = {
        coordinate.declared_name: coordinate.coordinate_cid
        for coordinate in function.sugar().formal_coordinates
    }
    receiver = ObjectValue(
        "Renamed",
        (ObjectField("total", TermValue(4)),),
        (),
        (),
        "renamed-receiver",
        allocation=FRAME_FRESH,
    )

    result = pending.discharge(
        None,
        {
            coordinates["receiver"]: receiver,
            coordinates["increment"]: TermValue(3),
        },
    )

    assert isinstance(result, ExitSet)
    assert len(result.exits) == 1
    assert isinstance(result.exits[0], Completed)


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
        left, right, operator="iadd", projector=project_iadd, site=site, ctx=None
    )
    assert isinstance(out, NativeOperationExitCarrierV1)
    assert out.demand.operator == "iadd"
    with pytest.raises(AssertionError):
        assert out.demand.operator == "add"


def test_notimplemented_fallback_twins_via_production_projector() -> None:
    """Same NotImplemented law as subscript: raw / ExitSet.completed(NI) → binary."""
    from sugar_lift_py_tests.floor.floor_value import FloorValue

    calls: list[str] = []

    class _RawNI(FloorValue):
        def inplace_binary_operator_with(self, operation, ctx):
            del operation, ctx
            calls.append("inplace")
            return NotImplemented

        def add(self, other, site, ctx):
            calls.append("add")
            return ExitSet.completed(TermValue(3))

    out = project_iadd(_RawNI(), TermValue(1), "op", None)
    assert out.completed_value() == TermValue(3)
    assert calls == ["inplace", "add"]
    calls.clear()

    class _CompleteNI(FloorValue):
        def inplace_binary_operator_with(self, operation, ctx):
            del operation, ctx
            calls.append("inplace")
            return ExitSet.completed(NotImplemented)  # type: ignore[arg-type]

        def add(self, other, site, ctx):
            calls.append("add")
            return ExitSet.completed(TermValue(4))

    out = project_iadd(_CompleteNI(), TermValue(1), "op", None)
    assert out.completed_value() == TermValue(4)
    assert calls == ["inplace", "add"]


def test_discrimination_incomplete_does_not_fall_through() -> None:
    from sugar_lift_py_tests.effect import CoverageGapEffect
    from sugar_lift_py_tests.floor.floor_value import FloorValue

    face = ExitSet.halted(
        CoverageGapEffect(boundary="iadd", reason="unresolved inplace")
    )

    class _Inc(FloorValue):
        def inplace_binary_operator_with(self, operation, ctx):
            del operation, ctx
            return face

        def add(self, other, site, ctx):
            return ExitSet.completed(TermValue(0))

    assert project_iadd(_Inc(), TermValue(1), "op", None) is face
