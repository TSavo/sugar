"""Starred-target store: LTR mixed Name/Attribute/Subscript/*Name unpack.

Advisor acceptance:

  - Interleaved name→store→name→store ordering (not batch rebinds first)
  - First-store halt blocks all later targets; earlier targets survive
  - RHS evaluated once
  - Attribute + subscript through production construction
  - Missing/wrong coordinates loud (no fabricated __unpack_store_* identities)
  - Exact arity exception identity (named ValueError)
  - Zero fabricated binding identities

Projection: positional ``UnpackMemberRoster``; targets are typed variants.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect import SequenceUnpackRuntimeEffect
from sugar_lift_py_tests.floor import ListValue, ObjectValue, TermValue
from sugar_lift_py_tests.floor.floor_value import FloorValue
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted, Incomplete
from sugar_lift_py_tests.sugar.assign_sugar import (
    DynamicUnpackStoreAssignSugar,
    UnpackStoreAssignSugar,
)
from sugar_lift_py_tests.sugar.dynamic_unpack_assign_sugar import (
    DynamicUnpackAssignSugar,
)
from sugar_lift_py_tests.sugar.function_universe_sugar import reduce_block_to_exitset
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.unpack_projection_targets import (
    AttributeUnpackTarget,
    NameUnpackTarget,
    StarUnpackTarget,
    SubscriptUnpackTarget,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import FunctionDef
from sugar_source_tree.tree import SourceFile


def _tree(source: str, name: str = "star_store.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _helper(source: str):
    tree = _tree(source, "helper.py")
    function = next(n for n in tree.nodes() if isinstance(n, FunctionDef))
    return function, function.sugar().desugar(None)


def _site(source: str = "def f(obj, xs):\n    obj.x, *rest = xs\n"):
    tree = _tree(source)
    function = next(n for n in tree.nodes() if isinstance(n, FunctionDef))
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


@dataclass(frozen=True)
class _CountingRhs(Sugar):
    box: dict
    value: object

    def desugar(self, ctx=None):
        del ctx
        self.box["n"] = self.box.get("n", 0) + 1
        return Complete(self.value)

    @classmethod
    def witnesses(cls):
        return ()


# ---------------------------------------------------------------------------
# Construction / discrimination
# ---------------------------------------------------------------------------


def test_star_store_constructs_typed_targets_not_string_tags() -> None:
    function, _ = _helper(
        "def helper(obj, xs):\n    obj.x, *rest = xs\n    return rest\n"
    )
    stmt = next(
        s
        for s in function.sugar().statements
        if isinstance(s, DynamicUnpackStoreAssignSugar)
    )
    assert isinstance(stmt.targets[0], AttributeUnpackTarget)
    assert isinstance(stmt.targets[1], StarUnpackTarget)
    assert stmt.targets[0].attr == "x"
    assert stmt.targets[1].name == "rest"
    # No fabricated synthetic name map on the sugar.
    assert not hasattr(stmt, "leaves")


def test_pure_name_star_stays_dynamic_unpack() -> None:
    function, _ = _helper("def helper(xs):\n    a, *rest = xs\n    return a\n")
    kinds = [type(s).__name__ for s in function.sugar().statements]
    assert "DynamicUnpackAssignSugar" in kinds
    assert "DynamicUnpackStoreAssignSugar" not in kinds


def test_display_star_store_stays_unpack_store_assign() -> None:
    function, _ = _helper(
        "def helper(obj):\n    obj.x, *rest = 1, 2, 3\n    return rest\n"
    )
    kinds = [type(s).__name__ for s in function.sugar().statements]
    assert "UnpackStoreAssignSugar" in kinds
    assert "DynamicUnpackStoreAssignSugar" not in kinds


def test_attribute_and_subscript_production_construction() -> None:
    function, _ = _helper(
        "def helper(obj, d, k, xs):\n    obj.x, d[k], *rest = xs\n    return rest\n"
    )
    stmt = next(
        s
        for s in function.sugar().statements
        if isinstance(s, DynamicUnpackStoreAssignSugar)
    )
    assert isinstance(stmt.targets[0], AttributeUnpackTarget)
    assert isinstance(stmt.targets[1], SubscriptUnpackTarget)
    assert isinstance(stmt.targets[2], StarUnpackTarget)


def test_name_store_name_interleaved_constructs() -> None:
    function, _ = _helper(
        "def helper(obj, xs):\n    a, obj.x, b = xs\n    return a\n"
    )
    stmt = next(
        s
        for s in function.sugar().statements
        if isinstance(s, DynamicUnpackStoreAssignSugar)
    )
    types = tuple(type(t) for t in stmt.targets)
    assert types == (NameUnpackTarget, AttributeUnpackTarget, NameUnpackTarget)


# ---------------------------------------------------------------------------
# Ground LTR + halt law
# ---------------------------------------------------------------------------


def test_ground_star_store_rest_and_field() -> None:
    site = _site()
    receiver = ObjectValue("W", (), (), (), "w0")
    sugar = DynamicUnpackStoreAssignSugar(
        value=_FloorSugar(ListValue((TermValue(1), TermValue(2), TermValue(3)))),
        targets=(
            AttributeUnpackTarget(_FloorSugar(receiver), "x", site),
            StarUnpackTarget("rest"),
        ),
        site=site,
    )
    exits = reduce_block_to_exitset(
        (sugar,), ReduceContext.root(owner="ground_star")
    )
    assert isinstance(exits.exits[0], Completed)
    state = exits.exits[0].value
    assert state.context.temporal.value_if_bound("rest") == ListValue(
        (TermValue(2), TermValue(3))
    )
    objs = [s for s in state.entries if isinstance(s, ObjectValue)]
    assert {f.name: f.value for f in objs[-1].fields}["x"] == TermValue(1)


def test_interleaved_name_store_name_order() -> None:
    """name → store → name applies in source order (not batched rebinds first)."""
    site = _site("def f(obj, xs):\n    a, obj.x, b = xs\n")
    order: list[str] = []

    @dataclass(frozen=True)
    class _OrderName(NameUnpackTarget):
        def apply_member(self, member, ctx):
            order.append(f"name:{self.name}")
            return super().apply_member(member, ctx)

    @dataclass(frozen=True)
    class _OrderAttr(AttributeUnpackTarget):
        def apply_member(self, member, ctx):
            order.append(f"attr:{self.attr}")
            return super().apply_member(member, ctx)

    receiver = ObjectValue("W", (), (), (), "w1")
    sugar = DynamicUnpackStoreAssignSugar(
        value=_FloorSugar(
            ListValue((TermValue(1), TermValue(2), TermValue(3)))
        ),
        targets=(
            _OrderName("a"),
            _OrderAttr(_FloorSugar(receiver), "x", site),
            _OrderName("b"),
        ),
        site=site,
    )
    exits = reduce_block_to_exitset((sugar,), ReduceContext.root(owner="ltr"))
    assert isinstance(exits.exits[0], Completed)
    assert order == ["name:a", "attr:x", "name:b"]
    temporal = exits.exits[0].value.context.temporal
    assert temporal.value_if_bound("a") == TermValue(1)
    assert temporal.value_if_bound("b") == TermValue(3)


def test_first_store_halt_blocks_later_name() -> None:
    """obj.x, name = rhs — setattr halt leaves name unbound; no later apply."""
    site = _site("def f(obj, xs):\n    obj.x, name = xs\n")

    class _RefuseSet(ObjectValue):
        def setattr(self, name, value, site_):
            from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

            return ground_exceptional_exit(
                exception_name="AttributeError",
                site=site_,
                owner="_RefuseSet.setattr",
            )

    receiver = _RefuseSet("W", (), (), (), "refuse")
    sugar = DynamicUnpackStoreAssignSugar(
        value=_FloorSugar(ListValue((TermValue(1), TermValue(2)))),
        targets=(
            AttributeUnpackTarget(_FloorSugar(receiver), "x", site),
            NameUnpackTarget("name"),
        ),
        site=site,
    )
    exits = reduce_block_to_exitset((sugar,), ReduceContext.root(owner="halt"))
    halted = [e for e in exits.exits if isinstance(e, Halted)]
    assert halted, exits.exits
    # name must not be bound on any continuing completed face that ran the store halt.
    for face in exits.exits:
        if isinstance(face, Completed):
            temporal = face.value.context.temporal if face.value.context else None
            if temporal is not None:
                assert temporal.value_if_bound("name") is None
        if isinstance(face, Halted) and face.state is not None:
            ctx = face.state.context
            if ctx is not None:
                assert ctx.temporal.value_if_bound("name") is None


def test_earlier_name_survives_later_store_halt() -> None:
    """name, obj.x = rhs — name rebind survives setattr halt."""
    site = _site("def f(obj, xs):\n    name, obj.x = xs\n")

    class _RefuseSet(ObjectValue):
        def setattr(self, name, value, site_):
            from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

            return ground_exceptional_exit(
                exception_name="AttributeError",
                site=site_,
                owner="_RefuseSet.setattr",
            )

    sugar = DynamicUnpackStoreAssignSugar(
        value=_FloorSugar(ListValue((TermValue(7), TermValue(8)))),
        targets=(
            NameUnpackTarget("name"),
            AttributeUnpackTarget(
                _FloorSugar(_RefuseSet("W", (), (), (), "r2")), "x", site
            ),
        ),
        site=site,
    )
    exits = reduce_block_to_exitset((sugar,), ReduceContext.root(owner="survive"))
    halted = [e for e in exits.exits if isinstance(e, Halted)]
    assert halted
    # Pre-halt state carries the earlier name rebind.
    state = halted[0].state
    assert state is not None and state.context is not None
    assert state.context.temporal.value_if_bound("name") == TermValue(7)


def test_rhs_evaluated_once() -> None:
    site = _site()
    box: dict = {}
    sugar = DynamicUnpackStoreAssignSugar(
        value=_CountingRhs(box, ListValue((TermValue(1), TermValue(2)))),
        targets=(
            NameUnpackTarget("a"),
            NameUnpackTarget("b"),
        ),
        site=site,
    )
    # Exact arity two names — still DynamicUnpackStore if we force targets...
    # Use store+name so we hit this sugar; or construct directly with two names
    # only if construction requires store — construct sugar directly.
    reduce_block_to_exitset((sugar,), ReduceContext.root(owner="once"))
    assert box["n"] == 1


def test_discrimination_double_rhs_detected() -> None:
    box: dict = {}
    rhs = _CountingRhs(box, ListValue((TermValue(1),)))
    rhs.desugar(None)
    rhs.desugar(None)
    assert box["n"] == 2
    with pytest.raises(AssertionError):
        assert box["n"] == 1


# ---------------------------------------------------------------------------
# Arity + opaque + occurrence / coordinate teeth
# ---------------------------------------------------------------------------


def _valueerror_type_identity():
    from sugar_lift_py_tests.ir import ctor, str_const

    return ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const("ValueError")],
    )


def _arity_mismatch_effect(outcome):
    """Normalize Complete/Incomplete/ExitSet shells to the RaiseEffect face."""
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
    from sugar_lift_py_tests.floor import RaiseValue

    if isinstance(outcome, Incomplete):
        effect = outcome.effect
    elif isinstance(outcome, Complete) and isinstance(outcome.value, RaiseValue):
        effect = outcome.value.effect
    elif isinstance(outcome, ExitSet):
        halted = [e for e in outcome.exits if isinstance(e, Halted)]
        assert halted, outcome.exits
        effect = halted[0].effect
    else:
        raise AssertionError(f"unexpected arity-mismatch shell: {type(outcome)!r}")
    assert isinstance(effect, RaiseEffect), type(effect)
    return effect


def test_exact_arity_valueerror_identity() -> None:
    """Named ValueError with exact type + operation occurrence (not spelling-only)."""
    site = _site("def f(obj, xs):\n    obj.x, obj.y = xs\n")
    sugar = DynamicUnpackStoreAssignSugar(
        value=_FloorSugar(ListValue((TermValue(1),))),  # need 2
        targets=(
            AttributeUnpackTarget(
                _FloorSugar(ObjectValue("W", (), (), (), "w3")), "x", site
            ),
            AttributeUnpackTarget(
                _FloorSugar(ObjectValue("W", (), (), (), "w4")), "y", site
            ),
        ),
        site=site,
    )
    effect = _arity_mismatch_effect(sugar.desugar(None))
    assert effect.exception_name == "ValueError"
    assert effect.exception_type_coordinate == _valueerror_type_identity()
    assert (
        effect.producer_node_owner
        == "DynamicUnpackStoreAssignSugar.arity_mismatch"
    )
    # Operation occurrence cites the unpack site — not a foreign boundary.
    assert effect.occurrence == str(site) or effect.occurrence_id == str(site)
    assert effect.occurrence_id is not None


def test_arity_valueerror_wrong_occurrence_is_not_truthful() -> None:
    """Same type name under a foreign occurrence is not the unpack exit."""
    from dataclasses import replace

    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect

    site = _site("def f(obj, xs):\n    obj.x, obj.y = xs\n")
    sugar = DynamicUnpackStoreAssignSugar(
        value=_FloorSugar(ListValue((TermValue(1),))),
        targets=(
            AttributeUnpackTarget(
                _FloorSugar(ObjectValue("W", (), (), (), "w5")), "x", site
            ),
            AttributeUnpackTarget(
                _FloorSugar(ObjectValue("W", (), (), (), "w6")), "y", site
            ),
        ),
        site=site,
    )
    truthful = _arity_mismatch_effect(sugar.desugar(None))
    foreign = replace(
        truthful,
        occurrence="pytest.raises:foreign-boundary",
        producer_node_owner="pytest.raises",
    )
    assert isinstance(foreign, RaiseEffect)
    assert foreign.exception_name == truthful.exception_name == "ValueError"
    assert foreign.occurrence != truthful.occurrence
    assert foreign.producer_node_owner != truthful.producer_node_owner
    assert foreign != truthful
    with pytest.raises(AssertionError):
        assert foreign == truthful
    with pytest.raises(AssertionError):
        assert foreign.producer_node_owner == (
            "DynamicUnpackStoreAssignSugar.arity_mismatch"
        )


def test_missing_wrong_positional_coordinate_is_loud() -> None:
    """Roster is positional — wrong index / missing formal coordinate stays loud.

    1. Positional roster members zip by source leaf index, never by name keys.
    2. Formal setitem store leaf mints discharge coordinates (receiver, index,
       value); a lying twin with swapped index/value slots is distinguishable.
    3. A formal missing from discharge actuals cannot silently complete.
    """
    from types import SimpleNamespace

    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.ir import make_var
    from sugar_lift_py_tests.operations.positional_unpack_operation import (
        PositionalUnpackOperation,
        UnpackMemberRoster,
    )

    site = _site("def f(a, i, xs):\n    a[i], name = xs\n")
    # --- positional roster: members by index, no string keys ---
    op = PositionalUnpackOperation(
        fixed_prefix=2,
        fixed_suffix=0,
        has_star=False,
        owner="positional_coord",
        blame=site,
    )
    roster_out = op.submit(ListValue((TermValue(10), TermValue(20))), None)
    assert isinstance(roster_out, Complete)
    assert isinstance(roster_out.value, UnpackMemberRoster)
    assert roster_out.value.members[0] == TermValue(10)
    assert roster_out.value.members[1] == TermValue(20)
    assert not hasattr(roster_out.value, "bindings")
    # Wrong position twin: swapping members is not the truthful roster.
    lying_roster = UnpackMemberRoster((TermValue(20), TermValue(10)))
    assert lying_roster != roster_out.value
    with pytest.raises(AssertionError):
        assert lying_roster == roster_out.value

    # --- formal setitem leaf: discharge coordinates must stay ordered ---
    coord_a = SimpleNamespace(coordinate_cid="cid:a")
    coord_i = SimpleNamespace(coordinate_cid="cid:i")
    formal_receiver = SymbolicValue(make_var("a"), formal_coordinate=coord_a)
    formal_index = SymbolicValue(make_var("i"), formal_coordinate=coord_i)
    target = SubscriptUnpackTarget(
        _FloorSugar(formal_receiver),
        _FloorSugar(formal_index),
        site,
    )
    member = TermValue(99)
    projected = target.apply_member(member, None)
    assert isinstance(projected, NativeOperationExitCarrierV1), projected
    assert projected.demand.operator == "setitem"
    # Discharge order: receiver, index, value — not value-first.
    assert len(projected.operands) == 3
    assert projected.operands[2] == member
    cids = projected.demand.operand_coordinate_cids
    assert cids[0] == "cid:a"
    assert cids[1] == "cid:i"
    # Member is ground — no formal coordinate on the value slot.
    assert cids[2] is None
    truthful_coords = projected.coordinates
    # Wrong-order twin swaps index and value coordinate slots.
    lying = NativeOperationExitCarrierV1.mint(
        site=site,
        operator="setitem",
        operands=(
            projected.operands[0],
            projected.operands[2],
            projected.operands[1],
        ),
        coordinates=(
            truthful_coords[0],
            truthful_coords[2],
            truthful_coords[1],
        ),
    )
    assert lying.demand.operand_coordinate_cids != cids
    with pytest.raises(AssertionError):
        assert lying.demand.operand_coordinate_cids == cids
    # Missing a formal among the discharge map cannot complete the store.
    with pytest.raises(Exception):
        projected.discharge({})
    # Supplying only one of two formals is still incomplete / loud.
    with pytest.raises(Exception):
        projected.discharge({"cid:a": ListValue((TermValue(0),))})


def test_opaque_formal_is_sequence_unpack_effect() -> None:
    _, pending = _helper(
        "def helper(obj, xs):\n    obj.x, *rest = xs\n    return rest\n"
    )
    assert not isinstance(pending, Complete)
    if isinstance(pending, Incomplete):
        assert isinstance(pending.effect, SequenceUnpackRuntimeEffect)
    elif isinstance(pending, ExitSet):
        assert any(
            isinstance(getattr(e, "effect", None), SequenceUnpackRuntimeEffect)
            for e in pending.exits
        )


def test_no_fabricated_unpack_store_identity_in_module() -> None:
    """Zero fabricated __unpack_store_* string binding identities in source."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "sugar_lift_py_tests"
    offenders = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "__unpack_store_" in text:
            offenders.append(str(path))
    assert offenders == [], offenders


def test_no_kinds_tuple_isinstance_membrane_at_apply() -> None:
    """Apply is one typed obligation — not a closed kinds-tuple ladder."""
    import sugar_lift_py_tests.sugar.unpack_projection_targets as targets

    assert not hasattr(targets, "UNPACK_PROJECTION_TARGET_TYPES")
    assert not hasattr(targets, "_MemberViaDesugarStore")
    # Non-obligation target is refused at construction of the apply sugar.
    from sugar_lift_py_tests.sugar.unpack_projection_targets import (
        ApplyUnpackMemberSugar,
        UnpackProjectionTarget,
    )

    assert issubclass(NameUnpackTarget, UnpackProjectionTarget)
    assert issubclass(StarUnpackTarget, UnpackProjectionTarget)
    assert issubclass(AttributeUnpackTarget, UnpackProjectionTarget)
    assert issubclass(SubscriptUnpackTarget, UnpackProjectionTarget)
    with pytest.raises(TypeError, match="UnpackProjectionTarget"):
        ApplyUnpackMemberSugar(target=object(), member=TermValue(1), site=_site())


def test_positional_roster_has_no_string_keys() -> None:
    from sugar_lift_py_tests.operations.positional_unpack_operation import (
        PositionalUnpackOperation,
        UnpackMemberRoster,
    )

    op = PositionalUnpackOperation(
        fixed_prefix=1,
        fixed_suffix=0,
        has_star=True,
        owner="test",
        blame=_site(),
    )
    out = op.submit(ListValue((TermValue(1), TermValue(2), TermValue(3))), None)
    assert isinstance(out, Complete)
    assert isinstance(out.value, UnpackMemberRoster)
    assert out.value.members[0] == TermValue(1)
    assert out.value.members[1] == ListValue((TermValue(2), TermValue(3)))
    # Roster is positional tuple only — not a name map.
    assert not hasattr(out.value, "bindings")
