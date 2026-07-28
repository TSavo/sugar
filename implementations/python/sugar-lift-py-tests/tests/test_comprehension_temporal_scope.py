"""Comprehensions are scoped folds and preserve temporal halts verbatim."""

from dataclasses import dataclass, replace

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect.expectation_not_met_effect import (
    ExpectationNotMetEffect,
)
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    ListValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted
from sugar_lift_py_tests.outcome.exit_set import true_guard
from sugar_lift_py_tests.sugar.comprehension_sugar import (
    ComprehensionGeneratorSugar,
    ComprehensionSugar,
    ComprehensionTargetSugar,
)
from sugar_source_tree.tree import SourceFile


@dataclass(frozen=True)
class _OutcomeSugar:
    outcome: object

    def desugar(self, ctx=None):
        del ctx
        return self.outcome


def _comprehension(element_outcome):
    return ComprehensionSugar(
        kind="py.listcomp",
        generators=(
            ComprehensionGeneratorSugar(
                target=ComprehensionTargetSugar(source_name="x"),
                binding_coordinate_cid="element-cid",
                iterable=_OutcomeSugar(Complete(SymbolicValue(make_var("outer_xs")))),
                filters=(),
            ),
        ),
        element=_OutcomeSugar(element_outcome),
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
    result = _comprehension(Complete(SymbolicValue(make_var("outer_x")))).desugar()

    assert isinstance(result, Complete)
    term = result.value.to_term(owner="test")
    assert term.name == "py.listcomp"
    assert term.args[0] == make_var("outer_xs")
    assert term.args[1].body == make_var("outer_x")
    assert term.args[1].body != make_var("element-cid")


def test_halted_element_bypasses_fold_and_retains_exact_outer_state():
    outer_state = object()
    fabricated_state = object()
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

    assert isinstance(outcome, Complete)
    assert outcome.value.post().args[1] == make_var("outer")


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
    constructed = call.sugar().desugar(None)
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, CallSiteValue)
    outcome = constructed.value.producer_outcome(None)

    assert isinstance(outcome, ExitSet), repr(outcome)
    assert len(outcome.exits) == 1
    halted = outcome.exits[0]
    assert isinstance(halted, Halted)
    assert halted.state is not None
    assert halted.state.entries == (ListValue((TermValue(7),)),)
    assert halted.state.entries != (ListValue((TermValue(0),)),)
    assert not any(isinstance(face, Completed) for face in outcome.exits)


def test_comprehension_target_coordinate_cannot_escape_into_enclosing_x():
    source = (
        "def helper(outer, items):\n"
        "    x = outer\n"
        "    result = [x for x in items]\n"
        "    return (x, result)\n"
    )
    function = next(_source_file(source).functions()).sugar()
    returned = function.statements[-1]
    pair = returned.value
    fold = pair.elements[1]
    generator = fold.generators[0]

    # LYING COORDINATE: deliberately collide the comprehension-local binder
    # with the enclosing formal's spelling. Lexical lambda scope must contain
    # that mutation; it may alter the fold binder but never the tuple's outer x.
    liar = replace(
        fold,
        generators=(replace(generator, binding_coordinate_cid="outer"),),
    )
    mutated_return = replace(
        returned,
        value=replace(pair, elements=(pair.elements[0], liar)),
    )
    outcome = replace(
        function,
        statements=(*function.statements[:-1], mutated_return),
    ).desugar()

    assert isinstance(outcome, Complete)
    post = outcome.value.post().args[1]
    outer, mutated_fold = post.args
    assert outer == make_var("outer")
    assert mutated_fold.args[1].param_name == "outer"
    assert mutated_fold.args[1].body == make_var("outer")
    assert post.args[0] == outer
