"""*args/**kwargs binding through formal setitem.

Concrete signatures:

    def helper(obj, key, *values):
        obj[key] = values

    def helper(obj, key, **values):
        obj[key] = values

Binding (SourceCallFrame.bind_actuals only — no second binder):

  - remaining positionals pack into authenticated ``TupleValue`` on the
    variadic-positional formal; setitem stores that tuple as the value
  - extra keywords pack into authenticated ``DictValue`` on the
    variadic-keyword formal; setitem stores that mapping as the value
  - empty * / ** are honest empty TupleValue / DictValue (never fabricated
    None or omitted)
  - invalid index: named IndexError; exact pre_effect_state identity
  - dropped/reordered variadic twins fail (lying mint ≠ truthful store)

Helper alone remains Undischarged setitem on exact formals
``(obj, key, values)``. Does not touch carrier/ExitSet, store
producer/projector/Floor.
"""

from __future__ import annotations

import inspect

import pytest

from sugar_lift_py_tests.caller_parameter_contract import (
    NativeOperationExitCarrierV1,
    _NATIVE_OPERATION_PROJECTORS,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import (
    DictValue,
    ListValue,
    StringValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.floor.universe_value import UniverseValue
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.tree import SourceFile

HELPER_STAR = "def helper(obj, key, *values):\n    obj[key] = values\n"
HELPER_KW = "def helper(obj, key, **values):\n    obj[key] = values\n"


def _tree(source: str, name: str = "setitem_variadic.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _helper(program: str):
    tree = _tree(program, "helper_alone.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function, function.sugar().desugar(None)


def _call(program: str, actuals: str):
    tree = _tree(program + f"\nhelper({actuals})\n")
    call = tuple(node for node in tree.nodes() if isinstance(node, Call))[-1]
    return call.sugar().desugar(None)


def _identity(name: str):
    from sugar_lift_py_tests.ir import ctor, str_const

    return ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const(name)],
    )


def _stored_list(completed_face) -> ListValue:
    assert isinstance(completed_face, Completed)
    record = getattr(completed_face.value, "record", None)
    assert record is not None
    lists = [s for s in record.statements if isinstance(s, ListValue)]
    assert len(lists) == 1, lists
    return lists[0]


# ---------------------------------------------------------------------------
# Helper alone → Undischarged setitem on variadic formals
# ---------------------------------------------------------------------------


def test_helper_star_alone_is_undischarged_setitem_with_variadic_positional() -> None:
    function, pending = _helper(HELPER_STAR)
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "setitem"
    assert tuple(value.term.name for value in pending.operands) == (
        "obj",
        "key",
        "values",
    )
    kinds = tuple(c.parameter_kind for c in function.sugar().formal_coordinates)
    assert kinds == (
        "positional-or-keyword",
        "positional-or-keyword",
        "variadic-positional",
    )
    assert pending.demand.operand_coordinate_cids == tuple(
        c.coordinate_cid for c in function.sugar().formal_coordinates
    )
    assert pending.pre_effect_state is not None
    parameters = tuple(
        inspect.signature(_NATIVE_OPERATION_PROJECTORS["setitem"]).parameters
    )
    assert parameters == ("receiver", "index", "value", "site")


def test_helper_kw_alone_is_undischarged_setitem_with_variadic_keyword() -> None:
    function, pending = _helper(HELPER_KW)
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "setitem"
    kinds = tuple(c.parameter_kind for c in function.sugar().formal_coordinates)
    assert kinds == (
        "positional-or-keyword",
        "positional-or-keyword",
        "variadic-keyword",
    )
    assert pending.demand.operand_coordinate_cids == tuple(
        c.coordinate_cid for c in function.sugar().formal_coordinates
    )


def test_helper_alone_is_not_completed_discrimination() -> None:
    _, pending = _helper(HELPER_STAR)
    with pytest.raises(AssertionError):
        assert isinstance(pending, Completed)


# ---------------------------------------------------------------------------
# Remaining positionals → authenticated TupleValue stored by setitem
# ---------------------------------------------------------------------------


def test_remaining_positionals_become_authenticated_tuple_store_value() -> None:
    """``helper([0], 0, 1, 2, 3)`` — *values packs (1,2,3) as stored value."""
    face = _call(HELPER_STAR, "[0], 0, 1, 2, 3").exits[0]
    assert isinstance(face, Completed)
    assert face.value.arg_values == (
        ListValue((TermValue(0),)),
        TermValue(0),
        TupleValue((TermValue(1), TermValue(2), TermValue(3))),
    )
    assert face.value.parameters == ("obj", "key", "values")


def test_star_values_discharge_stores_tuple_at_index() -> None:
    _, pending = _helper(HELPER_STAR)
    obj_cid, key_cid, values_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge(
        {
            obj_cid: ListValue((TermValue(0),)),
            key_cid: TermValue(0),
            values_cid: TupleValue((TermValue(1), TermValue(2))),
        }
    )
    assert isinstance(exits, ExitSet)
    assert isinstance(exits.exits[0], Completed)
    assert _stored_list(exits.exits[0]) == ListValue(
        (TupleValue((TermValue(1), TermValue(2))),)
    )


# ---------------------------------------------------------------------------
# Extra keywords → authenticated DictValue stored by setitem
# ---------------------------------------------------------------------------


def test_extra_keywords_become_authenticated_mapping_store_value() -> None:
    """``helper([0], 0, a=1, b=2)`` — **values packs mapping as stored value."""
    face = _call(HELPER_KW, "[0], 0, a=1, b=2").exits[0]
    assert isinstance(face, Completed)
    assert face.value.arg_values == (
        ListValue((TermValue(0),)),
        TermValue(0),
        DictValue(
            (
                (StringValue("a"), TermValue(1)),
                (StringValue("b"), TermValue(2)),
            )
        ),
    )
    assert face.value.parameters == ("obj", "key", "values")


def test_kw_values_discharge_stores_dict_at_index() -> None:
    _, pending = _helper(HELPER_KW)
    obj_cid, key_cid, values_cid = pending.demand.operand_coordinate_cids
    mapping = DictValue(((StringValue("a"), TermValue(1)),))
    exits = pending.discharge(
        {
            obj_cid: ListValue((TermValue(0),)),
            key_cid: TermValue(0),
            values_cid: mapping,
        }
    )
    assert isinstance(exits.exits[0], Completed)
    assert _stored_list(exits.exits[0]) == ListValue((mapping,))


# ---------------------------------------------------------------------------
# Empty variadics are honest empty values
# ---------------------------------------------------------------------------


def test_empty_star_is_honest_empty_tuple() -> None:
    """``helper([0], 0)`` with *values — empty pack, not None / omitted."""
    face = _call(HELPER_STAR, "[0], 0").exits[0]
    assert isinstance(face, Completed)
    assert face.value.arg_values[2] == TupleValue(())
    assert face.value.arg_values[2] is not None


def test_empty_kw_is_honest_empty_dict() -> None:
    """``helper([0], 0)`` with **values — empty mapping, not None / omitted."""
    face = _call(HELPER_KW, "[0], 0").exits[0]
    assert isinstance(face, Completed)
    assert face.value.arg_values[2] == DictValue(())
    assert face.value.arg_values[2] is not None


def test_empty_star_discharge_stores_empty_tuple() -> None:
    _, pending = _helper(HELPER_STAR)
    obj_cid, key_cid, values_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge(
        {
            obj_cid: ListValue((TermValue(0),)),
            key_cid: TermValue(0),
            values_cid: TupleValue(()),
        }
    )
    assert isinstance(exits.exits[0], Completed)
    assert _stored_list(exits.exits[0]) == ListValue((TupleValue(()),))


# ---------------------------------------------------------------------------
# Invalid index retains exact pre-effect state
# ---------------------------------------------------------------------------


def test_invalid_index_named_indexerror_with_exact_pre_effect_state() -> None:
    _, pending = _helper(HELPER_STAR)
    assert pending.pre_effect_state is not None
    obj_cid, key_cid, values_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge(
        {
            obj_cid: ListValue((TermValue(0),)),
            key_cid: TermValue(1),
            values_cid: TupleValue((TermValue(9),)),
        }
    )
    halted = exits.exits[0]
    assert isinstance(halted, Halted)
    assert not isinstance(halted, Completed)
    assert halted.effect.exception_type_coordinate == _identity("IndexError")
    assert (
        isinstance(halted.effect.occurrence_id, str)
        and ":" in halted.effect.occurrence_id
    ), (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {halted.effect.occurrence_id!r}"
    )
    assert halted.state is not None
    assert pending.pre_effect_state.state is halted.state
    assert not isinstance(getattr(halted, "value", None), UniverseValue)


def test_source_caller_invalid_index_preserves_state() -> None:
    outcome = _call(HELPER_STAR, "[0], 1, 9")
    assert isinstance(outcome, ExitSet)
    halted = outcome.exits[0]
    assert isinstance(halted, Halted)
    assert halted.effect.exception_type_coordinate == _identity("IndexError")
    assert halted.state is not None


def test_invalid_index_discrimination_not_completed() -> None:
    _, pending = _helper(HELPER_STAR)
    obj_cid, key_cid, values_cid = pending.demand.operand_coordinate_cids
    exits = pending.discharge(
        {
            obj_cid: ListValue((TermValue(0),)),
            key_cid: TermValue(1),
            values_cid: TupleValue((TermValue(9),)),
        }
    )
    with pytest.raises(AssertionError):
        assert isinstance(exits.exits[0], Completed)
    with pytest.raises(AssertionError):
        assert exits.exits[0].state is None


# ---------------------------------------------------------------------------
# Dropped / reordered variadic twins fail
# ---------------------------------------------------------------------------


def test_dropped_variadic_value_coordinate_is_undischarged() -> None:
    """Omitting the *values formal from discharge stays loud — no green store."""
    _, pending = _helper(HELPER_STAR)
    obj_cid, key_cid, _values_cid = pending.demand.operand_coordinate_cids
    from sugar_source_tree.panic import SugarNotWritten

    with pytest.raises(SugarNotWritten, match="caller actual absent"):
        pending.discharge(
            {
                obj_cid: ListValue((TermValue(0),)),
                key_cid: TermValue(0),
                # values_cid deliberately omitted
            }
        )


def test_reordered_variadic_twin_fails() -> None:
    """Lying mint with index/value slots swapped is not the truthful *store.

    Truthful discharge stores the TupleValue pack at TermValue index.
    Swapped mint feeds the pack as index — Floor refuses ground tuple index
    (ConstructionPanic) or yields a non-matching face. Never equals truthful.
    """
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    function, truthful = _helper(HELPER_STAR)
    site = function.body[0].fragment
    obj_c, key_c, values_c = truthful.coordinates
    lying = NativeOperationExitCarrierV1.mint(
        site=site,
        operator="setitem",
        operands=(
            truthful.operands[0],
            truthful.operands[2],
            truthful.operands[1],
        ),
        coordinates=(obj_c, values_c, key_c),
    )
    pack = TupleValue((TermValue(9), TermValue(8)))
    actuals = {
        obj_c.coordinate_cid: ListValue((TermValue(0), TermValue(1), TermValue(2))),
        key_c.coordinate_cid: TermValue(1),
        values_c.coordinate_cid: pack,
    }
    t_face = truthful.discharge(actuals).exits[0]
    assert isinstance(t_face, Completed)
    t_list = _stored_list(t_face)
    assert t_list == ListValue((TermValue(0), pack, TermValue(2)))
    try:
        l_face = lying.discharge(actuals).exits[0]
    except ConstructionPanic:
        return  # lying index is the packed tuple — not a lawful setitem index
    if isinstance(l_face, Completed) and isinstance(l_face.value, UniverseValue):
        assert _stored_list(l_face) != t_list
    elif isinstance(l_face, Completed) and isinstance(l_face.value, ListValue):
        assert l_face.value != t_list
    else:
        assert isinstance(l_face, Halted)


def test_star_vs_kw_kinds_are_not_interchangeable_discrimination() -> None:
    """Bite: *values pack is TupleValue; **values pack is DictValue."""
    star_face = _call(HELPER_STAR, "[0], 0, 1").exits[0]
    kw_face = _call(HELPER_KW, "[0], 0, a=1").exits[0]
    assert isinstance(star_face.value.arg_values[2], TupleValue)
    assert isinstance(kw_face.value.arg_values[2], DictValue)
    with pytest.raises(AssertionError):
        assert star_face.value.arg_values[2] == kw_face.value.arg_values[2]
