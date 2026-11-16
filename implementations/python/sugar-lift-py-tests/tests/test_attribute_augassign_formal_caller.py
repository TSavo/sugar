"""Formal attribute augmented assignment: ``obj.field += rhs``.

Same substrate as subscript AugAssign (#6712): once-eval, get before RHS,
``project_augmented`` / ``InplaceBinaryOperatorOperation`` edge, the one field
store last (``ReceiverFieldStoreStatement``: the receiver evaluated once and
bound under its key, the value ``AttributeAugAssignSugar``, the store
``ReceiverFieldStoreSugar``), halt blocking, distinct get/op/set sites,
NotImplemented fallback via production projector.  No second dispatch table
or control ladder.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.caller_parameter_contract import (
    NativeOperationExitCarrierV1,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import (
    ObjectField,
    ObjectValue,
    TermValue,
)
from sugar_lift_py_tests.floor.receiver_field_store_value import (
    ReceiverFieldStoreValue,
)
from sugar_lift_py_tests.outcome import Completed, ExitSet
from sugar_lift_py_tests.sugar.assign_sugar import KeyedStoreSugar
from sugar_lift_py_tests.sugar.augassign_sugar import (
    AttributeAugAssignSugar,
    project_augmented,
)
from sugar_lift_py_tests.sugar.receiver_field_store_sugar import (
    ReceiverFieldStoreSugar,
)
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import AugAssign, FunctionDef
from sugar_source_tree.operators import Add, BinaryOperator
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


def _aug_statement(source: str = "def helper(obj, rhs):\n    obj.field += rhs\n"):
    """The statement's sugar: the one field store, keyed, whose value is the
    field's in-place result."""
    tree = _tree(source)
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    aug = next(node for node in function.body if isinstance(node, AugAssign))
    keyed = aug.sugar()
    assert isinstance(keyed, KeyedStoreSugar), type(keyed)
    assert isinstance(keyed.value, AttributeAugAssignSugar), type(keyed.value)
    assert isinstance(keyed.store, ReceiverFieldStoreSugar), type(keyed.store)
    return function, keyed


def _aug_sugar(source: str = "def helper(obj, rhs):\n    obj.field += rhs\n"):
    function, keyed = _aug_statement(source)
    return function, keyed.value


def _production_sites():
    _, keyed = _aug_statement()
    value = keyed.value
    return value.current.site, value.op_site, keyed.store.site, value.site


@dataclass(frozen=True)
class _FieldRead(Sugar):
    """The field's read off ``receiver``: the one attribute lookup, as
    ``AttributeSugar`` reads it (its receiver here a plain test sugar)."""

    receiver: Sugar
    attr: str
    site: object

    def desugar(self, ctx=None):
        from sugar_lift_py_tests.sugar.attribute_sugar import AttributeSugar

        return self.receiver.desugar(ctx).and_then(
            lambda receiver: AttributeSugar.project_attribute(
                receiver, self.attr, self.site, ctx
            )
        )

    @classmethod
    def witnesses(cls):
        return ()


def _project_iadd(left, right, site, ctx):
    """``left += right`` through the ``+`` operator's own in-place edge
    (``BinaryOperator.project_inplace``), as the statement runs it."""
    return Add.instance().project_inplace(left, right, site, ctx)


def _read_modify_store(receiver, rhs, *, operation=_project_iadd, attr="field"):
    """``receiver.attr OP= rhs`` as the statement runs it: the field's
    in-place result (``AttributeAugAssignSugar``) of its read, then the one
    field store of it on the same receiver (``ReceiverFieldStoreSugar``)."""
    get_site, op_site, set_site, site = _production_sites()
    value = AttributeAugAssignSugar(
        current=_FieldRead(receiver, attr, get_site),
        rhs=rhs,
        operation=operation,
        op_site=op_site,
        site=site,
    )
    return value.desugar(None).and_then(
        lambda result: ReceiverFieldStoreSugar(
            receiver=receiver, value=_FloorSugar(result), attr=attr, site=set_site
        ).desugar(None)
    )


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
    return _read_modify_store(_FloorSugar(receiver), _FloorSugar(rhs), attr=attr)


def _stored(out):
    stored = out.completed_value()
    assert isinstance(stored, ReceiverFieldStoreValue), out
    return stored


# ---------------------------------------------------------------------------
# Construction / occurrence
# ---------------------------------------------------------------------------


def test_attribute_augassign_constructs_attribute_augassign_sugar() -> None:
    _, keyed = _aug_statement()
    sugar = keyed.value
    assert isinstance(sugar, AttributeAugAssignSugar)
    assert sugar.current.name == "field"
    assert not hasattr(sugar, "operator")
    assert sugar.operation.__func__ is BinaryOperator.project_inplace
    assert type(sugar.operation.__self__) is Add
    # The receiver is evaluated once, first, and bound under its key: the
    # read and the store read it there.
    assert keyed.receiver is not None
    assert isinstance(keyed.receiver_evaluation, str)
    assert sugar.current.receiver == keyed.store.receiver
    get_site, op_site, set_site, _site = _production_sites()
    assert get_site is not op_site
    assert op_site is not set_site
    assert get_site is not set_site


def test_op_site_is_structural_gap_not_rhs() -> None:
    function, sugar = _aug_sugar()
    aug = next(node for node in function.body if isinstance(node, AugAssign))
    assert sugar.op_site is not aug.value.fragment
    text = sugar.op_site.unit.source[sugar.op_site.span.start : sugar.op_site.span.end]
    assert "+=" in text


def test_discrimination_not_plain_store_of_the_rhs() -> None:
    """AugAssign attribute stores the field's in-place result, never the
    bare RHS."""
    function, keyed = _aug_statement()
    aug = next(node for node in function.body if isinstance(node, AugAssign))
    assert isinstance(keyed.value, AttributeAugAssignSugar)
    assert keyed.value.rhs == aug.value.sugar()
    assert keyed.value != aug.value.sugar()


# ---------------------------------------------------------------------------
# Production desugar: complete / once / order / halt
# ---------------------------------------------------------------------------


def test_production_desugar_object_field_augassign_completes() -> None:
    """``obj.field += 10`` on field=1 → field=11."""
    out = _production_desugar(_obj_with_field(1), TermValue(10))
    stored = _stored(out)
    assert stored.attr == "field"
    assert stored.value == TermValue(11)
    after = stored.receiver.with_field_store(stored.attr, stored.value)
    fields = {f.name: f.value for f in after.fields}
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
    stored = _stored(out)
    assert box["get"] == 1
    assert box["set"] == 1
    assert stored.value == TermValue(5)


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
        return _project_iadd(left, right, site_, ctx)

    out = _read_modify_store(
        _FloorSugar(
            _OrderObject(
                "Widget",
                (ObjectField("field", TermValue(3)),),
                (),
                (),
                "o0",
                allocation=FRAME_FRESH,
            )
        ),
        _RhsOrder(),
        operation=_project_order,
    )
    assert out.completed_value() is not None
    assert order == ["get", "rhs", "op", "set"]


def test_discrimination_wrong_order_rhs_before_get() -> None:
    order = ["rhs", "get"]
    with pytest.raises(AssertionError):
        assert order == ["get", "rhs", "op", "set"]


def _widget_class_value():
    """The class value of ``class Widget: pass``: its MRO is a source class
    and ``object``, and no class of it binds ``__getattr__``."""
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )
    from sugar_lift_py_tests.floor.class_definition_value import (
        ClassDefinitionValue,
    )
    from sugar_source_tree.nodes import ClassDef

    tree = SourceFile(
        (
            "class Widget:\n    pass\n",
            "widget_class.py",
            blake3_512_of(b"class Widget:\n    pass\n"),
        ),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    (statement,) = (node for node in tree.root.body if isinstance(node, ClassDef))
    span = statement.binding_target.line_col_span()
    return ClassDefinitionValue(
        class_name=statement.name,
        class_definition_cid=statement.fragment.seal().cid,
        methods=(),
        initializer=None,
        binding_target_occurrence=SourceFragmentCoordinateV1(
            statement.unit.source_cid,
            span.start_line,
            span.start_col,
            span.end_line,
            span.end_col,
        ),
        class_definition=statement,
    )


def test_production_get_halt_blocks_rhs_arithmetic_and_store() -> None:
    """A fresh ``Widget`` with no ``field``: the read raises AttributeError
    (Python's absence rule), and that halt blocks the RHS, the arithmetic
    and the store."""
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

    class _StoreCounting(ObjectValue):
        def setattr(self, name, value, site_, ctx):
            box["set"] += 1
            return super().setattr(name, value, site_, ctx)

    # Empty fields, a source class over ``object``: the read is AttributeError.
    receiver = _StoreCounting(
        "Widget",
        (),
        (),
        (),
        "empty",
        defining_class=_widget_class_value(),
        allocation=FRAME_FRESH,
    )
    out = _read_modify_store(_FloorSugar(receiver), _RhsProbe())
    assert out.completed_value() is None, out
    names = [
        halt.effect.exception_name
        for halt in out.halts()
        if isinstance(halt.effect, RaiseEffect)
    ]
    assert names == ["AttributeError"], out
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
    """Store AttributeError via the one field store: one halted arm, never a completion."""
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
    # The one field store hands the floor's halt on.
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
# Formal: the undecided read / a decided receiver through the same doors
# ---------------------------------------------------------------------------


def _own_exits(outcome) -> ExitSet:
    """The helper's own proof's exits: a carrier another operation of the
    chain still mints (the in-place ``iadd`` over a formal ``rhs``, not this
    family) discharged with no actual, every arm composed beside it kept
    (#7825); an ``ExitSet`` as it stands."""
    if isinstance(outcome, NativeOperationExitCarrierV1):
        return outcome.discharge(None, {})
    assert isinstance(outcome, ExitSet), type(outcome)
    return outcome


def test_helper_alone_get_leg_is_the_undecided_read_not_a_carrier() -> None:
    """Expected shape changed (#7757 audit 2 row NEW-1): the get leg
    ``obj.field`` on a formal was an ``attribute_named`` carrier waiting on
    a caller's actual production never supplies.  A read is
    ``__getattribute__`` then ``__getattr__``, a protocol no one dispatched
    method states, so on a formal it is the one two-faced undecided read
    (``SymbolicValue.attribute``): its halt kept, the undecided member
    owed, never a completion."""
    from sugar_lift_py_tests.unanswered_calls import owed_calls, unanswered_call

    _, outcome = _helper_definition()
    assert getattr(getattr(outcome, "demand", None), "operator", None) != (
        "attribute_named"
    )
    exits = _own_exits(outcome)
    halts = [
        face
        for face in exits.halts()
        if face.effect.producer_node_owner == "SymbolicValue.attribute"
    ]
    assert len(halts) == 1, exits
    (halt,) = halts
    assert unanswered_call(None, halt.effect.site) in owed_calls(exits)
    assert exits.completed_value() is None


def test_decided_receiver_get_iadd_setattr_updates_field() -> None:
    """The check that rode the carrier's discharge, on the decided actual
    through the same doors: the read (``AttributeSugar.project_attribute``),
    the in-place edge, and the one field store, ``1 + 10`` stored."""
    receiver = _obj_with_field(1)
    exits = _production_desugar(receiver, TermValue(10))
    assert isinstance(exits, ExitSet)
    assert len(exits.exits) == 1
    assert isinstance(exits.exits[0], Completed)
    stored = _stored(exits)
    assert stored.value == TermValue(11)


def test_enum_attribute_augassign_owner_reads_its_undecided_global_as_its_input() -> (
    None
):
    """CPython ``enum.py:292`` (``enum_class._flag_mask_ |= value``) sits in
    ``_proto_member.__set_name__``, which reads the module global ``Flag``.

    ``enum.py`` binds ``Flag`` twice (``Flag = None``, then ``class Flag``),
    and the module body's threading does not decide which binding stands
    where ``__set_name__`` runs.  A name the module body does not decide is
    never read by name in its place: it is read through its undecided key
    (``undecided_module_binding_key``), the function's free ``global:Flag``
    input with no stated value (#8704), and the function is built, never
    refused for it.  The read/operate/store chain at line 292 is asserted on
    a source whose globals the module decides
    (``test_unrelated_source_attribute_augassign_uses_the_same_projection``).
    """
    from sugar_lift_python_source.dependency_artifact import DependencyArtifactGraph
    from sugar_source_tree.panic import SugarNotWritten

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
    from sugar_source_tree.nodes import EvaluationRef, undecided_module_binding_key

    read = owner._module_global_references()["Flag"]
    assert isinstance(read, EvaluationRef)
    assert read.evaluation == undecided_module_binding_key(owner.unit, "Flag")
    try:
        owner.sugar()
    except SugarNotWritten as refused:
        assert "undecided module binding" not in refused.observed, refused


def test_unrelated_source_attribute_augassign_uses_the_same_projection() -> None:
    """A renamed source helper uses the same read/inplace/store chain: its
    get leg is the undecided read on its formal, never an
    ``attribute_named`` carrier, and a decided receiver completes through
    the same doors."""
    _, outcome = _helper_definition(
        "def renamed(receiver, increment):\n" "    receiver.total += increment\n"
    )
    assert getattr(getattr(outcome, "demand", None), "operator", None) != (
        "attribute_named"
    )
    assert [
        face
        for face in _own_exits(outcome).halts()
        if face.effect.producer_node_owner == "SymbolicValue.attribute"
    ]
    receiver = ObjectValue(
        "Renamed",
        (ObjectField("total", TermValue(4)),),
        (),
        (),
        "renamed-receiver",
        allocation=FRAME_FRESH,
    )

    result = _production_desugar(receiver, TermValue(3), attr="total")

    assert isinstance(result, ExitSet)
    assert len(result.exits) == 1
    assert isinstance(result.exits[0], Completed)
    assert _stored(result).value == TermValue(7)


def test_formal_operands_mint_no_carrier() -> None:
    """Inverted from the deleted ``iadd`` mint (#7757, audit row NEW-1): a
    formal's ``cell += rhs`` is the operator's own in-place edge, the
    undecided binary law's two faces, owing the undecided member."""
    from sugar_lift_py_tests.caller_parameter_contract import (
        _NATIVE_OPERATION_PROJECTORS,
    )
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome import Halted
    from sugar_lift_py_tests.unanswered_calls import owed_calls, unanswered_call

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
    out = project_augmented(left, right, projector=_project_iadd, site=site, ctx=None)
    assert not isinstance(out, NativeOperationExitCarrierV1)
    assert isinstance(out, ExitSet), type(out)
    (completed,) = [face for face in out.exits if isinstance(face, Completed)]
    assert completed.value.term.name == "python:binary_result"
    assert completed.value.term.args[0].value == "+"
    (halted,) = [face for face in out.exits if isinstance(face, Halted)]
    assert isinstance(halted.effect, UndeterminedRaiseEffect)
    assert halted.effect.producer_node_owner == "UndecidedBinary:+"
    assert unanswered_call(None, site) in owed_calls(out)
    assert "iadd" not in _NATIVE_OPERATION_PROJECTORS


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

    out = _project_iadd(_RawNI(), TermValue(1), "op", None)
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

    out = _project_iadd(_CompleteNI(), TermValue(1), "op", None)
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

    assert _project_iadd(_Inc(), TermValue(1), "op", None) is face
