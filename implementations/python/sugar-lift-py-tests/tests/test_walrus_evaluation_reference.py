"""``(x := e)``: a later read is a reference to the walrus's one evaluation.

Temporal choice 1 (#7661), as #7886 did for ``x += e``: substitution rewrites
a read of ``x`` after ``(x := e)`` to ``EvaluationRef(<the walrus's evaluation
key>)``; ``NamedExpressionValue`` binds the assigned value under that key.

Two hazards are pinned here:

1. A walrus in an ``if`` condition binds its key into the context both suites
   start from.  The join measures what the arms bound against the context
   before the condition, so the key is carried out of the ``if``.
2. A walrus nested in a larger expression (an assignment's right-hand side, a
   call's actual, any operand) carries its bind out to the enclosing statement
   on the value, through the one operand door (``consume_operands``), and a
   comprehension's element writes its key per member.  A read
   resolves through the key only: where the key was never bound it is
   refused, never read as the name or as the walrus's value evaluated again.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import GuardedFaces, TermValue
from sugar_lift_py_tests.floor.block_value import BlockValue
from sugar_lift_py_tests.floor.branch_result_coordinate import BranchResultSlot
from sugar_lift_py_tests.floor.named_expression_value import (
    NamedExpressionValue,
    bind_walrus_binds,
    carry_walrus_binds,
    consume_operands,
    peel_walrus_binds,
)
from sugar_lift_py_tests.floor.return_value import ReturnValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.floor.none_value import NoneValue
from sugar_lift_py_tests.floor.tuple_value import TupleValue
from sugar_lift_py_tests.generator_construction import (
    AssignStepV1,
    GeneratorAssignBindingV1,
    GeneratorConstructionV1,
    GeneratorTerminationV1,
    GeneratorWalrusBindingV1,
    OpaqueStepV1,
    ReturnStepV1,
    TermStepV1,
    YieldAssignStepV1,
    YieldEffect,
    YieldStepV1,
)
from sugar_lift_py_tests.outcome import Completed, ExitSet, outcome_to_exitset
from sugar_lift_py_tests.sugar.assign_sugar import AssignSugar
from sugar_lift_py_tests.sugar.binop_sugar import BinOpSugar
from sugar_lift_py_tests.sugar.bool_op_sugar import BoolOpSugar
from sugar_lift_py_tests.sugar.comprehension_sugar import ComprehensionSugar
from sugar_lift_py_tests.sugar.evaluation_ref_sugar import EvaluationRefSugar
from sugar_lift_py_tests.sugar.if_exp_sugar import IfExpSugar
from sugar_lift_py_tests.sugar.if_sugar import IfSugar
from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar
from sugar_lift_py_tests.sugar.name_sugar import NameSugar
from sugar_lift_py_tests.sugar.named_expr_sugar import NamedExprSugar
from sugar_lift_py_tests.temporal.temporal_context import EVALUATION_PREFIX
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, EvaluationRef, FunctionDef, Return
from sugar_source_tree.tree import SourceFile

KEY = EVALUATION_PREFIX + "blake3-512:test-walrus-evaluation"


@dataclass(frozen=True)
class _Site:
    filename: str = "walrus_evaluation.py"
    line: int = 1
    col: int = 0

    def __str__(self) -> str:
        return f"{self.filename}:{self.line}:{self.col}"


SITE = _Site()


def _function(source: str) -> FunctionDef:
    tree = SourceFile(
        (source, "walrus_evaluation.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(node for node in tree.nodes() if isinstance(node, FunctionDef))


def _walruses(node) -> list:
    return [child for child in node.walk() if child.kind == "NamedExpr"]


def _root(owner: str = "walrus-evaluation") -> ReduceContext:
    return ReduceContext.root(owner=owner)


def _value(outcome):
    """The one unconditional completed value of an outcome (#7825 reads
    ``ExitSet`` only), else None."""
    return outcome_to_exitset(outcome).completed_value()


# ---------------------------------------------------------------------------
# Substitution: the read is a reference to the walrus's evaluation
# ---------------------------------------------------------------------------


def test_read_after_walrus_references_its_evaluation() -> None:
    rewritten = _function("def f(z):\n    (x := z)\n    return x\n").substitute({})
    (walrus,) = _walruses(rewritten)
    ret = rewritten.body[-1]
    assert isinstance(ret, Return)
    assert isinstance(ret.value, EvaluationRef)
    assert isinstance(walrus.evaluation, str)
    assert walrus.evaluation.startswith(EVALUATION_PREFIX)
    assert ret.value.evaluation == walrus.evaluation
    assert ret.value.name == "x"


def test_walrus_sugar_carries_its_evaluation_key() -> None:
    rewritten = _function("def f(z):\n    (x := z)\n    return x\n").substitute({})
    (walrus,) = _walruses(rewritten)
    sugar = walrus.sugar()
    assert isinstance(sugar, NamedExprSugar)
    assert sugar.evaluation == walrus.evaluation


def test_each_unrolled_iteration_is_its_own_walrus_evaluation() -> None:
    rewritten = _function(
        "def f():\n    for v in [1, 2]:\n        (t := v)\n    return t\n"
    ).substitute({})
    walruses = _walruses(rewritten)
    assert len(walruses) == 2
    assert walruses[0].evaluation != walruses[1].evaluation
    ret = rewritten.body[-1]
    assert isinstance(ret, Return)
    assert isinstance(ret.value, EvaluationRef)
    assert ret.value.evaluation == walruses[1].evaluation


# ---------------------------------------------------------------------------
# Reduce: the walrus binds its value under its key
# ---------------------------------------------------------------------------


def test_walrus_value_binds_its_evaluation_and_its_name() -> None:
    value = NamedExpressionValue("x", TermValue(5), evaluation=KEY)
    ctx = value.extend_scope(_root())
    assert ctx.temporal.value_if_bound(KEY) == TermValue(5)
    assert ctx.temporal.value_if_bound("x") == TermValue(5)
    read = EvaluationRefSugar(evaluation=KEY, name="x", site=None)
    assert _value(read.desugar(ctx)) == TermValue(5)


def test_a_comparison_carries_the_walrus_evaluation() -> None:
    value = NamedExpressionValue("x", TermValue(5), evaluation=KEY)
    compared = _value(value.greater_than(TermValue(0), SITE, None))
    assert isinstance(compared, NamedExpressionValue)
    assert compared.evaluation == KEY
    ctx = compared.extend_scope(_root())
    assert ctx.temporal.value_if_bound(KEY) == TermValue(5)


# ---------------------------------------------------------------------------
# Hazard 1: a walrus in an if condition is carried out of the if
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("assigned", [5, 0])
def test_a_condition_walrus_is_carried_out_of_the_if(assigned: int) -> None:
    walrus = NamedExprSugar(
        name="n",
        value=IntLiteralSugar(assigned, site=SITE),
        site=SITE,
        evaluation=KEY,
    )
    outcome = IfSugar(
        test=walrus,
        branch_slot=BranchResultSlot(slot_id="b0"),
        then_body=(),
        else_body=(),
        site=SITE,
    ).desugar(_root("walrus-if"))
    faces = _value(outcome)
    assert isinstance(faces, GuardedFaces)
    # Measured against the context the suites started from, the condition's
    # key looked bound before the if and was dropped.
    assert [key for key, _carried in faces.evaluations] == [KEY]
    after = faces.extend_scope(_root("walrus-after-if"))
    read = EvaluationRefSugar(evaluation=KEY, name="n", site=None)
    assert _value(read.desugar(after)) is faces.evaluations[0][1]


# ---------------------------------------------------------------------------
# Hazard 2: a nested walrus's bind reaches the statement; a read resolves
# through the key only
# ---------------------------------------------------------------------------


def _returned_value(outcome):
    """The one completed return value of a reduced call."""
    assert isinstance(outcome, ExitSet), type(outcome)
    assert len(outcome.exits) == 1
    face = outcome.exits[0]
    assert isinstance(face, Completed), type(face)
    value = face.value
    force = getattr(value, "force_floor", None)
    if callable(force):
        forced = force(None, owner="walrus_evaluation_test")
        if isinstance(forced, BlockValue):
            returns = [s for s in forced.statements if isinstance(s, ReturnValue)]
            assert returns, forced.statements
            return returns[-1].value
        return forced
    record = getattr(value, "record", None)
    if record is not None:
        returns = [s for s in record.statements if isinstance(s, ReturnValue)]
        if returns:
            return returns[-1].value
    return value


def _call_outcome(source: str):
    """``source``'s last call, reduced through the production door."""
    tree = SourceFile(
        (source, "walrus_call.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    call = tuple(node for node in tree.nodes() if isinstance(node, Call))[-1]
    return call.sugar().desugar(None)


def test_read_after_a_walrus_nested_in_an_assignment_is_its_value() -> None:
    # `x += 1` wrote the name; the walrus nested in `y = ...` is the later
    # write, and the read resolves through its key.
    returned = _returned_value(
        _call_outcome(
            "def f(x):\n"
            "    x += 1\n"
            "    y = (x := 5)\n"
            "    return x\n"
            "\n"
            "f(3)\n"
        )
    )
    assert returned == TermValue(5)
    assert returned != TermValue(4)


def test_read_after_a_walrus_in_a_comprehension_is_the_last_member() -> None:
    returned = _returned_value(
        _call_outcome(
            "def f():\n"
            "    [(last := v) for v in [1, 2, 3]]\n"
            "    return last\n"
            "\n"
            "f()\n"
        )
    )
    assert returned == TermValue(3)


def test_a_comprehension_with_a_walrus_constructs() -> None:
    rewritten = _function(
        "def f():\n"
        "    value = 7\n"
        "    [(captured := value) for x in [1]]\n"
        "    return captured\n"
    ).substitute({})
    (walrus,) = _walruses(rewritten)
    comprehension = next(node for node in rewritten.walk() if node.kind == "ListComp")
    assert isinstance(comprehension.sugar(), ComprehensionSugar)
    ret = rewritten.body[-1]
    assert isinstance(ret, Return)
    assert isinstance(ret.value, EvaluationRef)
    assert ret.value.name == "captured"
    assert ret.value.evaluation == walrus.evaluation
    assert ret.value.walrus is True
    assert getattr(ret.value, "unevaluated", None) is None
    sugar = ret.value.sugar()
    assert isinstance(sugar, EvaluationRefSugar)
    assert sugar.walrus is True


def test_each_member_writes_the_walrus_key() -> None:
    rewritten = _function(
        "def f():\n    [(last := v) for v in [1, 2]]\n    return last\n"
    ).substitute({})
    (walrus,) = _walruses(rewritten)
    comprehension = next(node for node in rewritten.walk() if node.kind == "ListComp")
    carried = _value(comprehension.sugar().desugar(_root("walrus-comprehension")))
    binds, presented = peel_walrus_binds(carried)
    # One write carried out: the last member's, under the walrus's key.
    assert [(bind.name, bind.evaluation) for bind in binds] == [
        ("last", walrus.evaluation)
    ]
    assert binds[0].assigned_value == TermValue(2)
    # The comprehension's own value is the members, not the walrus wrapper.
    assert not any(
        isinstance(element, NamedExpressionValue)
        for element in presented.finite_elements
    )
    after = bind_walrus_binds(binds, _root("walrus-after-comprehension"))
    ret = rewritten.body[-1]
    assert isinstance(ret, Return)
    assert _value(ret.value.sugar().desugar(after)) == TermValue(2)


def test_a_call_carries_its_actual_walrus_to_the_result() -> None:
    walrus = NamedExpressionValue("x", TermValue(5), evaluation=KEY)
    seen = []

    def call(actual):
        seen.append(actual)
        return ExitSet.completed(TermValue(9))

    result = _value(consume_operands(call, walrus))
    # The call consumes the value the walrus presents, once.
    assert seen == [TermValue(5)]
    binds, presented = peel_walrus_binds(result)
    assert presented == TermValue(9)
    assert [(bind.name, bind.evaluation) for bind in binds] == [("x", KEY)]
    ctx = bind_walrus_binds(binds, _root("walrus-call"))
    assert ctx.temporal.value_if_bound(KEY) == TermValue(5)


def test_the_operand_door_carries_every_operand_bind_in_order() -> None:
    first = NamedExpressionValue("a", TermValue(1), evaluation=KEY + ":a")
    second = NamedExpressionValue("b", TermValue(2), evaluation=KEY + ":b")
    seen = []

    def consume(*operands):
        seen.append(operands)
        return ExitSet.completed(TermValue(3))

    result = _value(consume_operands(consume, first, TermValue(7), second))
    # The consumer runs once, on the values the operands present.
    assert seen == [(TermValue(1), TermValue(7), TermValue(2))]
    binds, presented = peel_walrus_binds(result)
    assert presented == TermValue(3)
    assert [bind.name for bind in binds] == ["a", "b"]


def test_the_operand_door_without_a_walrus_is_the_step_itself() -> None:
    outcome = ExitSet.completed(TermValue(3))
    assert consume_operands(lambda *_operands: outcome, TermValue(1)) is outcome


def _walrus_sugar(name: str, assigned: int, key: str = KEY) -> NamedExprSugar:
    return NamedExprSugar(
        name=name,
        value=IntLiteralSugar(assigned, site=SITE),
        site=SITE,
        evaluation=key,
    )


def test_an_arithmetic_operand_carries_its_walrus() -> None:
    outcome = BinOpSugar(
        op_kind="Add",
        left=_walrus_sugar("x", 5),
        right=IntLiteralSugar(1, site=SITE),
        site=SITE,
    ).desugar(_root("walrus-binop"))
    binds, presented = peel_walrus_binds(_value(outcome))
    assert presented == TermValue(6)
    assert [(bind.name, bind.assigned_value) for bind in binds] == [
        ("x", TermValue(5))
    ]


@pytest.mark.parametrize(
    ("op_kind", "first", "expected", "bound"),
    [
        # The second operand runs: its walrus binds on that face.
        ("Or", 0, TermValue(5), ["x"]),
        ("And", 1, TermValue(5), ["x"]),
        # The first operand stops: the second never ran and binds nothing.
        ("Or", 1, TermValue(1), []),
        ("And", 0, TermValue(0), []),
    ],
)
def test_a_short_circuit_binds_only_where_its_operand_ran(
    op_kind: str, first: int, expected, bound: list
) -> None:
    outcome = BoolOpSugar(
        op_kind=op_kind,
        values=(IntLiteralSugar(first, site=SITE), _walrus_sugar("x", 5)),
        site=SITE,
    ).desugar(_root("walrus-boolop"))
    binds, presented = peel_walrus_binds(_value(outcome))
    assert presented == expected
    assert [bind.name for bind in binds] == bound


@pytest.mark.parametrize(
    ("assigned", "expected"),
    [
        # The first operand stops: its walrus rides the stopping face.
        (3, TermValue(3)),
        # The first operand continues: its walrus rides the later face too.
        (0, TermValue(7)),
    ],
)
def test_a_short_circuit_first_operand_binds_on_every_face(
    assigned: int, expected
) -> None:
    outcome = BoolOpSugar(
        op_kind="Or",
        values=(_walrus_sugar("x", assigned), IntLiteralSugar(7, site=SITE)),
        site=SITE,
    ).desugar(_root("walrus-boolop-first"))
    binds, presented = peel_walrus_binds(_value(outcome))
    assert presented == expected
    assert [(bind.name, bind.assigned_value) for bind in binds] == [
        ("x", TermValue(assigned))
    ]


@pytest.mark.parametrize(
    "statement",
    [
        # arithmetic operands
        "y = (x := 5) + 1",
        "y = 1 + (x := 5)",
        "y = -(x := 5)",
        # comparison operands
        "y = 0 < (x := 5) < 9",
        "y = (x := 5) < 9 < 10",
        # display elements
        "y = [(x := 5)]",
        "y = ((x := 5), 1)",
        "y = {(x := 5)}",
        "y = {'k': (x := 5)}",
        "y = {(x := 5): 'v'}",
        # a subscript's index
        "y = [0, 1, 2, 3, 4, 5][(x := 5)]",
        # an f-string part
        "y = f'{(x := 5)}'",
        # a conditional expression's test
        "y = 'a' if (x := 5) else 'b'",
        # short-circuit operands
        "y = 0 or (x := 5)",
        "y = 1 and (x := 5)",
        # a walrus inside a walrus
        "y = (z := (x := 5))",
        # a container mutation's argument
        "xs = []\n    xs.append((x := 5))",
    ],
)
def test_a_walrus_in_an_operand_binds_the_statement(statement: str) -> None:
    returned = _returned_value(
        _call_outcome(
            "def f():\n"
            "    " + statement + "\n"
            "    return x\n"
            "\n"
            "f()\n"
        )
    )
    assert returned == TermValue(5)


def test_a_returned_operand_walrus_returns_the_value_it_presents() -> None:
    # The return holds the value, never the walrus wrapper: the callee's
    # write of `x` does not reach its caller.
    returned = _returned_value(
        _call_outcome("def f():\n    return (x := 5) + 1\n\nf()\n")
    )
    assert returned == TermValue(6)
    assert not isinstance(returned, NamedExpressionValue)


def test_an_assignment_binds_its_rhs_walrus() -> None:
    walrus = NamedExprSugar(
        name="x", value=IntLiteralSugar(5, site=SITE), site=SITE, evaluation=KEY
    )
    ctx = _root("walrus-assign")
    ctx = ctx.with_temporal(ctx.temporal.bind_value("x", TermValue(4)))
    statement = AssignSugar(name="y", value=walrus, site=SITE)
    (face,) = outcome_to_exitset(statement.desugar(ctx)).exits
    assert isinstance(face, Completed)
    after = face.value.context
    read = EvaluationRefSugar(evaluation=KEY, name="x", site=None, walrus=True)
    assert _value(read.desugar(after)) == TermValue(5)


def test_a_walrus_read_never_falls_back_to_the_name() -> None:
    # The key was never bound: the name's older write is not the walrus's
    # value, and the walrus's value is not evaluated again.  Refused by name.
    read = EvaluationRefSugar(evaluation=KEY, name="x", site=None, walrus=True)
    ctx = _root()
    ctx = ctx.with_temporal(ctx.temporal.bind_value("x", TermValue(1)))
    with pytest.raises(ConstructionPanic):
        read.desugar(ctx)


def test_an_evaluated_walrus_is_read_from_its_key() -> None:
    read = EvaluationRefSugar(evaluation=KEY, name="x", site=None, walrus=True)
    ctx = _root()
    ctx = ctx.with_temporal(ctx.temporal.bind_value("x", TermValue(1)))
    ctx = ctx.with_temporal(ctx.temporal.bind_value(KEY, TermValue(9)))
    assert _value(read.desugar(ctx)) == TermValue(9)


def test_a_write_of_the_name_after_the_walrus_is_read() -> None:
    read = EvaluationRefSugar(evaluation=KEY, name="x", site=None, walrus=True)
    ctx = _root()
    ctx = ctx.with_temporal(ctx.temporal.bind_value(KEY, TermValue(9)))
    ctx = ctx.with_temporal(ctx.temporal.bind_value("x", TermValue(3)))
    assert _value(read.desugar(ctx)) == TermValue(3)


# ---------------------------------------------------------------------------
# ``yield (x := v)``: the generator frame records the bind
# ---------------------------------------------------------------------------


def test_a_yielded_walrus_binds_the_generator_frame() -> None:
    # `yield (x := 5)` then `return x`: the yield hands out 5 and the
    # suspended frame records the walrus, so the step after the resume reads
    # `x` through the walrus's key.
    machine = GeneratorConstructionV1.allocate(
        allocation_coordinate="call:walrus_generator:1",
        frame_coordinate="frame:walrus_generator",
        binding_state=(),
        steps=(
            YieldStepV1(_walrus_sugar("x", 5)),
            ReturnStepV1(
                EvaluationRefSugar(evaluation=KEY, name="x", site=None, walrus=True)
            ),
        ),
    )
    yielded = machine.resume()
    assert isinstance(yielded, YieldEffect)
    assert yielded.value == TermValue(5)
    assert not isinstance(yielded.value, NamedExpressionValue)
    recorded = [
        item
        for item in yielded.machine.binding_state
        if isinstance(item, GeneratorWalrusBindingV1)
    ]
    assert [(item.name, item.evaluation) for item in recorded] == [("x", KEY)]
    terminated = yielded.machine.send(None)
    assert isinstance(terminated, GeneratorTerminationV1)
    assert terminated.return_value == TermValue(5)


def test_a_yield_without_a_walrus_records_nothing() -> None:
    machine = GeneratorConstructionV1.allocate(
        allocation_coordinate="call:plain_generator:1",
        frame_coordinate="frame:plain_generator",
        binding_state=(),
        steps=(YieldStepV1(IntLiteralSugar(5, site=SITE)),),
    )
    yielded = machine.resume()
    assert isinstance(yielded, YieldEffect)
    assert yielded.value == TermValue(5)
    assert yielded.machine.binding_state == ()


# ---------------------------------------------------------------------------
# ``y = yield v``: the sent value binds ``y``; a walrus in an assignment or a
# bare walrus statement binds the generator frame
# ---------------------------------------------------------------------------

Y_KEY = EVALUATION_PREFIX + "blake3-512:test-yield-assign-evaluation/y"


def _generator(name: str, *steps) -> GeneratorConstructionV1:
    return GeneratorConstructionV1.allocate(
        allocation_coordinate=f"call:{name}:1",
        frame_coordinate=f"frame:{name}",
        binding_state=(),
        steps=steps,
    )


def _generator_steps(source: str):
    return _function(source)._source_visible_generator_steps({})


def _walrus_records(machine) -> list:
    return [
        (item.name, item.evaluation)
        for item in machine.binding_state
        if isinstance(item, GeneratorWalrusBindingV1)
    ]


def test_a_yield_assignment_binds_the_sent_value_under_its_key() -> None:
    machine = _generator(
        "yield_assign",
        YieldAssignStepV1(
            YieldStepV1(_walrus_sugar("x", 5)), "y", "fragment:yield-assign", Y_KEY
        ),
        ReturnStepV1(EvaluationRefSugar(evaluation=Y_KEY, name="y", site=None)),
    )
    yielded = machine.resume()
    assert isinstance(yielded, YieldEffect)
    assert yielded.value == TermValue(5)
    assert _walrus_records(yielded.machine) == [("x", KEY)]
    terminated = yielded.machine.send(TermValue(7))
    assert isinstance(terminated, GeneratorTerminationV1)
    assert terminated.return_value == TermValue(7)
    (assigned,) = [
        item
        for item in terminated.binding_state
        if isinstance(item, GeneratorAssignBindingV1)
    ]
    assert (assigned.name, assigned.value, assigned.evaluation) == (
        "y",
        TermValue(7),
        Y_KEY,
    )


def test_a_plain_resume_sends_none_into_a_yield_assignment() -> None:
    machine = _generator(
        "yield_assign_next",
        YieldAssignStepV1(
            YieldStepV1(IntLiteralSugar(5, site=SITE)), "y", "fragment:next", Y_KEY
        ),
        ReturnStepV1(EvaluationRefSugar(evaluation=Y_KEY, name="y", site=None)),
    )
    yielded = machine.resume()
    assert isinstance(yielded, YieldEffect)
    terminated = yielded.machine.resume()
    assert isinstance(terminated, GeneratorTerminationV1)
    assert terminated.return_value == NoneValue()


def test_a_yield_assignment_is_a_named_step_reading_both_writes() -> None:
    # `y = yield (x := 5); return (x, y)` with `send(7)` returns (5, 7): the
    # walrus wrote before the suspension, the send wrote `y` on the resume.
    steps = _generator_steps("def g():\n    y = yield (x := 5)\n    return (x, y)\n")
    assert isinstance(steps[0], YieldAssignStepV1)
    assert not any(isinstance(step, OpaqueStepV1) for step in steps)
    assert steps[0].name == "y"
    assert isinstance(steps[0].evaluation, str)
    assert steps[0].evaluation.startswith(EVALUATION_PREFIX)
    yielded = _generator("g", *steps).resume()
    assert isinstance(yielded, YieldEffect)
    assert yielded.value == TermValue(5)
    terminated = yielded.machine.send(TermValue(7))
    assert isinstance(terminated, GeneratorTerminationV1)
    assert terminated.return_value == TupleValue((TermValue(5), TermValue(7)))


def test_an_assignment_records_its_rhs_walrus_in_the_generator_frame() -> None:
    # `y = (x := 5)`: the walrus is recorded before `y`, and `y` holds the
    # value the walrus presents, never the walrus wrapper.
    machine = _generator(
        "assign_walrus",
        AssignStepV1("y", _walrus_sugar("x", 5), "fragment:assign-walrus"),
        YieldStepV1(IntLiteralSugar(1, site=SITE)),
        ReturnStepV1(
            EvaluationRefSugar(evaluation=KEY, name="x", site=None, walrus=True)
        ),
    )
    yielded = machine.resume()
    assert isinstance(yielded, YieldEffect)
    assert _walrus_records(yielded.machine) == [("x", KEY)]
    (assigned,) = [
        item
        for item in yielded.machine.binding_state
        if isinstance(item, GeneratorAssignBindingV1)
    ]
    assert assigned.value == TermValue(5)
    assert not isinstance(assigned.value, NamedExpressionValue)
    terminated = yielded.machine.resume()
    assert isinstance(terminated, GeneratorTerminationV1)
    assert terminated.return_value == TermValue(5)


def test_a_bare_walrus_between_yields_is_read_after_the_next_resume() -> None:
    machine = _generator(
        "bare_walrus",
        YieldStepV1(IntLiteralSugar(1, site=SITE)),
        TermStepV1(_walrus_sugar("x", 5), "fragment:bare-walrus"),
        YieldStepV1(IntLiteralSugar(2, site=SITE)),
        ReturnStepV1(
            EvaluationRefSugar(evaluation=KEY, name="x", site=None, walrus=True)
        ),
    )
    first = machine.resume()
    assert isinstance(first, YieldEffect)
    assert first.value == TermValue(1)
    assert _walrus_records(first.machine) == []
    second = first.machine.resume()
    assert isinstance(second, YieldEffect)
    assert second.value == TermValue(2)
    assert _walrus_records(second.machine) == [("x", KEY)]
    terminated = second.machine.resume()
    assert isinstance(terminated, GeneratorTerminationV1)
    assert terminated.return_value == TermValue(5)


def test_a_bare_walrus_statement_through_the_producer_is_read_after_resume() -> None:
    steps = _generator_steps(
        "def g():\n    yield 1\n    (x := 5)\n    yield 2\n    return x\n"
    )
    assert not any(isinstance(step, OpaqueStepV1) for step in steps)
    first = _generator("g_bare", *steps).resume()
    assert isinstance(first, YieldEffect)
    second = first.machine.resume()
    assert isinstance(second, YieldEffect)
    assert second.value == TermValue(2)
    terminated = second.machine.resume()
    assert isinstance(terminated, GeneratorTerminationV1)
    assert terminated.return_value == TermValue(5)


# ---------------------------------------------------------------------------
# A walrus in a conditional expression's arm binds on its own arm
# ---------------------------------------------------------------------------


def test_a_conditional_arm_walrus_binds_only_its_own_arm() -> None:
    # `1 if c else (x := 5)` with `x` 3 before it: one arm per branch.  Where
    # the walrus ran, `x` reads 5; on the other arm the walrus's key holds 3.
    outcome = IfExpSugar(
        test=NameSugar(name="c", site=SITE),
        body=IntLiteralSugar(1, site=SITE),
        orelse=_walrus_sugar("x", 5),
        site=SITE,
        walrus_priors=((KEY, "x", IntLiteralSugar(3, site=SITE)),),
    ).desugar(_root("walrus-ifexp"))
    arms = [
        exit_.value
        for exit_ in outcome_to_exitset(outcome).exits
        if isinstance(exit_, Completed)
    ]
    assert len(arms) == 2
    read = EvaluationRefSugar(evaluation=KEY, name="x", site=None, walrus=True)
    seen = []
    for value in arms:
        binds, presented = peel_walrus_binds(value)
        after = bind_walrus_binds(binds, _root("walrus-ifexp-after"))
        seen.append((presented, _value(read.desugar(after))))
    assert (TermValue(1), TermValue(3)) in seen
    assert (TermValue(5), TermValue(5)) in seen


def test_an_arm_walrus_with_no_prior_is_refused_on_the_other_arm() -> None:
    # `x` was not bound before: the arm the walrus did not run on holds
    # nothing, and the read there is refused by name.
    outcome = IfExpSugar(
        test=NameSugar(name="c", site=SITE),
        body=IntLiteralSugar(1, site=SITE),
        orelse=_walrus_sugar("x", 5),
        site=SITE,
    ).desugar(_root("walrus-ifexp-unbound"))
    arms = [
        exit_.value
        for exit_ in outcome_to_exitset(outcome).exits
        if isinstance(exit_, Completed)
    ]
    assert len(arms) == 2
    bound = [peel_walrus_binds(value) for value in arms]
    assert sorted(len(binds) for binds, _presented in bound) == [0, 1]
    read = EvaluationRefSugar(evaluation=KEY, name="x", site=None, walrus=True)
    for binds, presented in bound:
        after = bind_walrus_binds(binds, _root("walrus-ifexp-unbound-after"))
        if binds:
            assert presented == TermValue(5)
            assert _value(read.desugar(after)) == TermValue(5)
        else:
            assert presented == TermValue(1)
            with pytest.raises(ConstructionPanic):
                read.desugar(after)


def test_a_held_bind_takes_the_latest_earlier_write_of_its_name() -> None:
    # `f((x := 1), 2 if c else (x := 3))` on the arm where `c` held: `x` is
    # 1 there, not what it was before the statement.
    earlier = NamedExpressionValue("x", TermValue(1), evaluation=KEY + ":first")
    held = NamedExpressionValue("x", TermValue(0), evaluation=KEY, held=True)
    binds, presented = peel_walrus_binds(
        carry_walrus_binds((earlier, held), TermValue(2))
    )
    assert presented == TermValue(2)
    assert [(bind.evaluation, bind.assigned_value) for bind in binds] == [
        (KEY + ":first", TermValue(1)),
        (KEY, TermValue(1)),
    ]
    after = bind_walrus_binds(binds, _root("walrus-held"))
    read = EvaluationRefSugar(evaluation=KEY, name="x", site=None, walrus=True)
    assert _value(read.desugar(after)) == TermValue(1)


def test_an_arm_walrus_carries_the_prior_read_of_its_name() -> None:
    rewritten = _function(
        "def f(c):\n    x = 3\n    y = 1 if c else (x := 5)\n    return x\n"
    ).substitute({})
    (walrus,) = _walruses(rewritten)
    conditional = next(node for node in rewritten.walk() if node.kind == "IfExp")
    assert conditional.walrus_prior_keys == ((walrus.evaluation, "x"),)
    sugar = conditional.sugar()
    assert isinstance(sugar, IfExpSugar)
    assert [(key, name) for key, name, _prior in sugar.walrus_priors] == [
        (walrus.evaluation, "x")
    ]


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        # The arm taken ran the walrus.
        ("(x := 5) if True else 1", 5),
        ("1 if False else (x := 5)", 5),
        # The arm taken did not: `x` is what it was before.
        ("1 if True else (x := 5)", 3),
        ("(x := 5) if False else 1", 3),
    ],
)
def test_a_ground_conditional_reads_the_arm_it_took(
    expression: str, expected: int
) -> None:
    returned = _returned_value(
        _call_outcome(
            "def f():\n"
            "    x = 3\n"
            "    y = " + expression + "\n"
            "    return x\n"
            "\n"
            "f()\n"
        )
    )
    assert returned == TermValue(expected)
