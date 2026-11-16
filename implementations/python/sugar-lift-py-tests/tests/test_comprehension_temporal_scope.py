"""Comprehensions are scoped folds and preserve temporal halts verbatim.

Deleted: ``test_finite_comprehensions_transport_exact_constructed_objects_in_
order`` read the objects ``Item(index, name)`` built off ``build(2, 1)``, the
body of ``build`` applied at the call (#8705) and the body of ``Item``'s
``__init__`` applied at each class call (#8738).  Both calls are now their
coordinate and edge, joined at prove (#7757 steps 5 and 6), so no object is
built at reduce for the second comprehension to transport.
"""

from dataclasses import dataclass, replace

import pytest

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect.expectation_not_met_effect import (
    ExpectationNotMetEffect,
)
from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.ir import ctor, make_var
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_py_tests.outcome.exit_set import true_guard
from sugar_lift_py_tests.sugar.comprehension_sugar import (
    ComprehensionGeneratorSugar,
    ComprehensionSugar,
    ComprehensionTargetSugar,
)
from sugar_lift_py_tests.sugar.function_universe_sugar import halt_record
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_source_tree.tree import SourceFile
from sugar_source_tree.nodes import TargetPatternConstructionGapV1
from producer_minted_enrollment import producer_not_enrolled


@dataclass(frozen=True)
class _ConstructedOutcomeSugar(ConstructedTermSugar):
    outcome: object
    site: object

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        return self.outcome

    def to_term(self, *, owner: str):
        del owner
        return self.outcome.completed_value().to_term(owner="test fixture")


def _comprehension(element_outcome, site="comprehension-temporal-test"):
    return ComprehensionSugar(
        kind="py.listcomp",
        generators=(
            ComprehensionGeneratorSugar(
                target=ComprehensionTargetSugar(source_name="x"),
                binding_coordinate_cid="element-cid",
                iterable=_ConstructedOutcomeSugar(
                    ExitSet.completed(SymbolicValue(make_var("outer_xs"))),
                    site="synthetic-comprehension-iterable",
                ),
                filters=(),
                target_pattern_enrollment=producer_not_enrolled(),
            ),
        ),
        element=_ConstructedOutcomeSugar(
            element_outcome,
            site="synthetic-comprehension-element",
        ),
        site=site,
    )


def _source_file(source: str):
    return SourceFile(
        (
            source,
            "tests/comprehension_temporal_scope_fixture.py",
            blake3_512_of(source.encode()),
        ),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _own_proof(outcome):
    """A function's outcome as its own proof states it: ``iter`` over a
    formal waits on the caller's actual, and the function's own proof has
    none (``as_its_own_proof_states``)."""
    from sugar_lift_py_tests.tree_enumerate import as_its_own_proof_states

    return as_its_own_proof_states(outcome, None)


def _source_outcome(source: str):
    function = next(_source_file(source).functions())
    return _own_proof(function.sugar().desugar())


def _the_completed_value(outcome):
    """The one completed arm's value: ``iter`` of an undecided iterable
    completes only under its own completes atom, beside its halt."""
    (done,) = [face for face in outcome.exits if isinstance(face, Completed)]
    return done.value


def _iteration_halt(face) -> bool:
    """``face`` is the halt of ``iter`` of the comprehension's undecided
    iterable, or of ``next`` of the iterator ``iter`` completed with
    (``ComprehensionSugar._iterated``, ``iterator_operation.stepped``)."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect

    return (
        isinstance(face, Halted)
        and type(face.effect) is UndeterminedRaiseEffect
        and face.effect.producer_node_owner
        in (
            "SymbolicValue.iter",
            "UnansweredNativeOperation:iter",
            "SymbolicValue.next",
        )
    )


def test_completed_element_completes_with_its_own_coordinate_exporting_nothing():
    # A real source occurrence: the comprehension's own coordinate names it.
    site = next(
        node
        for node in _source_file("def f(xs):\n    return [x for x in xs]\n").nodes()
        if node.kind == "ListComp"
    ).sugar().site
    comprehension = _comprehension(
        ExitSet.completed(SymbolicValue(make_var("outer_x"))), site=site
    )
    result = comprehension.desugar()

    # ``iter(outer_xs)`` is not decided here, nor is ``next`` of the
    # iterator it completes with: the fold follows the faces they complete
    # on, and the faces they raise on are kept.
    assert isinstance(result, ExitSet)
    owners = sorted(halted.effect.producer_node_owner for halted in result.halts())
    assert owners == ["SymbolicValue.iter", "SymbolicValue.next"], result.halts()
    assert all(_iteration_halt(halted) for halted in result.halts())
    # What it accumulates is its own coordinate, its kind over its
    # occurrence and this evaluation of it (no loop item, no unrolled
    # iteration around it: the bare site): neither the element nor the
    # target's binding is stated in it, and reading it owes (#7757).
    from sugar_lift_py_tests.occurrence import occurrence_term

    term = _the_completed_value(result).to_term(owner="test")
    assert term == ctor(
        "py.listcomp",
        [comprehension.occurrence_term(owner="test"), occurrence_term(site, ())],
        symbol_kind="coordinate",
    )
    assert "outer_x" not in repr(term)
    assert "element-cid" not in repr(term)
    assert result.owed_items(), result


def test_halted_element_bypasses_fold_and_retains_exact_outer_state():
    # A halt's state is the record it halted with (``require_halt_record``).
    outer_state = halt_record(None)
    fabricated_state = halt_record(None)
    effect = ExpectationNotMetEffect("comprehension-element", "test-site")
    incoming = ExitSet((Halted(true_guard(), effect, outer_state),))

    result = _comprehension(incoming).desugar()

    assert isinstance(result, ExitSet)
    # Three halts: ``iter`` of the undecided iterable, ``next`` of its
    # iterator, and the element's, on the face both complete on.  Nothing
    # completes.
    assert len(result.exits) == 3
    assert sum(1 for face in result.exits if _iteration_halt(face)) == 2
    (halted,) = [
        face
        for face in result.exits
        if isinstance(face, Halted) and not _iteration_halt(face)
    ]
    assert halted.effect is effect
    assert halted.state is outer_state
    assert halted.state is not fabricated_state
    assert not any(isinstance(face, Completed) for face in result.exits)


def test_real_source_comprehension_keeps_the_enclosing_x_binding():
    outcome = _source_outcome(
        "def helper(outer, items):\n"
        "    x = outer\n"
        "    result = [x for x in items]\n"
        "    return x\n"
    )

    assert any(_iteration_halt(face) for face in outcome.exits), outcome
    assert _the_completed_value(outcome).post().args[1] == make_var("outer")


def test_real_source_element_halt_keeps_exact_pre_comprehension_state():
    """``run``'s own reduction, the one its contract states.  ``values[4]``
    on the one-element list raises ``IndexError`` out of ``run``: the sole
    face, with no completion, and the record it halted with.

    Before #8738 this read the halt off ``Worker().run()``, ``run``'s body
    applied at the call; a method call on a decided receiver is now its
    coordinate and edge (#7757 step 6, "Edge, join at prove"), and the halt
    reaches the caller at prove as a panic locus of ``run``'s contract."""
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    source = (
        "class Worker:\n"
        "    def run(self):\n"
        "        values = [0]\n"
        "        values[0] = 7\n"
        "        [values[4] for item in [1]]\n"
        "        return values[0]\n"
    )
    run = next(
        function
        for function in _source_file(source).functions()
        if function.name == "run"
    )
    outcome = function_universe_outcome(run)

    assert isinstance(outcome, ExitSet), repr(outcome)
    assert len(outcome.exits) == 1
    halted = outcome.exits[0]
    assert isinstance(halted, Halted)
    assert halted.effect.exception_name == "IndexError"
    assert halted.state is not None
    assert not any(isinstance(face, Completed) for face in outcome.exits)


def test_comprehension_target_coordinate_cannot_escape_into_enclosing_x():
    source = (
        "def helper(outer, items):\n"
        "    x = outer\n"
        "    result = [x for x in items]\n"
        "    return (x, result)\n"
    )
    from sugar_lift_py_tests.sugar.assign_sugar import AssignSugar

    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    function = next(_source_file(source).functions()).sugar()
    # TRUTHFUL: the comprehension's ``x`` stays inside it; the tuple's ``x``
    # is the enclosing binding, ``outer``.
    told = _own_proof(function.desugar())
    assert _the_completed_value(told).post().args[1].args[0] == make_var("outer")

    # ``result`` is read in the ``return`` through its assignment's key: the
    # fold is built by the ``result = [...]`` statement, where it runs.
    (assign,) = [
        statement
        for statement in function.statements
        if isinstance(statement, AssignSugar) and statement.name == "result"
    ]
    fold = assign.value
    generator = fold.generators[0]

    # LYING COORDINATE: deliberately collide the comprehension-local binder
    # with the enclosing formal's spelling.  The element reads each member
    # under the coordinate its comprehension binds it (``EvaluationRefSugar``,
    # ``member``), so a fold that binds under a forged coordinate leaves the
    # element's read unbound: refused by name, naming the coordinate, never a
    # completion that reads the enclosing ``x`` or the formal in its place.
    liar = replace(
        fold,
        generators=(replace(generator, binding_coordinate_cid="outer"),),
    )
    mutated_assign = replace(assign, value=liar)
    with pytest.raises(
        ConstructionPanic, match="comprehension member `x` read with its coordinate"
    ):
        _own_proof(
            replace(
                function,
                statements=tuple(
                    mutated_assign if statement is assign else statement
                    for statement in function.statements
                ),
            ).desugar()
        )


def test_finite_comprehension_refuses_swapped_tuple_target_coordinates():
    source = "def build():\n" "    return [(left, right) for left, right in [(1, 2)]]\n"
    source_file = _source_file(source)
    comprehension = next(
        node for node in source_file.nodes() if node.kind == "ListComp"
    ).sugar()
    generator = comprehension.generators[0]

    with pytest.raises(TargetPatternConstructionGapV1) as rejected:
        replace(
            generator,
            target_coordinates=tuple(reversed(generator.target_coordinates)),
        )

    assert rejected.value.reason == "target-coordinate-order-mismatch"
