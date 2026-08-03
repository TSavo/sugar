"""Formal ``delitem`` / ``delattr_named`` through the n-ary projector family.

Python semantic law made constructible (mirrors setitem / setattr_named):

  def helper(obj, key):
      del obj[key]

  def helper2(obj):
      del obj.field

Helper alone retains the respective delete demand as an undischarged
``NativeOperationExitCarrierV1``. Authenticated callers discharge; mutable
receivers complete with the element/attribute gone; missing key → named
KeyError; missing/read-only attribute → named AttributeError — each with
exact pre-effect state. Missing caller actual stays Undischarged. Earlier
bindings survive later delete halts. Swapped-coordinate and
read-authorizes-delete twins fail (readability never authorizes deletion).

Mint contracts (Python protocol signatures; ordered operands + formals):

  operator ``delitem``  (~ ``__delitem__(self, key)``)
  operands ``(receiver, index)``  — discharge order
  projector: ``_project_delitem(receiver, index, site)``
  producer: ``SubscriptDeleteEffectSugar.mint_delitem_carrier``

  operator ``delattr_named``  (~ ``__delattr__(self, name)``)
  operands ``(receiver, StringValue(name))``
  coordinates ``(receiver.formal, None)``
  projector: ``_project_delattr_named(receiver, name, site)``
  producer: ``AttributeDeleteEffectSugar.mint_delattr_named_carrier``

Equality tooth: production-minted operator set == projector-table keys.

Out of scope: Name deletion (``del name`` / DeleteNameSugar) — not delitem,
not delattr_named.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.caller_parameter_contract import (
    NativeOperationExitCarrierV1,
    _NATIVE_OPERATION_PROJECTORS,
    _project_delattr_named,
    _project_delitem,
    production_native_operation_operators,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import (
    BytesValue,
    DictValue,
    ListValue,
    ObjectField,
    ObjectMethodValue,
    ObjectValue,
    SliceValue,
    StringValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.floor.block_value import BlockValue
from sugar_lift_py_tests.floor.return_value import ReturnValue
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted
from sugar_lift_py_tests.sugar.delete_effect_sugar import (
    AttributeDeleteEffectSugar,
    SubscriptDeleteEffectSugar,
)
from sugar_lift_py_tests.sugar.store_effect_sugar import (
    AttributeStoreEffectSugar,
    SubscriptStoreEffectSugar,
)
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import FunctionDef
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile

# ---------------------------------------------------------------------------
# Exact missing producer method names (valid deliverable when red)
# ---------------------------------------------------------------------------

MISSING_DELITEM_PRODUCER = (
    "SubscriptDeleteEffectSugar.mint_delitem_carrier"
    " — formal delitem producer mirroring "
    "SubscriptStoreEffectSugar.mint_setitem_carrier; "
    "operator='delitem', operands=(receiver, index), "
    "projector receiver.delitem(index, site)"
)

MISSING_DELATTR_PRODUCER = (
    "AttributeDeleteEffectSugar.mint_delattr_named_carrier"
    " — formal delattr_named producer mirroring "
    "AttributeStoreEffectSugar.mint_setattr_named_carrier; "
    "operator='delattr_named', operands=(receiver, StringValue(name)), "
    "projector receiver.delattr(name.value, site)"
)

MISSING_DELITEM_PROJECTOR = (
    "_NATIVE_OPERATION_PROJECTORS['delitem'] "
    "— lambda receiver, index, site: receiver.delitem(index, site)"
)

MISSING_DELATTR_PROJECTOR = (
    "_NATIVE_OPERATION_PROJECTORS['delattr_named'] "
    "— lambda receiver, name, site: receiver.delattr(name.value, site)"
)


def _tree(source: str, name: str = "delete_formal_caller.py") -> SourceFile:
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


def _delitem_helper():
    source = "def helper(obj, key):\n    del obj[key]\n"
    tree = _tree(source, "delitem_alone.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function, function.sugar().desugar(None)


def _delattr_helper():
    source = "def helper2(obj):\n    del obj.field\n"
    tree = _tree(source, "delattr_alone.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function, function.sugar().desugar(None)


def _require_delitem_carrier(pending) -> NativeOperationExitCarrierV1:
    if not isinstance(pending, NativeOperationExitCarrierV1):
        raise AssertionError(
            f"missing producer {MISSING_DELITEM_PRODUCER}: "
            f"helper alone must mint undischarged delitem carrier, "
            f"got {type(pending).__name__} {pending!r:.200}"
        )
    if pending.demand.operator != "delitem":
        raise AssertionError(
            f"missing producer {MISSING_DELITEM_PRODUCER}: "
            f"expected operator delitem, got {pending.demand.operator!r}"
        )
    if "delitem" not in _NATIVE_OPERATION_PROJECTORS:
        raise AssertionError(f"missing projector {MISSING_DELITEM_PROJECTOR}")
    return pending


def _require_delattr_carrier(pending) -> NativeOperationExitCarrierV1:
    if not isinstance(pending, NativeOperationExitCarrierV1):
        raise AssertionError(
            f"missing producer {MISSING_DELATTR_PRODUCER}: "
            f"helper2 alone must mint undischarged delattr_named carrier, "
            f"got {type(pending).__name__} {pending!r:.200}"
        )
    if pending.demand.operator != "delattr_named":
        raise AssertionError(
            f"missing producer {MISSING_DELATTR_PRODUCER}: "
            f"expected operator delattr_named, got {pending.demand.operator!r}"
        )
    if "delattr_named" not in _NATIVE_OPERATION_PROJECTORS:
        raise AssertionError(f"missing projector {MISSING_DELATTR_PROJECTOR}")
    return pending


def _assert_named_halt(outcome, expected: str) -> Halted:
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    halted = outcome.exits[0]
    assert isinstance(halted, Halted)
    assert halted.effect.exception_type_coordinate == _identity(expected)
    assert (
        isinstance(halted.effect.occurrence_id, str)
        and ":" in halted.effect.occurrence_id
    ), (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {halted.effect.occurrence_id!r}"
    )
    assert halted.state is not None, (
        "formal delete halt omitted real pre-effect state "
        "(NativeOperationResolutionV1.project / reduce_body collapse)"
    )
    return halted


def _deleted_list(completed_face) -> ListValue:
    assert isinstance(completed_face, Completed)
    value = completed_face.value
    if isinstance(value, ListValue):
        return value
    record = getattr(value, "record", None)
    if record is not None:
        lists = [s for s in record.statements if isinstance(s, ListValue)]
        assert len(lists) == 1, lists
        return lists[0]
    raise AssertionError(f"no ListValue post-state: {type(value).__name__}")


# ===========================================================================
# Missing-producer census (exact method names)
# ===========================================================================


def test_delitem_producer_method_is_enrolled_or_named_missing() -> None:
    """Pin the one-door mint method that store already has."""
    assert hasattr(SubscriptStoreEffectSugar, "mint_setitem_carrier")
    if not hasattr(SubscriptDeleteEffectSugar, "mint_delitem_carrier"):
        raise AssertionError(f"missing producer method {MISSING_DELITEM_PRODUCER}")


def test_delattr_producer_method_is_enrolled_or_named_missing() -> None:
    assert hasattr(AttributeStoreEffectSugar, "mint_setattr_named_carrier")
    if not hasattr(AttributeDeleteEffectSugar, "mint_delattr_named_carrier"):
        raise AssertionError(f"missing producer method {MISSING_DELATTR_PRODUCER}")


def test_delitem_projector_is_enrolled_or_named_missing() -> None:
    """Explicit projector matches Python ``__delitem__(self, key)`` arity."""
    assert "setitem" in _NATIVE_OPERATION_PROJECTORS
    if "delitem" not in _NATIVE_OPERATION_PROJECTORS:
        raise AssertionError(f"missing projector {MISSING_DELITEM_PROJECTOR}")
    projector = _NATIVE_OPERATION_PROJECTORS["delitem"]
    assert projector is _project_delitem
    parameters = tuple(inspect.signature(projector).parameters)
    assert parameters == ("receiver", "index", "site")


def test_delattr_projector_is_enrolled_or_named_missing() -> None:
    """Explicit ``delattr_named(receiver, name, site)`` projector enrolled."""
    assert "setattr_named" in _NATIVE_OPERATION_PROJECTORS
    if "delattr_named" not in _NATIVE_OPERATION_PROJECTORS:
        raise AssertionError(f"missing projector {MISSING_DELATTR_PROJECTOR}")
    projector = _NATIVE_OPERATION_PROJECTORS["delattr_named"]
    assert projector is _project_delattr_named
    parameters = tuple(inspect.signature(projector).parameters)
    assert parameters == ("receiver", "name", "site")


def test_production_minted_operators_equal_projector_keys_including_delete() -> None:
    """Equality tooth: production set == projector keys (delete twins included)."""
    production = production_native_operation_operators()
    projectors = frozenset(_NATIVE_OPERATION_PROJECTORS)
    assert production == projectors, (
        f"missing_projectors={sorted(production - projectors)} "
        f"orphan_projectors={sorted(projectors - production)}"
    )
    assert {"delitem", "delattr_named"} <= production
    assert {"delitem", "delattr_named"} <= projectors


def test_ordered_operands_and_formals_match_protocol_signatures() -> None:
    """Mint coordinate order is protocol discharge order, not source-eval order."""
    _, delitem = _delitem_helper()
    delitem = _require_delitem_carrier(delitem)
    assert delitem.demand.operator == "delitem"
    assert tuple(v.term.name for v in delitem.operands) == ("obj", "key")
    assert list(inspect.signature(_project_delitem).parameters) == [
        "receiver",
        "index",
        "site",
    ]

    _, delattr_c = _delattr_helper()
    delattr_c = _require_delattr_carrier(delattr_c)
    assert delattr_c.demand.operator == "delattr_named"
    assert delattr_c.demand.operand_coordinate_cids == (
        delattr_c.demand.operand_coordinate_cids[0],
        None,
    )
    assert isinstance(delattr_c.operands[1], StringValue)
    assert list(inspect.signature(_project_delattr_named).parameters) == [
        "receiver",
        "name",
        "site",
    ]


def test_name_deletion_is_out_of_scope_for_delitem_and_delattr_named() -> None:
    """``del name`` is DeleteNameSugar territory — not delitem/delattr_named."""
    source = "def helper(x):\n    del x\n"
    tree = _tree(source, "name_delete_out_of_scope.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    pending = function.sugar().desugar(None)
    if isinstance(pending, NativeOperationExitCarrierV1):
        assert pending.demand.operator not in {
            "delitem",
            "delattr_named",
        }, "Name deletion must not mint delitem/delattr_named"
    # Positive: attribute/subscript delete still own those operators.
    _, item = _delitem_helper()
    assert _require_delitem_carrier(item).demand.operator == "delitem"
    _, attr = _delattr_helper()
    assert _require_delattr_carrier(attr).demand.operator == "delattr_named"


# ===========================================================================
# Helper alone retains the delete demand
# ===========================================================================


def test_helper_alone_retains_undischarged_delitem_demand() -> None:
    """``def helper(obj, key): del obj[key]`` → undischarged delitem carrier."""
    _, pending = _delitem_helper()
    pending = _require_delitem_carrier(pending)
    assert len(pending.operands) == 2
    assert len(pending.demand.operand_coordinate_cids) == 2
    cids = pending.demand.operand_coordinate_cids
    assert all(cid is not None for cid in cids)
    assert len(set(cids)) == 2
    assert tuple(value.term.name for value in pending.operands) == ("obj", "key")


def test_helper2_alone_retains_undischarged_delattr_named_demand() -> None:
    """``def helper2(obj): del obj.field`` → undischarged delattr_named carrier."""
    _, pending = _delattr_helper()
    pending = _require_delattr_carrier(pending)
    assert len(pending.operands) == 2
    assert pending.demand.operand_coordinate_cids[0] is not None
    # Static attribute name slot is null — not a formal (mirrors setattr_named).
    assert pending.demand.operand_coordinate_cids[1] is None
    assert isinstance(pending.operands[1], StringValue)
    assert pending.operands[1].value == "field"


def test_discrimination_helper_alone_is_not_completed_delete() -> None:
    """Undischarged demand is not a completed empty body."""
    _, pending = _delitem_helper()
    if isinstance(pending, NativeOperationExitCarrierV1):
        assert not isinstance(pending, Completed)
        assert not isinstance(pending, ExitSet)
        return
    # Until the producer lands, dual Halted+Completed RuntimeEffect is not
    # the formal demand — still red naming the mint method.
    raise AssertionError(
        f"missing producer {MISSING_DELITEM_PRODUCER}: "
        f"helper alone must not collapse to dual ExitSet RuntimeEffect; "
        f"got {type(pending).__name__}"
    )


# ===========================================================================
# Missing caller actual stays Undischarged
# ===========================================================================


def test_missing_caller_actual_is_undischarged_not_completed() -> None:
    _, pending = _delitem_helper()
    pending = _require_delitem_carrier(pending)
    with pytest.raises(SugarNotWritten, match="caller actual absent"):
        pending.discharge({})


def test_partial_caller_actual_is_undischarged_discrimination() -> None:
    _, pending = _delitem_helper()
    pending = _require_delitem_carrier(pending)
    obj_cid, key_cid = pending.demand.operand_coordinate_cids
    completed = pending.discharge(
        {obj_cid: ListValue((TermValue(0),)), key_cid: TermValue(0)}
    )
    assert isinstance(completed.exits[0], Completed)
    with pytest.raises(SugarNotWritten, match="caller actual absent"):
        pending.discharge({obj_cid: ListValue((TermValue(0),))})


# ===========================================================================
# Authenticated callers discharge; mutable receiver completes gone
# ===========================================================================


def test_mutable_list_receiver_completes_delete_with_element_gone() -> None:
    """``del obj[0]`` on ``[0, 1]`` → ListValue([1])."""
    _, pending = _delitem_helper()
    pending = _require_delitem_carrier(pending)
    obj_cid, key_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge(
        {
            obj_cid: ListValue((TermValue(0), TermValue(1))),
            key_cid: TermValue(0),
        }
    )
    assert isinstance(exits, ExitSet)
    assert len(exits.exits) == 1
    assert isinstance(exits.exits[0], Completed)
    assert _deleted_list(exits.exits[0]) == ListValue((TermValue(1),))


def test_mutable_dict_receiver_completes_delete_with_key_gone() -> None:
    """``del obj[key]`` on dict with present key → empty entries."""
    _, pending = _delitem_helper()
    pending = _require_delitem_carrier(pending)
    obj_cid, key_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge(
        {
            obj_cid: DictValue(((StringValue("a"), TermValue(1)),)),
            key_cid: StringValue("a"),
        }
    )
    assert isinstance(exits.exits[0], Completed)
    value = exits.exits[0].value
    if isinstance(value, DictValue):
        assert value.entries == ()
    else:
        record = getattr(value, "record", None)
        assert record is not None
        dicts = [s for s in record.statements if isinstance(s, DictValue)]
        assert dicts and dicts[-1].entries == ()


def test_writable_field_delete_completes_with_attribute_gone() -> None:
    """``del obj.field`` on writable instance field → field absent."""
    _, pending = _delattr_helper()
    pending = _require_delattr_carrier(pending)
    obj_cid, _name_cid = pending.demand.operand_coordinate_cids
    receiver = ObjectValue(
        class_name="Widget",
        fields=(ObjectField("field", TermValue(7)),),
        methods=(),
    )
    exits = pending.discharge({obj_cid: receiver})
    assert isinstance(exits.exits[0], Completed)
    stored = exits.exits[0].value
    record = getattr(stored, "record", None)
    objs = []
    if isinstance(stored, ObjectValue):
        objs = [stored]
    elif record is not None:
        objs = [s for s in record.statements if isinstance(s, ObjectValue)]
    assert objs, f"no ObjectValue post-state: {type(stored).__name__}"
    assert not any(f.name == "field" for f in objs[-1].fields), objs[-1].fields


def test_discrimination_completed_delete_is_not_halted() -> None:
    _, pending = _delitem_helper()
    pending = _require_delitem_carrier(pending)
    obj_cid, key_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge(
        {obj_cid: ListValue((TermValue(0),)), key_cid: TermValue(0)}
    )
    with pytest.raises(AssertionError):
        assert isinstance(exits.exits[0], Halted)


# ===========================================================================
# Missing key / missing attribute → named exceptional faces + pre-effect
# ===========================================================================


def test_missing_dict_key_halts_with_named_keyerror_and_pre_effect_state() -> None:
    _, pending = _delitem_helper()
    pending = _require_delitem_carrier(pending)
    testimony = pending.pre_effect_state
    assert testimony is not None, (
        "method body reducer did not enroll ReducerPreEffectStateV1 on the "
        "formal delitem carrier"
    )
    obj_cid, key_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge(
        {
            obj_cid: DictValue(((StringValue("a"), TermValue(1)),)),
            key_cid: StringValue("missing"),
        }
    )
    halted = _assert_named_halt(exits, "KeyError")
    assert halted.state is testimony.state


def test_missing_list_index_halts_with_named_indexerror_and_pre_effect_state() -> None:
    _, pending = _delitem_helper()
    pending = _require_delitem_carrier(pending)
    obj_cid, key_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge(
        {obj_cid: ListValue((TermValue(0),)), key_cid: TermValue(4)}
    )
    halted = _assert_named_halt(exits, "IndexError")
    assert halted.state is not None


def test_missing_attribute_halts_with_named_attributeerror_and_pre_effect() -> None:
    _, pending = _delattr_helper()
    pending = _require_delattr_carrier(pending)
    testimony = pending.pre_effect_state
    assert (
        testimony is not None
    ), "reducer did not enroll ReducerPreEffectStateV1 on formal delattr_named"
    obj_cid, _ = pending.demand.operand_coordinate_cids
    receiver = ObjectValue(class_name="Widget", fields=(), methods=())
    exits = pending.discharge({obj_cid: receiver})
    halted = _assert_named_halt(exits, "AttributeError")
    assert halted.state is testimony.state


def test_discrimination_present_key_is_not_keyerror() -> None:
    _, pending = _delitem_helper()
    pending = _require_delitem_carrier(pending)
    obj_cid, key_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge(
        {
            obj_cid: DictValue(((StringValue("a"), TermValue(1)),)),
            key_cid: StringValue("a"),
        }
    )
    assert isinstance(exits.exits[0], Completed)
    assert not isinstance(exits.exits[0], Halted)


# ===========================================================================
# Deletion does not roll back earlier bindings
# ===========================================================================


def test_deletion_does_not_roll_back_earlier_bindings_on_keyerror() -> None:
    """Prior store/bindings in pre-effect state survive a KeyError delete halt.

    When formal discharge is available, the halt state is the enrolled
    pre-effect testimony (earlier bindings intact). Floor KeyError alone is
    not a substitute for that composition.
    """
    _, pending = _delitem_helper()
    pending = _require_delitem_carrier(pending)
    assert pending.pre_effect_state is not None
    obj_cid, key_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge(
        {
            obj_cid: DictValue(((StringValue("kept"), TermValue(1)),)),
            key_cid: StringValue("missing"),
        }
    )
    halted = _assert_named_halt(exits, "KeyError")
    # Pre-effect state object identity — not a fabricated empty block.
    assert halted.state is pending.pre_effect_state.state


# ===========================================================================
# Swapped-coordinate and read-authorizes-delete twins
# ===========================================================================


def test_swapped_receiver_index_coordinates_rejected_against_truthful_delete() -> None:
    """Lying mint (receiver/index swapped) must not equal truthful post-state.

    Swapped discharge puts the index formal in the receiver slot; Floor
    ``TermValue.delitem`` refuses loudly (ConstructionPanic).  That is a valid
    discrimination face — the lying mint must not complete the truthful list.
    """
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    function, truthful = _delitem_helper()
    truthful = _require_delitem_carrier(truthful)
    site = function.body[0].fragment
    obj_c, key_c = truthful.coordinates
    # LYING mint: index in receiver slot.
    lying = NativeOperationExitCarrierV1.mint(
        site=site,
        operator="delitem",
        operands=(truthful.operands[1], truthful.operands[0]),
        coordinates=(key_c, obj_c),
    )
    actuals = {
        obj_c.coordinate_cid: ListValue((TermValue(0), TermValue(1))),
        key_c.coordinate_cid: TermValue(0),
    }
    truthful_exits = truthful.discharge(actuals)
    assert isinstance(truthful_exits.exits[0], Completed)
    truthful_list = _deleted_list(truthful_exits.exits[0])
    assert truthful_list == ListValue((TermValue(1),))
    try:
        lying_exits = lying.discharge(actuals)
    except ConstructionPanic:
        # Receiver slot received TermValue — Floor refuses delitem. Discrimination holds.
        return
    lying_face = lying_exits.exits[0]
    if isinstance(lying_face, Completed):
        lying_value = lying_face.value
        if isinstance(lying_value, ListValue):
            assert lying_value != truthful_list
        else:
            assert _deleted_list(lying_face) != truthful_list
    else:
        assert isinstance(lying_face, Halted)


def test_read_does_not_authorize_delete_on_getter_only_property() -> None:
    """Property is readable but delete must not complete (read ≠ delete authority)."""
    _, pending = _delattr_helper()
    pending = _require_delattr_carrier(pending)
    obj_cid, _ = pending.demand.operand_coordinate_cids

    @dataclass(frozen=True)
    class _GetterBody(Sugar):
        def desugar(self, ctx=None):
            del ctx
            return Complete(
                BlockValue((ReturnValue(TermValue(1)),), can_fall_through=False)
            )

        @classmethod
        def witnesses(cls):
            return ()

    # Getter-only property enrolled; no deleter.
    receiver = ObjectValue(
        class_name="Widget",
        fields=(),
        methods=(
            ObjectMethodValue(
                name="field",
                parameters=("self",),
                body=_GetterBody(),
                descriptor_kind="property",
            ),
        ),
    )
    assert any(
        m.name == "field" and m.descriptor_kind == "property" for m in receiver.methods
    )
    exits = pending.discharge({obj_cid: receiver})
    halted = exits.exits[0]
    assert isinstance(
        halted, Halted
    ), "read-authorizes-delete twin: getter-only property must not complete delete"
    assert halted.effect.exception_type_coordinate == _identity("AttributeError")


def test_discrimination_writable_field_is_not_attributeerror_delete() -> None:
    _, pending = _delattr_helper()
    pending = _require_delattr_carrier(pending)
    obj_cid, _ = pending.demand.operand_coordinate_cids
    receiver = ObjectValue(
        class_name="Widget",
        fields=(ObjectField("field", TermValue(1)),),
        methods=(),
    )
    exits = pending.discharge({obj_cid: receiver})
    assert isinstance(exits.exits[0], Completed)
    assert not isinstance(exits.exits[0], Halted)


# ===========================================================================
# Floor-level delete twins (exist today — not a substitute for formal carriers)
# ===========================================================================


def _floor_site():
    """Genuine fragment locus for Floor delitem (not a string blame)."""
    function, _ = _delitem_helper()
    return function.body[0].fragment


@dataclass(frozen=True)
class _FloorSugar(Sugar):
    value: object

    def desugar(self, ctx=None):
        del ctx
        return Complete(self.value)

    @classmethod
    def witnesses(cls):
        return ()


@pytest.mark.parametrize(
    ("receiver", "owner"),
    (
        (StringValue("abc"), "StringValue.delitem"),
        (BytesValue(b"abc"), "BytesValue.delitem"),
        (TupleValue((TermValue(1),)), "TupleValue.delitem"),
    ),
)
def test_immutable_slice_delete_has_exact_typeerror_occurrence(receiver, owner):
    site = _floor_site()
    outcome = SubscriptDeleteEffectSugar(
        _FloorSugar(receiver),
        _FloorSugar(SliceValue(TermValue(0), TermValue(1), None)),
        site,
    ).desugar(None)
    assert type(outcome).__name__ == "Incomplete"
    assert outcome.effect.exception_name == "TypeError"
    assert outcome.effect.producer_node_owner == owner
    assert outcome.effect.occurrence_id == str(site)


@pytest.mark.parametrize(
    "receiver",
    (
        StringValue("abc"),
        BytesValue(b"abc"),
        TupleValue((TermValue(1),)),
    ),
)
def test_immutable_slice_delete_cannot_fabricate_mutated_receiver(receiver):
    site = _floor_site()
    outcome = SubscriptDeleteEffectSugar(
        _FloorSugar(receiver),
        _FloorSugar(SliceValue(TermValue(0), TermValue(1), None)),
        site,
    ).desugar(None)
    assert not isinstance(outcome, Complete)


def test_floor_list_delitem_completes_with_element_gone() -> None:
    """Floor ``ListValue.delitem`` already implements the delete post-state law."""
    result = ListValue((TermValue(0), TermValue(1))).delitem(
        TermValue(0), _floor_site()
    )
    assert isinstance(result, Complete)
    assert result.value == ListValue((TermValue(1),))


def test_floor_list_delitem_out_of_range_is_named_indexerror() -> None:
    """Floor list delete IndexError (ground_index_error) — named exceptional face."""
    from sugar_lift_py_tests.floor import RaiseValue

    result = ListValue((TermValue(0),)).delitem(TermValue(5), _floor_site())
    assert isinstance(result, Complete)
    assert isinstance(result.value, RaiseValue)
    assert result.value.effect.exception_name == "IndexError"


def test_floor_delete_is_not_the_formal_carrier_twin() -> None:
    """Discrimination: floor Complete is not helper-alone undischarged demand."""
    floor = ListValue((TermValue(0),)).delitem(TermValue(0), _floor_site())
    assert isinstance(floor, Complete)
    _, pending = _delitem_helper()
    # Formal demand (when present) is a carrier, not a floor Complete.
    assert not (isinstance(pending, Complete) and isinstance(pending.value, ListValue))
    if isinstance(pending, NativeOperationExitCarrierV1):
        assert pending.demand.operator == "delitem"
    else:
        # Still red until mint exists — floor success does not green the vertical.
        assert not isinstance(pending, NativeOperationExitCarrierV1)
