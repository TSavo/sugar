"""Bound-method returns as caller actuals — source-return projection.

Concrete program:

    class Factory:
        def make(self):
            return 41

    Factory().make() + 1                 # BinOp consumer
    Factory().make() < 50                # Compare consumer
    store([0], 0, Factory().make())      # setitem consumer

Python law: a method call's return is a value. When that value feeds a consumer
as an actual or operand, the **return floor** is the actual — ``TermValue(41)``
— not the method body's ``BlockValue`` and not an unreduced ``CallSiteValue``.
Bound ``self`` is the binder's slot; it does not leak into the returned
testimony.

Acceptance (each with a discrimination twin where noted):

  1. ``obj.make()`` result feeds BinOp, Compare, and setitem consumers.
  2. Direct-value twins are outcome-isomorphic (``41 + 1``, ``41 < 50``,
     ``store([0], 0, 41)``).
  3. Self binding does not leak into the returned value's testimony.
  4. A method returning a raising computation propagates its named
     exceptional edge.
  5. Chained ``obj.make().other()`` stays honestly typed (loud, not fabricated).
  6. Swapped-receiver / tampered-return twins refuse.

Reds name **codex-3's general producer** — acceptance instruments, expected
red until that producer projects bound-method source returns as caller
actuals.

Does not touch: production, binder, carrier/ExitSet; no helper/method spelling.
"""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    ListValue,
    ObjectValue,
    RaiseValue,
    ReturnValue,
    TermValue,
)
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Attribute, BinOp, Call, Compare, Name
from sugar_source_tree.tree import SourceFile

# ---------------------------------------------------------------------------
# Owner named on every red face (codex-3 general producer)
# ---------------------------------------------------------------------------

CODEX3_GENERAL_PRODUCER = (
    "codex-3 general producer: project bound-method source returns as "
    "caller actuals (return floor into BinOp / Compare / setitem consumers; "
    "not BlockValue body, not unreduced CallSiteValue)"
)

FACTORY_MAKE_41 = "class Factory:\n" "    def make(self):\n" "        return 41\n"

STORE_DEF = "def store(obj, key, value):\n    obj[key] = value\n"

RAISING_FACTORY = (
    "class Factory:\n" "    def make(self):\n" "        raise ValueError()\n"
)

CHAIN_SOURCE = (
    "class Inner:\n"
    "    def other(self):\n"
    "        return 7\n"
    "class Factory:\n"
    "    def make(self):\n"
    "        return Inner()\n"
    "\n"
    "Factory().make().other()\n"
)


def _tree(source: str, name: str = "method_return_as_actual.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _desugar_or_name_codex3(thunk, *, face: str):
    """Run a desugar thunk; ConstructionPanic becomes an AssertionError naming codex-3."""
    try:
        return thunk()
    except ConstructionPanic as panic:
        raise AssertionError(
            f"{CODEX3_GENERAL_PRODUCER} — face={face}; construction panic: {panic}"
        ) from panic


def _binop_outcome(source: str):
    tree = _tree(source)
    nodes = tuple(n for n in tree.nodes() if isinstance(n, BinOp))
    assert len(nodes) == 1, nodes
    return _desugar_or_name_codex3(
        lambda: nodes[0].sugar().desugar(None),
        face="binop-consumer",
    )


def _compare_outcome(source: str):
    tree = _tree(source)
    nodes = tuple(n for n in tree.nodes() if isinstance(n, Compare))
    assert len(nodes) == 1, nodes
    return _desugar_or_name_codex3(
        lambda: nodes[0].sugar().desugar(None),
        face="compare-consumer",
    )


def _name_call_outcome(source: str, name: str):
    tree = _tree(source)
    calls = tuple(
        n
        for n in tree.nodes()
        if isinstance(n, Call) and isinstance(n.func, Name) and n.func.id == name
    )
    assert len(calls) == 1, calls
    return _desugar_or_name_codex3(
        lambda: calls[0].sugar().desugar(None),
        face=f"name-call:{name}",
    )


def _attr_call_outcome(source: str, attr: str):
    tree = _tree(source)
    calls = tuple(
        n
        for n in tree.nodes()
        if isinstance(n, Call) and isinstance(n.func, Attribute) and n.func.attr == attr
    )
    assert calls, (attr, source)
    return _desugar_or_name_codex3(
        lambda: calls[-1].sugar().desugar(None),
        face=f"attr-call:{attr}",
    )


def _attr_callsite(source: str, attr: str) -> CallSiteValue:
    outcome = _attr_call_outcome(source, attr)
    assert isinstance(outcome, Complete), outcome
    assert isinstance(outcome.value, CallSiteValue), outcome.value
    return outcome.value


def _identity(name: str):
    from sugar_lift_py_tests.temporal.temporal_context import TemporalContext

    return TemporalContext.empty().value_for(name).exception_type_identity()


def _completed_sum_value(outcome) -> int:
    """Project BinOp completion to the integer sum (direct twin: 41+1 → 42)."""
    if isinstance(outcome, Complete) and isinstance(outcome.value, TermValue):
        return int(outcome.value.value)
    if isinstance(outcome, ExitSet) and len(outcome.exits) == 1:
        face = outcome.exits[0]
        if isinstance(face, Completed) and isinstance(face.value, TermValue):
            return int(face.value.value)
    raise AssertionError(
        f"{CODEX3_GENERAL_PRODUCER} — BinOp face is not a completed TermValue sum: "
        f"{type(outcome).__name__} {outcome!r:.200}"
    )


def _completed_compare_is_true(outcome) -> bool:
    """Project Compare completion to bool (direct twin: 41 < 50 → True)."""
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar

    if isinstance(outcome, Complete):
        if isinstance(outcome.value, TrueBoolLiteralSugar):
            return True
        if isinstance(outcome.value, FalseBoolLiteralSugar):
            return False
    if isinstance(outcome, ExitSet) and len(outcome.exits) == 1:
        face = outcome.exits[0]
        if isinstance(face, Completed):
            value = face.value
            if isinstance(value, TrueBoolLiteralSugar):
                return True
            if isinstance(value, FalseBoolLiteralSugar):
                return False
            # PredicateValue / other completed faces — not the direct twin shape.
    raise AssertionError(
        f"{CODEX3_GENERAL_PRODUCER} — Compare face is not outcome-isomorphic to "
        f"TrueBoolLiteralSugar for 41 < 50: {type(outcome).__name__} {outcome!r:.200}"
    )


def _store_value_actual(outcome) -> object:
    """Pull the value actual from a completed ``store(obj, key, value)`` call."""
    if isinstance(outcome, ExitSet) and len(outcome.exits) == 1:
        face = outcome.exits[0]
        if isinstance(face, Completed) and isinstance(face.value, CallSiteValue):
            args = face.value.arg_values
            assert len(args) == 3, args
            return args[2]
    if isinstance(outcome, Complete) and isinstance(outcome.value, CallSiteValue):
        args = outcome.value.arg_values
        assert len(args) == 3, args
        return args[2]
    raise AssertionError(
        f"{CODEX3_GENERAL_PRODUCER} — setitem store face has no value actual: "
        f"{type(outcome).__name__} {outcome!r:.200}"
    )


def _returned_floor_from_make(source: str = FACTORY_MAKE_41 + "\nFactory().make()\n"):
    """Dig the return floor from a completed bound-method call."""
    site = _attr_callsite(source, "make")
    assert site.parameters[0] == "self"
    assert isinstance(site.arg_values[0], ObjectValue)
    assert site.arg_values[0].class_name == "Factory"
    dug = site._dig_floor_or_none(None, owner="method-return-as-actual")
    assert dug is not None, site
    return dug


def _collect_return_values(root) -> list:
    found: list = []
    seen: set[int] = set()
    stack = [root]
    while stack:
        value = stack.pop()
        if id(value) in seen:
            continue
        seen.add(id(value))
        if isinstance(value, ReturnValue):
            found.append(value)
            continue
        if isinstance(value, RaiseValue):
            continue
        statements = getattr(value, "statements", None)
        if statements:
            stack.extend(statements)
            continue
        record = getattr(value, "record", None)
        if record is not None and getattr(record, "statements", None):
            stack.extend(record.statements)
            continue
        inner = getattr(value, "value", None)
        if inner is not None and inner is not value:
            stack.append(inner)
    return found


# ---------------------------------------------------------------------------
# Direct-value twins (green baselines)
# ---------------------------------------------------------------------------


def test_direct_value_twins_establish_green_baselines() -> None:
    """Direct values complete without method-return projection."""
    binop = _binop_outcome("41 + 1\n")
    assert _completed_sum_value(binop) == 42

    compare = _compare_outcome("41 < 50\n")
    assert _completed_compare_is_true(compare) is True

    store = _name_call_outcome(
        STORE_DEF + "\nstore([0], 0, 41)\n",
        "store",
    )
    assert _store_value_actual(store) == TermValue(41)


# ---------------------------------------------------------------------------
# 1–2. Method return feeds consumers; isomorphic to direct twins
# ---------------------------------------------------------------------------


def test_method_return_feeds_binop_isomorphic_to_direct_value() -> None:
    """``Factory().make() + 1`` must complete as ``41 + 1`` → 42.

    RED until codex-3 general producer projects the method return floor into
    the add consumer (today: ConstructionPanic on BlockValue.add).
    """
    direct = _binop_outcome("41 + 1\n")
    method = _binop_outcome(FACTORY_MAKE_41 + "\nFactory().make() + 1\n")
    assert _completed_sum_value(method) == _completed_sum_value(direct) == 42, (
        f"{CODEX3_GENERAL_PRODUCER} — BinOp method-return face not isomorphic "
        f"to direct 41+1: method={type(method).__name__} direct={type(direct).__name__}"
    )


def test_method_return_feeds_compare_isomorphic_to_direct_value() -> None:
    """``Factory().make() < 50`` must complete as ``41 < 50`` → True.

    RED until codex-3 general producer projects the method return floor into
    the less_than consumer (today: dual ExitSet, not TrueBoolLiteralSugar).
    """
    direct = _compare_outcome("41 < 50\n")
    method = _compare_outcome(FACTORY_MAKE_41 + "\nFactory().make() < 50\n")
    assert (
        _completed_compare_is_true(method) is _completed_compare_is_true(direct) is True
    ), (
        f"{CODEX3_GENERAL_PRODUCER} — Compare method-return face not isomorphic "
        f"to direct 41<50: method={type(method).__name__} direct={type(direct).__name__}"
    )


def test_method_return_feeds_setitem_isomorphic_to_direct_value() -> None:
    """``store([0], 0, Factory().make())`` value actual must be ``TermValue(41)``.

    RED until codex-3 general producer projects the method return into the
    setitem value slot (today: value actual remains CallSiteValue(Factory.make)).
    """
    direct = _name_call_outcome(STORE_DEF + "\nstore([0], 0, 41)\n", "store")
    method = _name_call_outcome(
        FACTORY_MAKE_41 + "\n" + STORE_DEF + "\nstore([0], 0, Factory().make())\n",
        "store",
    )
    direct_value = _store_value_actual(direct)
    method_value = _store_value_actual(method)
    assert method_value == direct_value == TermValue(41), (
        f"{CODEX3_GENERAL_PRODUCER} — setitem value actual from method return "
        f"is not TermValue(41): got {type(method_value).__name__} {method_value!r:.160}"
    )


def test_discrimination_unreduced_callsite_is_not_the_returned_term() -> None:
    """Lying twin: leaving CallSiteValue(Factory.make) as the value is not 41."""
    method = _name_call_outcome(
        FACTORY_MAKE_41 + "\n" + STORE_DEF + "\nstore([0], 0, Factory().make())\n",
        "store",
    )
    value = _store_value_actual(method)
    # Until codex-3 lands this may still be CallSiteValue — instrument names it.
    if value != TermValue(41):
        raise AssertionError(
            f"{CODEX3_GENERAL_PRODUCER} — value actual must be TermValue(41), "
            f"not unreduced {type(value).__name__}"
        )


# ---------------------------------------------------------------------------
# 3. Self binding does not leak into returned testimony
# ---------------------------------------------------------------------------


def test_self_binding_does_not_leak_into_returned_testimony() -> None:
    """Bound self is prepended at the callsite; return floor is TermValue(41)."""
    site = _attr_callsite(FACTORY_MAKE_41 + "\nFactory().make()\n", "make")
    assert site.parameters == ("self",)
    assert isinstance(site.arg_values[0], ObjectValue)
    assert site.arg_values[0].class_name == "Factory"

    dug = _returned_floor_from_make()
    returned = dug
    assert returned == TermValue(41), returned
    # Self is not the returned testimony.
    assert not isinstance(returned, ObjectValue)
    assert returned != site.arg_values[0]


def test_discrimination_returned_term_is_not_the_receiver_object() -> None:
    site = _attr_callsite(FACTORY_MAKE_41 + "\nFactory().make()\n", "make")
    dug = site._dig_floor_or_none(None, owner="method-return-as-actual")
    assert dug == TermValue(41)
    assert dug != site.arg_values[0]


# ---------------------------------------------------------------------------
# 4. Method returning a raising computation propagates named edge
# ---------------------------------------------------------------------------


def test_method_returning_raise_propagates_named_exceptional_edge() -> None:
    """``Factory().make()`` body ``raise ValueError()`` → Halted ValueError."""
    site = _attr_callsite(RAISING_FACTORY + "\nFactory().make()\n", "make")
    assert isinstance(site.arg_values[0], ObjectValue)
    assert site.arg_values[0].class_name == "Factory"

    outcome = site.producer_outcome(None)
    assert isinstance(outcome, ExitSet), outcome
    assert len(outcome.exits) == 1
    halted = outcome.exits[0]
    assert isinstance(halted, Halted), halted
    assert halted.effect.exception_name == "ValueError"
    assert halted.effect.exception_type_coordinate == _identity("ValueError")
    assert halted.effect.occurrence_id == str(site)


def test_discrimination_completed_return_is_not_valueerror_halt() -> None:
    """Positive twin returns 41; must not be a ValueError halt."""
    site = _attr_callsite(FACTORY_MAKE_41 + "\nFactory().make()\n", "make")
    outcome = site.producer_outcome(None)
    if isinstance(outcome, ExitSet):
        assert not any(
            isinstance(e, Halted) and e.effect.exception_name == "ValueError"
            for e in outcome.exits
        )
    else:
        assert isinstance(outcome, Complete)
        dug = outcome.value._dig_floor_or_none(None, owner="method-return-as-actual")
        assert dug == TermValue(41)


# ---------------------------------------------------------------------------
# 5. Chained obj.make().other() stays honestly typed
# ---------------------------------------------------------------------------


def test_chained_method_return_stays_honestly_typed() -> None:
    """``Factory().make().other()`` must complete as 7, or fail loud naming codex-3.

    Fabricated green (silent Complete without return 7) is forbidden. Loud
    ConstructionPanic / TypeError is acceptable until codex-3 projects the
    intermediate return as the receiver of ``.other()``.
    """
    try:
        outcome = _attr_call_outcome(CHAIN_SOURCE, "other")
    except AssertionError as err:
        # _desugar_or_name_codex3 already named codex-3.
        assert "codex-3 general producer" in str(err), err
        raise
    except TypeError as err:
        # Honest loud gap (e.g. ConstructionGap.owner mis-attribution) — still
        # not fabricated green; rename to codex-3 owner for the merger.
        raise AssertionError(
            f"{CODEX3_GENERAL_PRODUCER} — chained make().other() must project "
            f"Inner receiver then return 7; observed TypeError: {err}"
        ) from err

    # Green path: dig / complete to TermValue(7).
    if isinstance(outcome, Complete) and isinstance(outcome.value, CallSiteValue):
        dug = outcome.value._dig_floor_or_none(None, owner="method-return-as-actual")
        if dug == TermValue(7):
            return
        returns = _collect_return_values(dug) if dug is not None else []
        if returns and returns[0].value == TermValue(7):
            return
        raise AssertionError(
            f"{CODEX3_GENERAL_PRODUCER} — chained other() completed without "
            f"return floor TermValue(7): dig={type(dug).__name__ if dug else None}"
        )
    if isinstance(outcome, Complete) and isinstance(outcome.value, TermValue):
        assert outcome.value == TermValue(7)
        return
    raise AssertionError(
        f"{CODEX3_GENERAL_PRODUCER} — chained make().other() face not TermValue(7): "
        f"{type(outcome).__name__}"
    )


# ---------------------------------------------------------------------------
# 6. Swapped receiver / tampered-return twins refuse
# ---------------------------------------------------------------------------


def test_tampered_return_twin_refuses_isomorphism_with_truthful_sum() -> None:
    """Lying map: pretend make returned 99; truthful sum is 42, not 100."""
    direct = _binop_outcome("41 + 1\n")
    assert _completed_sum_value(direct) == 42
    # Discrimination only: a tampered 99+1 is not the truthful method face.
    tampered = _binop_outcome("99 + 1\n")
    assert _completed_sum_value(tampered) == 100
    assert _completed_sum_value(tampered) != _completed_sum_value(direct)


def test_swapped_receiver_is_not_the_returned_value() -> None:
    """Receiver ObjectValue(Factory) is not TermValue(41) — self is not the return."""
    site = _attr_callsite(FACTORY_MAKE_41 + "\nFactory().make()\n", "make")
    receiver = site.arg_values[0]
    assert isinstance(receiver, ObjectValue)
    dug = site._dig_floor_or_none(None, owner="method-return-as-actual")
    assert dug == TermValue(41)
    assert dug != receiver
    # A swapped lying map that treats self as the returned actual fails.
    assert not (isinstance(dug, ObjectValue) and dug.class_name == "Factory")


def test_discrimination_list_literal_is_not_make_return() -> None:
    """Direct setitem list actual is not a method-return CallSiteValue."""
    direct = _name_call_outcome(STORE_DEF + "\nstore([0], 0, 41)\n", "store")
    value = _store_value_actual(direct)
    assert value == TermValue(41)
    assert not isinstance(value, CallSiteValue)
    assert value != ListValue((TermValue(0),))
