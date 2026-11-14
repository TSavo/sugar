"""``a, b = f()``: a later read is a reference to its projection of the
statement's one evaluation.

Temporal choice 1 (#7661), the unpack half of item 7: substitution bound
nothing for an unpacking assignment whose right-hand side is not a display, so
a later read of ``a`` fell to whatever ``a`` held before the statement -- the
seeded unbound state in a function (a false ``NameError``), or a stale earlier
binding. Each Name target is now bound to ``EvaluationRef(<its projection of
the statement's evaluation key>)``, and the unpack sugar binds each member
under that projection at reduce.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect.name_error_effect import NameErrorEffect
from sugar_lift_py_tests.floor import ListValue, TermValue
from sugar_lift_py_tests.floor.scope_rebind import ScopeRebind, ScopeRebinds
from sugar_lift_py_tests.floor.tuple_literal_value import TupleLiteralValue
from sugar_lift_py_tests.outcome import ExitSet, Halted
from sugar_lift_py_tests.sugar.dynamic_unpack_assign_sugar import (
    DynamicUnpackAssignSugar,
)
from sugar_lift_py_tests.sugar.evaluation_ref_sugar import EvaluationRefSugar
from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock
from sugar_lift_py_tests.sugar.if_sugar import _arm_evaluations
from sugar_lift_py_tests.sugar.nested_dynamic_unpack_assign_sugar import (
    NestedDynamicUnpackAssignSugar,
)
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.unpack_projection_targets import (
    NameUnpackTarget,
    StarUnpackTarget,
)
from sugar_lift_py_tests.temporal.temporal_context import (
    EVALUATION_PREFIX,
    projection_key,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.nodes import Assign, EvaluationRef, FunctionDef, Return
from sugar_source_tree.tree import SourceFile

KEY = EVALUATION_PREFIX + "blake3-512:test-unpack-evaluation"
ONE, TWO, THREE = TermValue(1), TermValue(2), TermValue(3)

FLAT = "def f(o):\n    a, b = o\n    return a\n"
NESTED = "def f(o):\n    (a, b), c = o\n    return b\n"
STARRED = "def f(o):\n    a, *rest = o\n    return rest\n"
BESIDE_A_STORE = "def f(o, p):\n    a, o.x = p\n    return a\n"
BOTH = "def f(o):\n    a, b = o\n    return a, b\n"
EARLIER = "def f(o, q):\n    a = q\n    a, b = o\n    return a\n"
DISPLAY = "def f(p, q):\n    a, b = p, q\n    return a\n"
UNROLLED = "def f(o):\n    for v in [1, 2]:\n        a, b = o\n    return a\n"


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
        (source, "unpack_evaluation_reference.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(node for node in tree.nodes() if isinstance(node, FunctionDef))


def _body(source: str) -> tuple:
    return _function(source).substitute({}).body


def _carries_evaluation(node) -> bool:
    key = getattr(node, "evaluation", None)
    return isinstance(node, Assign) and isinstance(key, str)


def _assign_and_return(source: str) -> tuple[Assign, Return]:
    body = _body(source)
    assign = next(node for node in body if _carries_evaluation(node))
    ret = body[-1]
    assert isinstance(ret, Return)
    return assign, ret


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


# ---------------------------------------------------------------------------
# Substitution: each target reads its projection of the one evaluation.
# ---------------------------------------------------------------------------


def test_read_after_unpack_references_its_projection() -> None:
    assign, ret = _assign_and_return(FLAT)
    assert assign.evaluation.startswith(EVALUATION_PREFIX)
    assert isinstance(ret.value, EvaluationRef)
    assert ret.value.evaluation == projection_key(assign.evaluation, "a")
    assert ret.value.name == "a"


def test_each_target_is_its_own_projection() -> None:
    assign, ret = _assign_and_return(BOTH)
    read_a, read_b = ret.value.elts
    assert isinstance(read_a, EvaluationRef)
    assert isinstance(read_b, EvaluationRef)
    assert read_a.evaluation == projection_key(assign.evaluation, "a")
    assert read_b.evaluation == projection_key(assign.evaluation, "b")
    assert read_a.evaluation != read_b.evaluation


def test_a_starred_target_references_its_projection() -> None:
    assign, ret = _assign_and_return(STARRED)
    assert isinstance(ret.value, EvaluationRef)
    assert ret.value.evaluation == projection_key(assign.evaluation, "rest")


def test_a_nested_target_references_its_projection() -> None:
    assign, ret = _assign_and_return(NESTED)
    assert isinstance(ret.value, EvaluationRef)
    assert ret.value.evaluation == projection_key(assign.evaluation, "b")


def test_a_name_beside_a_store_leaf_references_its_projection() -> None:
    assign, ret = _assign_and_return(BESIDE_A_STORE)
    assert isinstance(ret.value, EvaluationRef)
    assert ret.value.evaluation == projection_key(assign.evaluation, "a")


def test_an_earlier_binding_of_the_name_is_not_read() -> None:
    # Before, the read substituted to the stale `a = q`: the unpack's own
    # member was never what `return a` read.
    assign, ret = _assign_and_return(EARLIER)
    assert isinstance(ret.value, EvaluationRef)
    assert ret.value.evaluation == projection_key(assign.evaluation, "a")


def test_a_display_unpack_still_binds_its_members() -> None:
    body = _body(DISPLAY)
    assert not isinstance(body[-1].value, EvaluationRef)
    assert not any(_carries_evaluation(node) for node in body)


def test_each_unrolled_iteration_is_its_own_evaluation() -> None:
    body = _body(UNROLLED)
    assigns = [node for node in body if isinstance(node, Assign)]
    assert len(assigns) == 2
    assert assigns[0].evaluation != assigns[1].evaluation
    ret = body[-1]
    assert isinstance(ret, Return)
    assert isinstance(ret.value, EvaluationRef)
    assert ret.value.evaluation == projection_key(assigns[1].evaluation, "a")


def test_statement_sugar_carries_its_evaluation_key() -> None:
    statement = _function(FLAT).sugar().statements[0]
    assert isinstance(statement, DynamicUnpackAssignSugar)
    assert isinstance(statement.evaluation, str)
    assert statement.evaluation.startswith(EVALUATION_PREFIX)


def test_nested_statement_sugar_carries_its_evaluation_key() -> None:
    statement = _function(NESTED).sugar().statements[0]
    assert isinstance(statement, NestedDynamicUnpackAssignSugar)
    assert isinstance(statement.evaluation, str)


# ---------------------------------------------------------------------------
# Reduce: the completed unpack binds each member under its projection.
# ---------------------------------------------------------------------------


def _value(outcome):
    """The single completed value of an outcome, in either outcome form."""
    return outcome.completed_value()


def _flat(evaluation: str | None = None) -> DynamicUnpackAssignSugar:
    value = _FloorSugar(TupleLiteralValue((ONE, TWO)))
    return DynamicUnpackAssignSugar(("a", "b"), value, "site", evaluation=evaluation)


def _read(name: str) -> EvaluationRefSugar:
    key = projection_key(KEY, name)
    return EvaluationRefSugar(evaluation=key, name=name, site=None)


def test_a_completed_unpack_binds_each_projection_and_no_name() -> None:
    bindings = (
        (projection_key(KEY, "a"), ONE),
        (projection_key(KEY, "b"), TWO),
    )
    assert _value(_flat(KEY).desugar(None)) == ScopeRebinds(bindings)
    ctx = _value(_flat(KEY).desugar(None)).extend_scope(
        ReduceContext.root(owner="unpack-evaluation-no-name")
    )
    assert ctx.temporal.value_if_bound("a") is None
    assert ctx.temporal.value_if_bound("b") is None


def test_an_unsubstituted_unpack_binds_the_names_alone() -> None:
    bindings = (("a", ONE), ("b", TWO))
    assert _value(_flat().desugar(None)) == ScopeRebinds(bindings)


def test_a_starred_projection_is_the_middle_list() -> None:
    sugar = DynamicUnpackAssignSugar(
        target_names=("a",),
        value=_FloorSugar(TupleLiteralValue((ONE, TWO, THREE))),
        site="site",
        star_name="rest",
        prefix_names=("a",),
        evaluation=KEY,
    )
    value = _value(sugar.desugar(None))
    assert isinstance(value, ScopeRebinds)
    rest = (projection_key(KEY, "rest"), ListValue((TWO, THREE)))
    assert rest in value.bindings


def test_a_reference_reads_its_member() -> None:
    rebinds = _value(_flat(KEY).desugar(None))
    ctx = rebinds.extend_scope(ReduceContext.root(owner="unpack-evaluation"))
    assert _value(_read("a").desugar(ctx)) == ONE
    assert _value(_read("b").desugar(ctx)) == TWO


def test_a_name_leaf_beside_a_store_binds_its_projection() -> None:
    key_a = projection_key(KEY, "a")
    key_r = projection_key(KEY, "r")
    name = NameUnpackTarget("a", evaluation=KEY).apply_member(ONE, None)
    star = StarUnpackTarget("r", evaluation=KEY).apply_member(ONE, None)
    plain = NameUnpackTarget("a").apply_member(ONE, None)
    assert _value(name) == ScopeRebinds(((key_a, ONE),))
    assert _value(star) == ScopeRebinds(((key_r, ONE),))
    assert _value(plain) == ScopeRebind("a", ONE)


def _arm(ctx) -> ExitSet:
    return ExitSet.completed(_ReducedBlock((), True, (), context=ctx))


def test_an_if_carries_an_arm_projection_out() -> None:
    key_a = projection_key(KEY, "a")
    base = ReduceContext.root(owner="unpack-evaluation-join")
    then = base.with_temporal(base.temporal.bind_value(key_a, TWO))
    assert _arm_evaluations((_arm(then), _arm(base)), base) == ((key_a, TWO),)


# ---------------------------------------------------------------------------
# The false halt: a later read no longer falls to the seeded unbound state.
# ---------------------------------------------------------------------------

UNPACK_THEN_READ = (
    "def A(p, q, r, s):\n"
    "    xs = [[p, q], [r, s]]\n"
    "    a, b = xs[0]\n"
    "    return a\n"
)
READ_THEN_UNPACK = (
    "def A(p, q, r, s):\n"
    "    xs = [[p, q], [r, s]]\n"
    "    y = a\n"
    "    a, b = xs[0]\n"
    "    return y\n"
)


def test_a_read_after_a_dynamic_unpack_is_not_a_name_error(tmp_path: Path) -> None:
    outcome = _outcome(tmp_path, UNPACK_THEN_READ, "unpack_then_read")
    assert _value(outcome) is not None, outcome
    assert "NameError" not in repr(outcome)


def test_a_read_before_the_unpack_still_halts(tmp_path: Path) -> None:
    # Discrimination: the unpack binds from its statement on, never before.
    outcome = _outcome(tmp_path, READ_THEN_UNPACK, "read_then_unpack")
    exits = outcome
    halts = [face for face in exits.exits if isinstance(face, Halted)]
    names = [f.effect.name for f in halts if isinstance(f.effect, NameErrorEffect)]
    assert names and set(names) == {"a"}
