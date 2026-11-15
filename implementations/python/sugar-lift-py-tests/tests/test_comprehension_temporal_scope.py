"""Comprehensions are scoped folds and preserve temporal halts verbatim."""

from dataclasses import dataclass, replace

import pytest

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect.expectation_not_met_effect import (
    ExpectationNotMetEffect,
)
from sugar_lift_py_tests.floor import (
    DictValue,
    ObjectValue,
    SymbolicValue,
)
from sugar_lift_py_tests.ir import make_var
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


def _comprehension(element_outcome):
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
        site="comprehension-temporal-test",
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


def _source_outcome(source: str):
    function = next(_source_file(source).functions())
    return function.sugar().desugar()


def test_completed_element_builds_fold_without_exporting_target_binding():
    result = _comprehension(
        ExitSet.completed(SymbolicValue(make_var("outer_x")))
    ).desugar()

    assert result.completed_value() is not None
    term = result.completed_value().to_term(owner="test")
    assert term.name == "py.listcomp"
    assert term.args[0] == make_var("outer_xs")
    assert term.args[1].body == make_var("outer_x")
    assert term.args[1].body != make_var("element-cid")


def test_halted_element_bypasses_fold_and_retains_exact_outer_state():
    # A halt's state is the record it halted with (``require_halt_record``).
    outer_state = halt_record(None)
    fabricated_state = halt_record(None)
    effect = ExpectationNotMetEffect("comprehension-element", "test-site")
    incoming = ExitSet((Halted(true_guard(), effect, outer_state),))

    result = _comprehension(incoming).desugar()

    assert isinstance(result, ExitSet)
    assert len(result.exits) == 1
    halted = result.exits[0]
    assert isinstance(halted, Halted)
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

    assert outcome.completed_value() is not None
    assert outcome.completed_value().post().args[1] == make_var("outer")


def test_real_source_element_halt_keeps_exact_pre_comprehension_state():
    source = (
        "class Worker:\n"
        "    def run(self):\n"
        "        values = [0]\n"
        "        values[0] = 7\n"
        "        [values[4] for item in [1]]\n"
        "        return values[0]\n"
        "\n"
        "Worker().run()\n"
    )
    call = next(
        node
        for node in _source_file(source).nodes()
        if node.kind == "Call"
        and node.func.kind == "Attribute"
        and node.func.attr == "run"
    )
    # The call is applied where it stands (``CallSiteValue.producer_outcome``
    # runs inside the Call's reduction): its outcome is the body's, every halt
    # published at the Call.  ``values[4]`` on the one-element list raises
    # ``IndexError`` out of ``run``: the sole face, with no completion.
    outcome = call.sugar().desugar(None)

    assert isinstance(outcome, ExitSet), repr(outcome)
    assert len(outcome.exits) == 1
    halted = outcome.exits[0]
    assert isinstance(halted, Halted)
    assert halted.effect.exception_name == "IndexError"
    assert halted.effect.producer_node_owner == "Call"
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
    told = function.desugar()
    assert told.completed_value() is not None
    assert told.completed_value().post().args[1].args[0] == make_var("outer")

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
        replace(
            function,
            statements=tuple(
                mutated_assign if statement is assign else statement
                for statement in function.statements
            ),
        ).desugar()


def test_finite_comprehensions_transport_exact_constructed_objects_in_order():
    """The second comprehension binds the exact objects built by the first."""
    source = (
        "class Item:\n"
        "    def __init__(self, index, name):\n"
        "        self.index = index\n"
        "        self.name = name\n"
        "def build(*names):\n"
        "    items = [Item(index, name) for index, name in enumerate(names)]\n"
        "    return {item.name: item for item in items}\n"
        "build(2, 1)\n"
    )
    call = tuple(
        node
        for node in _source_file(source).nodes()
        if node.kind == "Call" and node.func.kind == "Name" and node.func.id == "build"
    )[-1]
    outcome = call.sugar().desugar(None)

    assert outcome.completed_value() is not None
    returned = outcome.completed_value().project_operation_receiver(
        None, owner="finite-comprehension-transport-test"
    )
    assert isinstance(returned, DictValue)
    assert tuple(key.value for key, _ in returned.entries) == (2, 1)
    objects = tuple(value for _, value in returned.entries)
    assert all(type(value) is ObjectValue for value in objects)
    assert tuple(value.fields[0].value.value for value in objects) == (0, 1)
    assert tuple(value.fields[1].value.value for value in objects) == (2, 1)
    assert returned.entries[0][1] is objects[0]
    assert returned.entries[1][1] is objects[1]


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
