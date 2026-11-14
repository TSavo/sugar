"""``y = x``: a later read of ``y`` is a reference to the assignment's
evaluation, never ``x`` read again where ``y`` is used (temporal choice 1,
#7661; #7757 item 7, reported by #7928).

Before, ``y`` was bound to the reference ``y = x`` read, which names ``x``,
and a reference reads the latest of its evaluation and a write of its name.
So ``x = 1; x += 1; y = x; x += 1; return y`` returned 3.  #7928 closed this
in live loop bodies only.  Now every assignment whose value is a reference to
an evaluation binds each such Name target to its own projection of the
assignment's evaluation (``Assign.alias_evaluations``); the assignment binds
the value it read under that key at reduce, and every later read of the name
reads that key.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
from sugar_lift_py_tests.floor.return_value import ReturnValue
from sugar_lift_py_tests.outcome import Completed, ExitSet, outcome_to_exitset
from sugar_lift_py_tests.sugar.assign_sugar import (
    AssignSugar,
    ChainedAssignSugar,
)
from sugar_lift_py_tests.sugar.evaluation_ref_sugar import EvaluationRefSugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.temporal.temporal_context import (
    EVALUATION_PREFIX,
    projection_key,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.nodes import (
    Assign,
    AugAssign,
    EvaluationRef,
    FunctionDef,
    Return,
)
from sugar_source_tree.tree import SourceFile

KEY = EVALUATION_PREFIX + "blake3-512:test-alias-evaluation"
TWO, THREE = TermValue(2), TermValue(3)

STRAIGHT = (
    "def f():\n"
    "    x = 1\n"
    "    x += 1\n"
    "    y = x\n"
    "    x += 1\n"
    "    return y\n"
)
IN_IF = (
    "def f(c):\n"
    "    x = 1\n"
    "    x += 1\n"
    "    if c:\n"
    "        y = x\n"
    "        x += 1\n"
    "        return y\n"
    "    return 0\n"
)
IN_UNROLLED_FOR = (
    "def f():\n"
    "    x = 1\n"
    "    for _ in [0, 1]:\n"
    "        x += 1\n"
    "        y = x\n"
    "        x += 1\n"
    "    return y\n"
)
IN_TRY_BODY = (
    "def f():\n"
    "    x = 1\n"
    "    x += 1\n"
    "    try:\n"
    "        y = x\n"
    "        x += 1\n"
    "    finally:\n"
    "        x += 1\n"
    "    return y\n"
)
IN_FINALLY = (
    "def f():\n"
    "    x = 1\n"
    "    try:\n"
    "        x += 1\n"
    "    finally:\n"
    "        y = x\n"
    "        x += 1\n"
    "    return y\n"
)
CHAINED = (
    "def f():\n"
    "    x = 1\n"
    "    x += 1\n"
    "    y = z = x\n"
    "    x += 1\n"
    "    return z\n"
)
ALIAS_OF_ALIAS = (
    "def f():\n"
    "    x = 1\n"
    "    x += 1\n"
    "    y = x\n"
    "    w = y\n"
    "    x += 1\n"
    "    return w\n"
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


def _function(source: str) -> FunctionDef:
    tree = SourceFile(
        (source, "alias_evaluation_reference.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(node for node in tree.nodes() if isinstance(node, FunctionDef))


def _outcome(tmp_path: Path, source: str, stem: str):
    path = tmp_path / f"{stem}.py"
    path.write_text(source, encoding="utf-8")
    functions = list(
        SourceFile(
            path_source(str(path)),
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        ).functions()
    )
    return functions[-1].sugar().desugar(None)


def _returned(outcome) -> list:
    """Every value a completed face of ``outcome`` returns."""
    found: list = []

    def visit(value) -> None:
        if isinstance(value, (ReturnValue, GuardedReturn)):
            found.append(value.value)
            return
        for entry in getattr(value, "statements", ()) or ():
            visit(entry)
        record = getattr(value, "record", None)
        if record is not None:
            visit(record)

    for exit_ in outcome_to_exitset(outcome).exits:
        if isinstance(exit_, Completed):
            visit(exit_.value)
    return found


# ---------------------------------------------------------------------------
# Substitution: the alias reads its own projection of the assignment.
# ---------------------------------------------------------------------------


def test_an_alias_reads_its_own_projection_of_the_assignment() -> None:
    body = _function(STRAIGHT).substitute({}).body
    first, assign = [node for node in body if isinstance(node, Assign)]
    ret = body[-1]
    assert isinstance(ret, Return)
    # ``x = 1`` reads no evaluation and carries no key.
    assert getattr(first, "evaluation", None) is None
    assert isinstance(assign.evaluation, str)
    assert isinstance(ret.value, EvaluationRef)
    assert ret.value.evaluation == projection_key(assign.evaluation, "y")
    assert ret.value.name == "y"


def test_the_alias_never_reads_the_name_it_was_given() -> None:
    body = _function(STRAIGHT).substitute({}).body
    augs = [node for node in body if isinstance(node, AugAssign)]
    ret = body[-1]
    assert all(ret.value.evaluation != aug.evaluation for aug in augs)
    assert ret.value.name != "x"


def test_the_assignment_sugar_carries_the_alias_key() -> None:
    statements = _function(STRAIGHT).sugar().statements
    assigns = {
        sugar.name: sugar for sugar in statements if isinstance(sugar, AssignSugar)
    }
    # ``x = 1`` reads no evaluation; ``y = x`` reads ``x += 1``'s.
    assert assigns["x"].evaluations == ()
    ((name, key),) = assigns["y"].evaluations
    assert name == "y"
    assert key.startswith(EVALUATION_PREFIX)
    assert key.endswith("/y")


def test_an_assignment_of_no_evaluation_carries_no_key() -> None:
    body = _function("def f(z):\n    y = z\n    return y\n").substitute({}).body
    assign = next(node for node in body if isinstance(node, Assign))
    assert getattr(assign, "evaluation", None) is None
    assert not isinstance(body[-1].value, EvaluationRef)


def test_each_unrolled_iteration_aliases_its_own_evaluation() -> None:
    body = _function(IN_UNROLLED_FOR).substitute({}).body
    assigns = [node for node in body if isinstance(node, Assign)]
    aliases = [
        node for node in assigns if isinstance(getattr(node, "evaluation", None), str)
    ]
    assert len(aliases) == 2
    assert aliases[0].evaluation != aliases[1].evaluation
    ret = body[-1]
    assert isinstance(ret.value, EvaluationRef)
    assert ret.value.evaluation == projection_key(aliases[1].evaluation, "y")


# ---------------------------------------------------------------------------
# Reduce: the assignment binds the value it read under the alias key.
# ---------------------------------------------------------------------------


def test_the_assignment_binds_its_value_under_the_alias_key() -> None:
    ctx = ReduceContext.root(owner="alias-evaluation")
    sugar = AssignSugar(
        name="y", value=_FloorSugar(TWO), site=None, evaluations=(("y", KEY),)
    )
    block = outcome_to_exitset(sugar.desugar(ctx)).completed_value()
    assert block.context.temporal.value_if_bound(KEY) == TWO


def test_a_later_write_of_the_aliased_name_is_not_read() -> None:
    ctx = ReduceContext.root(owner="alias-evaluation")
    sugar = AssignSugar(
        name="y", value=_FloorSugar(TWO), site=None, evaluations=(("y", KEY),)
    )
    block = outcome_to_exitset(sugar.desugar(ctx)).completed_value()
    later = block.context.with_temporal(block.context.temporal.bind_value("x", THREE))
    read = EvaluationRefSugar(evaluation=KEY, name="y", site=None)
    assert outcome_to_exitset(read.desugar(later)).completed_value() == TWO


def test_a_chained_assignment_binds_each_alias_key() -> None:
    ctx = ReduceContext.root(owner="alias-evaluation")
    key_y, key_z = projection_key(KEY, "y"), projection_key(KEY, "z")
    value = _FloorSugar(TWO)
    sugar = ChainedAssignSugar(
        bindings=(("y", value), ("z", value)),
        stores=(),
        value=value,
        site=None,
        evaluations=(("y", key_y), ("z", key_z)),
    )
    block = outcome_to_exitset(sugar.desugar(ctx)).completed_value()
    assert block.context.temporal.value_if_bound(key_y) == TWO
    assert block.context.temporal.value_if_bound(key_z) == TWO


def test_without_an_alias_the_assignment_binds_no_key() -> None:
    ctx = ReduceContext.root(owner="alias-evaluation")
    sugar = AssignSugar(name="y", value=_FloorSugar(TWO), site=None)
    outcome = outcome_to_exitset(sugar.desugar(ctx))
    block = outcome.completed_value()
    context = getattr(block, "context", None)
    assert context is None or context.temporal.value_if_bound(KEY) is None


# ---------------------------------------------------------------------------
# The function: ``y`` is the value ``x`` held at ``y = x``.
# ---------------------------------------------------------------------------


def test_straight_line_alias_returns_the_value_it_read(tmp_path: Path) -> None:
    returned = _returned(_outcome(tmp_path, STRAIGHT, "straight"))
    assert returned == [TWO], returned


def test_alias_inside_an_if_returns_the_value_it_read(tmp_path: Path) -> None:
    returned = _returned(_outcome(tmp_path, IN_IF, "in_if"))
    assert TWO in returned, returned
    assert THREE not in returned, returned


def test_alias_inside_an_unrolled_for_returns_its_iterations_value(
    tmp_path: Path,
) -> None:
    # x: 1 -> 2 (y = 2) -> 3 -> 4 (y = 4) -> 5; the last iteration's y is 4.
    returned = _returned(_outcome(tmp_path, IN_UNROLLED_FOR, "in_unrolled_for"))
    assert returned == [TermValue(4)], returned


def test_alias_inside_a_try_body_returns_the_value_it_read(tmp_path: Path) -> None:
    returned = _returned(_outcome(tmp_path, IN_TRY_BODY, "in_try_body"))
    assert TWO in returned, returned
    assert THREE not in returned, returned
    assert TermValue(4) not in returned, returned


def test_alias_inside_finally_returns_the_value_it_read(tmp_path: Path) -> None:
    returned = _returned(_outcome(tmp_path, IN_FINALLY, "in_finally"))
    assert TWO in returned, returned
    assert THREE not in returned, returned


def test_chained_alias_returns_the_value_it_read(tmp_path: Path) -> None:
    returned = _returned(_outcome(tmp_path, CHAINED, "chained"))
    assert returned == [TWO], returned


def test_alias_of_an_alias_returns_the_value_it_read(tmp_path: Path) -> None:
    returned = _returned(_outcome(tmp_path, ALIAS_OF_ALIAS, "alias_of_alias"))
    assert returned == [TWO], returned
