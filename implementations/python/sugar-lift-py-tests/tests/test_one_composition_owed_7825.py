"""#7825, one composition: every site that unioned debts by hand now composes.

An arm owes what any path into it incurred. ``ExitSet.sequence`` (with
``consume=`` for a halt the composition owns) is the one way to compose a
step with what follows, carrying guard, faces and ``owed``; sibling arms that
stand for each other join through ``ExitSet.union`` / ``normalize``, and what a
set of arms owes together is read with ``ExitSet.owed_items``. ``owed_union``
is private to the exit algebra. One test per rewritten site: the debt
survives.
"""

from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests import unanswered_calls
from sugar_lift_py_tests.context.reduce_context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.effect.raise_effect import (
    RaiseEffect,
    UndeterminedRaiseEffect,
)
from sugar_lift_py_tests.floor import SymbolicValue, TermValue
from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
from sugar_lift_py_tests.ir import PrimitiveSort, atomic, make_var, not_
from sugar_lift_py_tests.outcome.exit_set import (
    Completed,
    ExitSet,
    Halted,
    complement_guard,
    partition,
    true_guard,
)
from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock
from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar
from sugar_lift_py_tests.sugar.match_sugar import MatchCaseSpec, MatchSugar
from sugar_lift_py_tests.sugar.return_sugar import ReturnSugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.tree import SourceFile


class _Fixed(Sugar):
    """A sugar whose reduction is handed in."""

    def __init__(self, build):
        self.build = build

    def desugar(self, ctx=None):
        return self.build(ctx)

    @classmethod
    def witnesses(cls):
        return ()


def _raise(occurrence: str) -> RaiseEffect:
    return RaiseEffect.for_builtin("ValueError", occurrence=occurrence)


def _site():
    source = "def operation(left, right):\n    return left + right\n"
    tree = SourceFile(
        (source, "one_composition_7825.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(tree.functions()).fragment


def _coordinate(name: str, ordinal: int) -> FormalParameterCoordinateV1:
    source_cid = "blake3-512:" + "a" * 128
    owner = SourceFragmentCoordinateV1(source_cid, 1, 0, 2, 23)
    return FormalParameterCoordinateV1.mint(
        owner_source_identity_cid=source_cid,
        owner_definition_locus=owner,
        declaration_locus=SourceFragmentCoordinateV1(
            source_cid, 1, 14 + ordinal * 6, 1, 18 + ordinal * 6
        ),
        ordinal=ordinal,
        parameter_kind="positional-or-keyword",
        declared_name=name,
        sort=PrimitiveSort("Value"),
    )


def _carrier():
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )

    left = _coordinate("left", 0)
    right = _coordinate("right", 1)
    carrier = NativeOperationExitCarrierV1.mint(
        site=_site(),
        operator="add",
        operands=(
            SymbolicValue(make_var("left"), left),
            SymbolicValue(make_var("right"), right),
        ),
        coordinates=(left, right),
    )
    return carrier, left, right


# --- if: the completed face joins its sibling suites (a join, not a sequence)


def test_an_if_join_owes_every_completed_suites_debt() -> None:
    from sugar_lift_py_tests.sugar.if_sugar import IfSugar

    formula = atomic("test:if_c:7825", [])
    then_face, else_face = partition(("test:if-join", 7825))
    block = _ReducedBlock(entries=(), can_fall_through=True, fall_through=())
    joined = IfSugar._join_branches(
        None,
        ExitSet((Completed(true_guard(), block, owed=("debt:then",)),)),
        ExitSet((Completed(true_guard(), block, owed=("debt:else",)),)),
        formula=formula,
        not_formula=not_(formula),
        then_face=then_face,
        else_face=else_face,
        observed_formula=true_guard(),
        authentication=None,
    )
    assert [type(arm) for arm in joined.exits] == [Completed], joined.exits
    assert joined.exits[0].owed == ("debt:then", "debt:else")


# --- except group: each child halt is consumed, then the group raises


def test_a_grouped_raise_owes_what_every_child_halt_owed() -> None:
    from sugar_lift_py_tests.effect import GroupedRaiseEffect
    from sugar_lift_py_tests.sugar.grouped_raise_sugar import GroupedRaiseSugar

    first = _raise("test:child:a:7825")
    second = _raise("test:child:b:7825")
    sugar = GroupedRaiseSugar(
        group_identity="test:group:7825",
        message=_Fixed(lambda _ctx: ExitSet.completed("g")),
        children=(
            _Fixed(
                lambda _ctx: ExitSet(
                    (Halted(true_guard(), first, None, owed=("debt:a",)),)
                )
            ),
            _Fixed(
                lambda _ctx: ExitSet(
                    (Halted(true_guard(), second, None, owed=("debt:b",)),)
                )
            ),
        ),
        site=_site(),
    )
    outcome = sugar.desugar(None)
    assert [type(arm) for arm in outcome.exits] == [Halted], outcome.exits
    (halt,) = outcome.exits
    assert isinstance(halt.effect, GroupedRaiseEffect)
    assert halt.effect.children == (first, second)
    assert halt.owed == ("debt:a", "debt:b")


# --- native operation: the resolution continues beneath the projector halt


def test_a_decided_raise_resolution_owes_what_the_projector_halt_owed(
    monkeypatch,
) -> None:
    from sugar_lift_py_tests.caller_parameter_contract import (
        _NATIVE_OPERATION_PROJECTORS,
    )

    def owing_raise(left, right, site):
        del left, right, site
        return ExitSet(
            (
                Halted(
                    true_guard(),
                    RaiseEffect.for_builtin("TypeError", occurrence="test:op:7825"),
                    None,
                    owed=("debt:op",),
                ),
            )
        )

    monkeypatch.setitem(_NATIVE_OPERATION_PROJECTORS, "add", owing_raise)
    carrier, left, right = _carrier()
    exits = carrier.discharge(
        {left.coordinate_cid: TermValue(1), right.coordinate_cid: TermValue(2)}
    )
    assert exits.halts() and exits.halts() == exits.exits, exits.exits
    assert all(halt.owed == ("debt:op",) for halt in exits.halts()), exits.exits


# --- guarded value: both arms' predicates ran before the joined predicate


@dataclass(frozen=True)
class _OwingPredicateArm:
    formula: object
    debt: str

    def truth(self, site):
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue

        predicate = PredicateValue(self.formula, site)
        return ExitSet((Completed(true_guard(), predicate, owed=(self.debt,)),))


def test_a_guarded_predicate_owes_what_both_arms_owed() -> None:
    from sugar_lift_py_tests.floor.guarded_value import GuardedValue
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue

    value = GuardedValue(
        atomic("test:gv_guard:7825", []),
        _OwingPredicateArm(atomic("test:gv_true:7825", []), "debt:true"),
        _OwingPredicateArm(atomic("test:gv_false:7825", []), "debt:false"),
    )
    joined = value.truth("gv-site:7825")
    assert [type(arm) for arm in joined.exits] == [Completed], joined.exits
    (arm,) = joined.exits
    assert isinstance(arm.value, PredicateValue)
    assert arm.owed == ("debt:true", "debt:false")


# --- receiver partition: a nested face is sequenced beneath its enclosing face


def test_a_flattened_receiver_face_owes_its_enclosing_face_debt() -> None:
    from sugar_lift_py_tests.floor.receiver_state_partition_value import (
        ReceiverStatePartitionValue,
    )

    outer = atomic("test:outer:7825", [])
    inner = atomic("test:inner:7825", [])
    nested = ReceiverStatePartitionValue(
        ExitSet(
            (
                Completed(inner, TermValue(1), owed=("debt:inner",)),
                Halted(
                    complement_guard(inner),
                    _raise("test:inner-halt:7825"),
                    None,
                    owed=("debt:inner-halt",),
                ),
            )
        )
    )
    value = ReceiverStatePartitionValue(
        ExitSet(
            (
                Completed(outer, nested, owed=("debt:outer",)),
                Halted(
                    complement_guard(outer),
                    _raise("test:ctor:7825"),
                    None,
                    owed=("debt:ctor",),
                ),
            )
        )
    )
    halts, completed = value.constructor_faces()
    assert [arm.owed for arm in completed] == [("debt:outer", "debt:inner")]
    assert [arm.owed for arm in halts] == [
        ("debt:outer", "debt:inner-halt"),
        ("debt:ctor",),
    ]


# --- generator machine: exits continue beneath a routing face


def _routing_faces():
    route = atomic("test:route:7825", [])
    completed_face = Completed(route, TermValue(0), owed=("debt:face",))
    halted_face = Halted(
        complement_guard(route),
        _raise("test:route-halt:7825"),
        None,
        owed=("debt:halt",),
    )
    inner = ExitSet((Completed(true_guard(), TermValue(1), owed=("debt:inner",)),))
    return inner, completed_face, halted_face


def test_a_generator_routing_face_debt_rides_every_exit_beneath_it() -> None:
    from sugar_lift_py_tests.generator_construction import _guard_exits

    inner, completed_face, halted_face = _routing_faces()
    assert [arm.owed for arm in _guard_exits(inner, completed_face).exits] == [
        ("debt:face", "debt:inner")
    ]
    assert [arm.owed for arm in _guard_exits(inner, halted_face).exits] == [
        ("debt:halt", "debt:inner")
    ]


def test_a_generator_manager_mapped_face_debt_rides_every_exit_beneath_it() -> None:
    from sugar_lift_py_tests.generator_manager_exit import _guard_with

    inner, completed_face, halted_face = _routing_faces()
    assert [arm.owed for arm in _guard_with(inner, completed_face).exits] == [
        ("debt:face", "debt:inner")
    ]
    assert [arm.owed for arm in _guard_with(inner, halted_face).exits] == [
        ("debt:halt", "debt:inner")
    ]


# --- owed_calls: a deferred carrier's reduced arms are read by the one reader


def test_a_deferred_carrier_owes_its_prefix_arms_debts() -> None:
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )

    first = unanswered_calls.unanswered_call("python:first", None)
    second = unanswered_calls.unanswered_call("python:second", None)
    prefix_guard = atomic("test:prefix:7825", [])
    carrier, _left, _right = _carrier()
    prefix = ExitSet(
        (
            Completed(prefix_guard, TermValue(1), owed=(first,)),
            Halted(
                complement_guard(prefix_guard),
                UndeterminedRaiseEffect(blame="test", occurrence="test"),
                None,
                owed=(second,),
            ),
        )
    )
    composed = prefix.sequence(lambda _value: carrier)
    assert isinstance(composed, NativeOperationExitCarrierV1)
    # The resolved (halted) prefix arm first, then the deferred prefix arm.
    assert unanswered_calls.owed_calls(composed) == (second, first)


# --- match: patterns, equalities and guards are steps of one path


@dataclass(frozen=True)
class _MatchSite:
    filename: str = "one_composition_match_7825.py"
    line: int = 1
    col: int = 0

    def __str__(self) -> str:
        return f"{self.filename}:{self.line}:{self.col}"


_MATCH_SITE = _MatchSite()
_EQ = atomic("test:match_eq:7825", [])
_EQ_OTHER = atomic("test:match_eq_other:7825", [])
_EQ_FACE = atomic("test:match_eq_face:7825", [])


@dataclass(frozen=True)
class _Truth:
    """A completed value whose truth is the symbolic ``formula``."""

    formula: object

    def truth(self, site):
        del site
        return ExitSet.completed(self)


@dataclass(frozen=True)
class _Subject:
    """A subject whose ``__eq__`` answers the arms ``build()`` returns."""

    build: object

    def equals(self, other, site, ctx):
        del other, site, ctx
        return self.build()


@dataclass(frozen=True)
class _ValueSugar(Sugar):
    """A sugar that completes with ``value`` owing ``owed``."""

    value: object
    owed: tuple = ()

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        return ExitSet((Completed(true_guard(), self.value, owed=self.owed),))


def _int(n: int) -> IntLiteralSugar:
    return IntLiteralSugar(n, site=_MatchSite(col=n))


def _ret(n: int) -> ReturnSugar:
    return ReturnSugar(_int(n), site=_MatchSite(line=n))


def _match(subject: _Subject, *cases: MatchCaseSpec) -> ExitSet:
    sugar = MatchSugar(subject=_ValueSugar(subject), cases=cases, site=_MATCH_SITE)
    outcome = sugar.desugar(ReduceContext.root(owner="test_one_composition_7825"))
    assert isinstance(outcome, ExitSet), type(outcome).__name__
    return outcome


def _eq_owing(*owed) -> _Subject:
    return _Subject(
        lambda: ExitSet((Completed(true_guard(), _Truth(_EQ), owed=tuple(owed)),))
    )


def test_a_match_guard_debt_reaches_the_body_and_the_fall_through() -> None:
    """``case 1 if g:``: the body runs after ``g``, and so does the fall-through."""
    outcome = _match(
        _eq_owing("debt:eq"),
        MatchCaseSpec(
            alternatives=(_int(1),),
            body=(_ret(10),),
            guard=_ValueSugar(_Truth(atomic("test:guard:7825", [])), ("debt:guard",)),
        ),
    )
    assert len(outcome.exits) >= 2, outcome.exits
    owing = ("debt:eq", "debt:guard")
    assert all(arm.owed == owing for arm in outcome.exits), outcome.exits


def test_an_equality_halt_owes_the_alternative_it_ran_after() -> None:
    """The ``__eq__`` halt is sequenced after the alternative that completed."""
    subject = _Subject(
        lambda: ExitSet(
            (
                Completed(_EQ_FACE, _Truth(_EQ), owed=("debt:eq",)),
                Halted(
                    complement_guard(_EQ_FACE),
                    UndeterminedRaiseEffect(blame="test", occurrence="test"),
                    None,
                    owed=("debt:eq-halt",),
                ),
            )
        )
    )
    outcome = _match(
        subject,
        MatchCaseSpec(
            alternatives=(_ValueSugar(TermValue(1), ("debt:alt",)),),
            body=(_ret(10),),
        ),
    )
    assert [halt.owed for halt in outcome.halts()] == [("debt:alt", "debt:eq-halt")]
    completed = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    assert completed, outcome.exits
    assert all(arm.owed == ("debt:alt", "debt:eq") for arm in completed), completed


def test_sibling_equality_faces_join_their_debts() -> None:
    """Two completed ``__eq__`` faces: every path past the comparison owes both."""
    subject = _Subject(
        lambda: ExitSet(
            (
                Completed(_EQ_FACE, _Truth(_EQ), owed=("debt:eq-a",)),
                Completed(
                    complement_guard(_EQ_FACE), _Truth(_EQ_OTHER), owed=("debt:eq-b",)
                ),
            )
        )
    )
    outcome = _match(
        subject,
        MatchCaseSpec(alternatives=(_int(1),), body=(_ret(10),)),
    )
    assert outcome.exits
    owing = ("debt:eq-a", "debt:eq-b")
    assert all(arm.owed == owing for arm in outcome.exits), outcome.exits
