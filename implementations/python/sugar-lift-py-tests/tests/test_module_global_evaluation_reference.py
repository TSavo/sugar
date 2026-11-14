"""A function's read of a module global, and a module class body's read of a
module name, are references to the module body's evaluations (temporal
choice 1, #7661; #7757 item 7).

A function runs after the module body: a global it reads is the module's
final binding of it, the evaluation of the module body's last write
(``FunctionDef._module_global_references``).  A module class statement runs
once, in source order: its body reads a module name as the module held it
when the statement ran (``ClassDef._module_name_references``).  Neither reads
the name, so ``x += e`` no longer writes the name for them: it binds only its
evaluation, except for a name a live loop carries, which the recurrence
reads through the temporal.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.floor.scope_rebind import ScopeRebinds
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.augassign_sugar import AugAssignSugar
from sugar_lift_py_tests.sugar.evaluation_ref_sugar import EvaluationRefSugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.temporal.temporal_context import EVALUATION_PREFIX
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import (
    AugAssign,
    ClassDef,
    EvaluationRef,
    FunctionDef,
    Name,
    Return,
)
from sugar_source_tree.tree import SourceFile

KEY = EVALUATION_PREFIX + "blake3-512:module-global-evaluation"


def _source(source: str) -> SourceFile:
    return SourceFile(
        (source, "module_global_evaluation.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _module_evaluations(tree: SourceFile) -> list[str]:
    """The evaluation key of each module-level ``x += e``, in source order."""
    body = tree.root.substitute({}).body
    return [node.evaluation for node in body if isinstance(node, AugAssign)]


def _function(tree: SourceFile, name: str = "f") -> FunctionDef:
    return next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == name
    )


def _returned(function: FunctionDef):
    statement = function.substitute({}).body[-1]
    assert isinstance(statement, Return)
    return statement.value


# -- a function reads a module global ------------------------------------------


def test_a_global_rebound_twice_reads_the_last_evaluation() -> None:
    tree = _source("x = 1\ndef f():\n    return x\nx += 1\nx += 1\n")
    first, second = _module_evaluations(tree)
    read = _returned(_function(tree))
    assert isinstance(read, EvaluationRef)
    assert read.name == "x"
    # The module's final binding, wherever the def stands: not the first
    # rebind, and not the value the module held at the def.
    assert read.evaluation == second
    assert read.evaluation != first


def test_the_read_is_spanned_at_its_use() -> None:
    tree = _source("x = 1\nx += 1\nx += 1\ndef f():\n    return x\n")
    function = _function(tree)
    read = _returned(function)
    assert isinstance(read, EvaluationRef)
    assert read.span == function.body[0].value.span


def test_the_same_source_gives_the_same_reference() -> None:
    source = "x = 1\nx += 1\nx += 1\ndef f():\n    return x\n"
    first = _returned(_function(_source(source)))
    second = _returned(_function(_source(source)))
    assert first.evaluation == second.evaluation


def test_a_local_of_the_same_name_is_not_the_global() -> None:
    tree = _source("x = 1\nx += 1\ndef f():\n    x = 5\n    return x\n")
    assert not isinstance(_returned(_function(tree)), EvaluationRef)


def test_a_global_last_written_by_an_assignment_is_read_by_name() -> None:
    tree = _source("x = 1\nx += 1\nx = 3\ndef f():\n    return x\n")
    assert isinstance(_returned(_function(tree)), Name)


# -- a module class body reads a module name ----------------------------------


def test_a_class_body_reads_the_binding_its_statement_saw() -> None:
    tree = _source("x = 1\nx += 1\nclass C:\n    y = x\nx += 1\n")
    first, second = _module_evaluations(tree)
    definition = next(node for node in tree.nodes() if isinstance(node, ClassDef))
    (field,) = definition.sugar().fields
    assert field.name == "y"
    assert isinstance(field.value_sugar, EvaluationRefSugar)
    # The class statement ran before the second rebind.
    assert field.value_sugar.evaluation == first
    assert field.value_sugar.evaluation != second


def test_a_name_the_class_body_binds_is_not_read_from_the_module() -> None:
    tree = _source("x = 1\nx += 1\nclass C:\n    x = 2\n    y = x\n")
    definition = next(node for node in tree.nodes() if isinstance(node, ClassDef))
    fields = {field.name: field for field in definition.sugar().fields}
    assert not isinstance(fields["y"].value_sugar, EvaluationRefSugar)


# -- x += e binds its evaluation, and the name only for a live loop -----------


@dataclass(frozen=True)
class _Ground(Sugar):
    value: object

    def desugar(self, ctx=None):
        del ctx
        return ExitSet.completed(self.value)

    @classmethod
    def witnesses(cls):
        return ()


def _aug(evaluation: str) -> AugAssignSugar:
    tree = _source("def f(x):\n    x += 1\n")
    statement = _function(tree).sugar().statements[0]
    assert isinstance(statement, AugAssignSugar)
    return replace(
        statement,
        left=_Ground(TermValue(3)),
        right=_Ground(TermValue(2)),
        evaluation=evaluation,
    )


def test_outside_a_live_loop_only_the_evaluation_is_bound() -> None:
    ctx = ReduceContext.root(owner="module-global-evaluation")
    rebind = _aug(KEY).desugar(ctx).completed_value()
    assert isinstance(rebind, ScopeRebinds)
    assert rebind.bindings == ((KEY, TermValue(5)),)
    after = rebind.extend_scope(ctx)
    assert after.temporal.value_if_bound(KEY) == TermValue(5)
    assert after.temporal.value_if_bound("x") is None


def test_a_name_a_live_loop_carries_binds_only_the_evaluation_too() -> None:
    # The recurrence reads a carried name's writes by their keys, so the
    # name is never written inside a live loop either.
    ctx = replace(
        ReduceContext.root(owner="module-global-evaluation"),
        live_loop_names=frozenset({"x"}),
    )
    rebind = _aug(KEY).desugar(ctx).completed_value()
    assert isinstance(rebind, ScopeRebinds)
    assert rebind.bindings == ((KEY, TermValue(5)),)
    assert rebind.extend_scope(ctx).temporal.value_if_bound("x") is None
