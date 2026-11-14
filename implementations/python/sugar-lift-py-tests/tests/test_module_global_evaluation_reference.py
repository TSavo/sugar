"""A function's read of a module global, and a module class body's read of a
module name, are references to the module body's evaluations (temporal
choice 1, #7661; #7757 item 7).

A function reads a global when it runs.  Called after import, it reads the
module's final binding of it, the evaluation of the module body's last write
(``FunctionDef._module_global_references``).  Called while the module body
runs (a call in the module body or a class body, or one reached from such a
call), it reads the binding standing at that call
(``SourceUnit.module_bindings_at``).  A module class statement runs once, in
source order: its body reads a module name as the module held it when the
statement ran (``ClassDef._module_name_references``).  Neither reads the name,
so ``x += e`` no longer writes the name for them: it binds only its
evaluation, except for a name a live loop carries, which the recurrence reads
through the temporal.  A walrus's write is read through its evaluation too;
a binding the module body does not decide at the read is cited ``undecided``
by name, never read by name.

An implicit call (an operator's ``__add__``, a subscript's ``__getitem__``, a
property getter) is a call site too: its node's sugar is stamped with its
module execution site, reduces there, and the dunder's frame is read again
at it (``frame_at_current_module_execution_site``).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, replace

import pytest

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect import NameErrorEffect
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.floor.scope_rebind import ScopeRebinds
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_py_tests.source_call_frame import (
    frame_at_current_module_execution_site,
)
from sugar_lift_py_tests.sugar.augassign_sugar import AugAssignSugar
from sugar_lift_py_tests.sugar.evaluation_ref_sugar import EvaluationRefSugar
from sugar_lift_py_tests.sugar.name_sugar import NameSugar
from sugar_lift_py_tests.sugar.return_sugar import ReturnSugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.temporal.temporal_context import EVALUATION_PREFIX
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.binding_state import UnboundBinding
from sugar_source_tree.nodes import (
    UNDECIDED_MODULE_BINDING,
    AnnAssign,
    Assign,
    Attribute,
    AugAssign,
    BinOp,
    BranchResultRef,
    Call,
    ClassDef,
    EffectRef,
    EvaluationRef,
    For,
    FunctionDef,
    GuardedBindingRead,
    IfExp,
    ImportBindingRef,
    ListComp,
    Name,
    Return,
    Subscript,
    TypeAlias,
    With,
    _at_module_execution_site,
    _module_reference_state,
    construct_at_module_execution_site,
    current_module_execution_site,
    stamped_module_execution_site,
)
from sugar_source_tree.panic import SugarNotWritten
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


def _assignment_keys(tree: SourceFile, name: str) -> list[str]:
    """The key of ``name``'s projection of each module-level ``name = e``
    and ``name: T = e``, in source order."""
    body = tree.root.substitute({}).body
    return [
        dict(node.target_evaluations())[name]
        for node in body
        if isinstance(node, (Assign, AnnAssign))
        and name in dict(node.target_evaluations())
    ]


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


def _calls(tree: SourceFile, name: str = "f") -> list[Call]:
    """Every call of ``name`` in the source, in source order."""
    return sorted(
        (
            node
            for node in tree.nodes()
            if isinstance(node, Call)
            and isinstance(node.func, Name)
            and node.func.id == name
        ),
        key=lambda node: node.span.start,
    )


def _returned_at(call: Call, function: FunctionDef):
    """``function``'s returned read, its body substituted at the module
    execution site of ``call`` (as the call's construction does)."""
    site = call.unit.module_execution_site(call)
    assert site is not None
    return construct_at_module_execution_site(site, lambda: _returned(function))


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


def test_a_global_last_written_by_an_assignment_reads_its_key() -> None:
    tree = _source("x = 1\nx += 1\nx = 3\ndef f():\n    return x\n")
    *_, last = _assignment_keys(tree, "x")
    read = _returned(_function(tree))
    assert isinstance(read, EvaluationRef)
    assert read.evaluation == last


# -- every module-level binding kind is read through its key (#7757 item 7) --


REBOUND_AROUND_A_CALL = "X = 1\ndef f():\n    return X\ny = f()\nX = 2\n"


def test_a_plain_global_reads_the_module_final_assignment() -> None:
    tree = _source("X = 1\ndef f():\n    return X\nX = 2\n")
    first, second = _assignment_keys(tree, "X")
    read = _returned(_function(tree))
    assert isinstance(read, EvaluationRef)
    assert read.name == "X"
    assert read.evaluation == second
    assert read.evaluation != first


def test_a_plain_global_read_at_a_module_call_reads_the_assignment_there() -> None:
    tree = _source(REBOUND_AROUND_A_CALL)
    first, second = _assignment_keys(tree, "X")
    (call,) = _calls(tree)
    read = _returned_at(call, _function(tree))
    assert isinstance(read, EvaluationRef)
    assert read.evaluation == first
    after_import = _returned(_function(tree))
    assert isinstance(after_import, EvaluationRef)
    assert after_import.evaluation == second


def test_an_annotated_global_reads_its_key() -> None:
    tree = _source("X: int = 1\ndef f():\n    return X\n")
    (key,) = _assignment_keys(tree, "X")
    read = _returned(_function(tree))
    assert isinstance(read, EvaluationRef)
    assert read.evaluation == key


def test_a_global_unbound_at_the_module_call_is_undecided() -> None:
    tree = _source("def f():\n    return X\ny = f()\nX = 1\n")
    (call,) = _calls(tree)
    with pytest.raises(SugarNotWritten, match="undecided module binding of `X`"):
        _returned_at(call, _function(tree))


TRY_IMPORT_FALLBACK = (
    "try:\n    import json\nexcept ImportError:\n    json = None\n"
    "def f():\n    return json\n"
)


def test_a_try_import_fallback_decides_the_binding_per_route() -> None:
    tree = _source(TRY_IMPORT_FALLBACK)
    read = _returned(_function(tree))
    # A phi over the try's route: the handler's ``json = None`` where the
    # import failed into the handler, the import table's row for the import
    # where it did not.  Never undecided, never the name read.
    assert isinstance(read, IfExp)
    assert isinstance(read.test, BranchResultRef)
    assert isinstance(read.body, EvaluationRef)
    assert read.body.name == "json"
    assert isinstance(read.orelse, ImportBindingRef)
    assert read.orelse.name == "json"
    assert read.orelse.target_symbol == "python:json"


def test_an_import_after_an_assignment_reads_the_import_table() -> None:
    tree = _source("json = None\nimport json\ndef f():\n    return json\n")
    unit = _function(tree).unit
    final = unit.module_bindings_at(None, {"json"})["json"]
    assert isinstance(final, ImportBindingRef)
    assert final.target_symbol == "python:json"


def test_the_import_arm_constructs_as_an_ordinary_read_of_the_name() -> None:
    # The import table's row is the read: it constructs exactly as a read of
    # ``json`` does (``_name_read_sugar``), and reduces, never refused.
    read = _returned(_function(_source(TRY_IMPORT_FALLBACK)))
    arm = read.orelse.sugar()
    plain = _source("import json\ndef f():\n    return json\n")
    ordinary = _returned(_function(plain))
    assert isinstance(ordinary, Name)
    assert type(arm) is type(ordinary.sugar()) is NameSugar
    assert arm.name == ordinary.sugar().name == "json"
    exits = arm.desugar(None).exits
    assert len(exits) == 1 and isinstance(exits[0], Completed), exits


def test_a_from_import_arm_reduces_too() -> None:
    tree = _source(
        "try:\n    from re import Pattern\nexcept ImportError:\n    Pattern = None\n"
        "def f():\n    return Pattern\n"
    )
    read = _returned(_function(tree))
    assert isinstance(read, IfExp)
    assert isinstance(read.orelse, ImportBindingRef)
    assert read.orelse.target_symbol == "python:re.Pattern"
    exits = read.orelse.sugar().desugar(None).exits
    assert len(exits) == 1 and isinstance(exits[0], Completed), exits


# -- a deleted target list, a type alias, an except* name (#7757 item 7) ------


@pytest.mark.parametrize("target", ["(X, Y)", "[X, Y]", "X, (Y,)"])
def test_a_deleted_target_list_unbinds_each_name(target: str) -> None:
    tree = _source(
        f"X = 1\nY = 2\ndel {target}\n"
        "def f():\n    return X\ndef g():\n    return Y\n"
    )
    unit = _function(tree).unit
    finals = unit.module_bindings_at(None, {"X", "Y"})
    assert isinstance(finals["X"], UnboundBinding)
    assert isinstance(finals["Y"], UnboundBinding)
    read = _returned(_function(tree))
    assert isinstance(read, GuardedBindingRead)
    assert isinstance(read.state, UnboundBinding)
    exits = _function(tree).sugar().desugar(None).exits
    halted = [e for e in exits if isinstance(e, Halted)]
    assert not [e for e in exits if isinstance(e, Completed)], exits
    assert len(halted) == 1 and isinstance(halted[0].effect, NameErrorEffect)
    assert halted[0].effect.name == "X"


@pytest.mark.skipif(not hasattr(ast, "TypeAlias"), reason="needs type aliases")
def test_a_type_alias_binds_its_name_as_a_definition_does() -> None:
    tree = _source("X = 1\ntype X = int\ndef f():\n    return X\n")
    final = _function(tree).unit.module_bindings_at(None, {"X"})["X"]
    assert isinstance(final, TypeAlias)
    # The read is the alias statement's own binding of the name, as a def's
    # is: never ``X = 1``'s evaluation, never undecided.
    read = _returned(_function(tree))
    assert isinstance(read, Name)
    assert read.id == "X"


TRY_STAR_AS = (
    "eg = None\ndel eg\n"
    "def f():\n    return eg\n"
    "try:\n    pass\nexcept* ValueError as eg:\n    y = f()\n"
)


def test_an_except_star_name_is_its_handlers_slot_inside_the_handler() -> None:
    tree = _source(TRY_STAR_AS)
    (call,) = _calls(tree)
    assert isinstance(_returned_at(call, _function(tree)), EffectRef)


def test_an_except_star_name_is_unbound_after_the_statement() -> None:
    tree = _source(TRY_STAR_AS)
    final = _function(tree).unit.module_bindings_at(None, {"eg"})["eg"]
    assert isinstance(final, UnboundBinding)
    read = _returned(_function(tree))
    assert isinstance(read, GuardedBindingRead)
    assert isinstance(read.state, UnboundBinding)


def test_an_except_star_name_bound_before_stays_undecided() -> None:
    # The route no handler took keeps ``eg = None``; no route slot of
    # ``except*`` decides which route left the statement.
    tree = _source(
        "eg = None\ndef f():\n    return eg\n"
        "try:\n    pass\nexcept* ValueError as eg:\n    pass\n"
    )
    with pytest.raises(SugarNotWritten, match="undecided module binding of `eg`"):
        _returned(_function(tree))


DEF_REBINDS = "X = None\ndef X():\n    pass\ndef f():\n    return X\ny = f()\n"


def test_a_def_after_an_assignment_binds_the_definition() -> None:
    tree = _source(DEF_REBINDS)
    unit = _function(tree).unit
    final = unit.module_bindings_at(None, {"X"})["X"]
    assert isinstance(final, FunctionDef)
    assert final.name == "X"
    # The read is the definition's own binding, as a local definition's is:
    # the name, never ``X = None``'s evaluation.
    read = _returned(_function(tree))
    assert isinstance(read, Name)
    assert read.id == "X"
    (call,) = _calls(tree)
    at_call = _returned_at(call, _function(tree))
    assert isinstance(at_call, Name)
    assert at_call.id == "X"


def test_a_call_before_the_def_reads_the_assignment() -> None:
    tree = _source("X = None\ndef f():\n    return X\ny = f()\ndef X():\n    pass\n")
    (key,) = _assignment_keys(tree, "X")
    (call,) = _calls(tree)
    at_call = _returned_at(call, _function(tree))
    assert isinstance(at_call, EvaluationRef)
    assert at_call.evaluation == key
    after_import = _returned(_function(tree))
    assert isinstance(after_import, Name)


def test_a_deleted_global_read_is_a_name_error_halt() -> None:
    tree = _source("X = 1\ndel X\ndef f():\n    return X\n")
    read = _returned(_function(tree))
    assert isinstance(read, GuardedBindingRead)
    assert isinstance(read.state, UnboundBinding)
    exits = _function(tree).sugar().desugar(None).exits
    assert not [e for e in exits if isinstance(e, Completed)], exits
    halted = [e for e in exits if isinstance(e, Halted)]
    assert len(halted) == 1, exits
    assert isinstance(halted[0].effect, NameErrorEffect)
    assert halted[0].effect.name == "X"


def test_a_star_import_leaves_every_global_undecided() -> None:
    tree = _source("from os import *\nX = 1\ndef f():\n    return X\n")
    assert _function(tree).unit.module_unthreaded_names() == frozenset({"X"})
    with pytest.raises(SugarNotWritten, match="undecided module binding of `X`"):
        _returned(_function(tree))


def test_a_dynamic_global_writer_leaves_every_global_undecided() -> None:
    tree = _source("X = 1\nglobals()['X'] = 2\ndef f():\n    return X\n")
    assert _function(tree).unit.module_unthreaded_names() == frozenset({"X"})
    with pytest.raises(SugarNotWritten, match="undecided module binding of `X`"):
        _returned(_function(tree))


def test_a_global_a_function_writes_is_undecided() -> None:
    tree = _source(
        "X = None\ndef put():\n    global X\n    X = 1\ndef f():\n    return X\n"
    )
    with pytest.raises(SugarNotWritten, match="undecided module binding of `X`"):
        _returned(_function(tree))


def test_only_names_a_nested_scope_reads_are_threaded() -> None:
    tree = _source("X = 1\nY = 2\ndef f():\n    return X\nY += 1\n")
    unit = _function(tree).unit
    assert unit.module_threaded_names() == frozenset({"X"})
    states = unit.module_binding_states()
    assert set(states.final) == {"X"}
    assert all(set(scope) <= {"X"} for row in states.at.values() for scope in row)


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


def test_a_class_statement_nested_in_a_module_if_reads_the_binding_it_saw() -> None:
    tree = _source("x = 1\nx += 1\nif x:\n    class C:\n        y = x\nx += 1\n")
    first, second = _module_evaluations(tree)
    definition = next(node for node in tree.nodes() if isinstance(node, ClassDef))
    (field,) = definition.sugar().fields
    assert isinstance(field.value_sugar, EvaluationRefSugar)
    assert field.value_sugar.evaluation == first
    assert field.value_sugar.evaluation != second


# -- a call the module body runs reads the binding at that call (item 1) ------


CALLED_DURING_IMPORT = "x = 1\nx += 1\ndef f():\n    return x\ny = f()\nx += 1\n"


def test_a_call_in_the_module_body_reads_the_binding_at_that_call() -> None:
    tree = _source(CALLED_DURING_IMPORT)
    first, second = _module_evaluations(tree)
    (call,) = _calls(tree)
    read = _returned_at(call, _function(tree))
    assert isinstance(read, EvaluationRef)
    assert read.evaluation == first
    # Called from outside the module's execution, the same body reads the
    # module's final binding.
    after_import = _returned(_function(tree))
    assert isinstance(after_import, EvaluationRef)
    assert after_import.evaluation == second


def test_the_call_constructs_its_callee_frame_at_its_site() -> None:
    tree = _source(CALLED_DURING_IMPORT)
    first, _second = _module_evaluations(tree)
    (call,) = _calls(tree)
    frame = call.sugar().source_call_frame
    assert frame is not None
    assert frame.module_execution_site == call.unit.module_execution_site(call)
    returned = frame.body.statements[-1]
    assert isinstance(returned, ReturnSugar)
    assert isinstance(returned.value, EvaluationRefSugar)
    assert returned.value.evaluation == first


def test_a_call_reached_from_a_module_call_reads_the_binding_there() -> None:
    tree = _source(
        "x = 1\nx += 1\ndef f():\n    return x\n"
        "def g():\n    return f()\ny = g()\nx += 1\n"
    )
    first, _second = _module_evaluations(tree)
    (inner,) = _calls(tree, "f")
    # A call in a function body is not one the module body runs: it is
    # constructed at the site it was reached from.
    assert inner.unit.module_execution_site(inner) is None
    (outer,) = _calls(tree, "g")
    read = _returned_at(outer, _function(tree, "f"))
    assert isinstance(read, EvaluationRef)
    assert read.evaluation == first


def test_a_call_in_a_class_body_reads_the_binding_at_its_class_statement() -> None:
    tree = _source(
        "x = 1\nx += 1\ndef f():\n    return x\nclass C:\n    y = f()\nx += 1\n"
    )
    first, _second = _module_evaluations(tree)
    (call,) = _calls(tree)
    site = call.unit.module_execution_site(call)
    assert isinstance(site.chain[-1], ClassDef)
    read = _returned_at(call, _function(tree))
    assert isinstance(read, EvaluationRef)
    assert read.evaluation == first


def test_a_walrus_in_the_calling_statement_leaves_the_binding_undecided() -> None:
    tree = _source(
        "x = 1\nx += 1\ndef f():\n    return x\ny = [(x := 5), f()]\nx += 1\n"
    )
    (call,) = _calls(tree)
    with pytest.raises(SugarNotWritten, match="undecided module binding of `x`"):
        _returned_at(call, _function(tree))


# -- a reader reached while the module is threaded (item 2) -------------------


def test_a_reader_reached_while_the_module_is_threaded_reads_the_binding_there(
    monkeypatch,
) -> None:
    source = (
        "x = 1\nx += 1\ndef f():\n    return x\ny = f()\n"
        "def probe():\n    pass\nz = f()\nx += 1\n"
    )
    first, second = _module_evaluations(_source(source))
    tree = _source(source)
    reached, unreached = _calls(tree)
    unit = reached.unit
    sites = (
        unit.module_execution_site(reached),
        unit.module_execution_site(unreached),
        None,
    )
    seen = []
    original = FunctionDef.substitute

    def substitute(self, scope):
        # ``def probe`` is threaded after ``y = f()`` and before ``z = f()``.
        if self.name == "probe" and not seen:
            seen.append(
                tuple(unit.module_bindings_at(site, {"x"})["x"] for site in sites)
            )
        return original(self, scope)

    monkeypatch.setattr(FunctionDef, "substitute", substitute)
    unit.module_binding_states()
    ((at_reached, at_unreached, with_no_site),) = seen
    assert isinstance(at_reached, EvaluationRef)
    assert at_reached.evaluation == first
    # Never the name read: a point the threading has not reached, and the
    # final binding before the threading is done, are undecided.
    assert at_unreached is UNDECIDED_MODULE_BINDING
    assert with_no_site is UNDECIDED_MODULE_BINDING
    final = unit.module_bindings_at(None, {"x"})["x"]
    assert isinstance(final, EvaluationRef)
    assert final.evaluation == second


# -- walrus and comprehension-member bindings (item 3) ------------------------


def test_a_global_last_written_by_a_walrus_reads_its_evaluation() -> None:
    tree = _source("x = 1\n(x := 5)\ndef f():\n    return x\n")
    read = _returned(_function(tree))
    assert isinstance(read, EvaluationRef)
    assert getattr(read, "walrus", False)


def test_a_call_after_a_walrus_reads_the_walrus_evaluation() -> None:
    tree = _source("x = 1\n(x := 5)\ndef f():\n    return x\ny = f()\nx += 1\n")
    (call,) = _calls(tree)
    read = _returned_at(call, _function(tree))
    assert isinstance(read, EvaluationRef)
    assert getattr(read, "walrus", False)
    after_import = _returned(_function(tree))
    assert isinstance(after_import, EvaluationRef)
    assert not getattr(after_import, "walrus", False)


def test_a_comprehension_member_is_undecided_outside_its_comprehension() -> None:
    tree = _source("ys = [v for v in (1, 2)]\n")
    comprehension = next(node for node in tree.nodes() if isinstance(node, ListComp))
    (member,) = comprehension._target_references(
        0, comprehension.generators[0]
    ).values()
    assert getattr(member, "member", False)
    assert _module_reference_state(member) is UNDECIDED_MODULE_BINDING


# -- an implicit call the module body runs reads the binding at it ------------

# The dunder (as the class body spells it), the expression that calls it
# implicitly, the node kind that expression is, and the method's name.
IMPLICIT_CALLS = {
    "__add__": (
        "def __add__(self, o):\n        return x\n",
        "C() + 0",
        BinOp,
        "__add__",
    ),
    "__getitem__": (
        "def __getitem__(self, i):\n        return x\n",
        "C()[0]",
        Subscript,
        "__getitem__",
    ),
    "property": (
        "@property\n    def p(self):\n        return x\n",
        "C().p",
        Attribute,
        "p",
    ),
}


def _implicit_call_source(name: str) -> str:
    """``x = 1; class C: <dunder returning x>; y = <implicit call>; x = 2``:
    called at ``y = ...``, the dunder reads ``x = 1`` (``y == 1``)."""
    method, expression, _kind, _name = IMPLICIT_CALLS[name]
    return f"x = 1\nclass C:\n    {method}y = {expression}\nx = 2\n"


def _only(tree: SourceFile, kind: type):
    (node,) = [node for node in tree.nodes() if isinstance(node, kind)]
    return node


@dataclass(frozen=True)
class _SiteProbe(Sugar):
    """Records the module execution site its reduction runs under."""

    seen: list

    def desugar(self, ctx=None):
        del ctx
        self.seen.append(current_module_execution_site())
        return ExitSet.completed(TermValue(0))

    @classmethod
    def witnesses(cls):
        return ()


@pytest.mark.parametrize("name", sorted(IMPLICIT_CALLS))
def test_an_implicit_call_reads_the_binding_at_its_site(name: str) -> None:
    _method, _expression, kind, method_name = IMPLICIT_CALLS[name]
    tree = _source(_implicit_call_source(name))
    first, second = _assignment_keys(tree, "x")
    node = _only(tree, kind)
    site = node.unit.module_execution_site(node)
    assert site is not None
    function = _function(tree, method_name)
    read = construct_at_module_execution_site(site, lambda: _returned(function))
    assert isinstance(read, EvaluationRef)
    assert read.evaluation == first
    # Called after import, the same body reads the module's final binding.
    after_import = _returned(function)
    assert isinstance(after_import, EvaluationRef)
    assert after_import.evaluation == second


@pytest.mark.parametrize("name", sorted(IMPLICIT_CALLS))
def test_the_implicit_call_records_its_site_on_its_sugar(name: str) -> None:
    _method, _expression, kind, _name = IMPLICIT_CALLS[name]
    tree = _source(_implicit_call_source(name))
    node = _only(tree, kind)
    site = node.unit.module_execution_site(node)
    assert site is not None
    assert stamped_module_execution_site(node.sugar()) == site


@pytest.mark.parametrize("name", sorted(IMPLICIT_CALLS))
def test_the_dunder_frame_is_read_again_at_the_implicit_call(name: str) -> None:
    _method, _expression, kind, method_name = IMPLICIT_CALLS[name]
    tree = _source(_implicit_call_source(name))
    first, second = _assignment_keys(tree, "x")
    node = _only(tree, kind)
    site = node.unit.module_execution_site(node)
    # The method frame the class statement constructs: no call site.
    frame = _function(tree, method_name).source_visible_call_frame()
    assert frame.module_execution_site is None
    assert frame_at_current_module_execution_site(frame) is frame
    at_call = construct_at_module_execution_site(
        site, lambda: frame_at_current_module_execution_site(frame)
    )
    assert at_call.module_execution_site == site
    returned = at_call.body.statements[-1]
    assert isinstance(returned, ReturnSugar)
    assert isinstance(returned.value, EvaluationRefSugar)
    assert returned.value.evaluation == first
    assert returned.value.evaluation != second


def test_a_stamped_sugar_reduces_at_its_site() -> None:
    tree = _source(_implicit_call_source("__add__"))
    node = _only(tree, BinOp)
    seen: list = []
    _at_module_execution_site(node, _SiteProbe(seen)).desugar(None)
    _SiteProbe(seen).desugar(None)
    assert seen == [node.unit.module_execution_site(node), None]


def test_a_def_statement_is_stamped_with_no_site() -> None:
    # Its body runs when it is called, at its caller's site.
    tree = _source("x = 1\nx += 1\nif x:\n    def f():\n        return x\n")
    function = _function(tree)
    assert function.unit.module_execution_site(function) is not None
    stamped = _at_module_execution_site(function, _SiteProbe([]))
    assert stamped_module_execution_site(stamped) is None


def test_a_for_statements_own_call_runs_after_its_body() -> None:
    tree = _source(
        "x = 1\nx += 1\ndef g():\n    return (1, 2)\nfor v in g():\n    x += 1\n"
    )
    first = _module_evaluations(tree)[0]
    loop = _only(tree, For)
    unit = loop.unit
    # ``__next__`` runs after the body, which rebinds ``x``.
    own = unit.module_execution_site(loop)
    assert own.after_body
    assert unit.module_bindings_at(own, {"x"})["x"] is UNDECIDED_MODULE_BINDING
    # The iterable's call runs once, before the body.
    (call,) = _calls(tree, "g")
    at_call = unit.module_execution_site(call)
    assert not at_call.after_body
    read = unit.module_bindings_at(at_call, {"x"})["x"]
    assert isinstance(read, EvaluationRef)
    assert read.evaluation == first


_MODULE_WITH = (
    "x = 1\n"
    "class M:\n"
    "    def __enter__(self):\n"
    "        return x\n"
    "    def __exit__(self, t, v, tb):\n"
    "        return False\n"
    "with M() as y:\n"
    "    pass\n"
    "x = 2\n"
)


def test_a_module_with_enters_reading_the_binding_at_the_with() -> None:
    # ``x = 1; class M: def __enter__(self): return x; with M() as y: ...;
    # x = 2``: the with's ``__enter__`` runs where the with stands, so ``y``
    # is the ``x = 1`` binding.  The protocol binds ``__enter__`` through
    # ``bind_method_call`` at the with's site (``_call_protocol_method``),
    # which reads the method frame again there.
    tree = _source(_MODULE_WITH)
    first, second = _assignment_keys(tree, "x")
    node = _only(tree, With)
    site = node.unit.module_execution_site(node)
    assert site is not None
    function = _function(tree, "__enter__")
    read = construct_at_module_execution_site(site, lambda: _returned(function))
    assert isinstance(read, EvaluationRef)
    assert read.evaluation == first
    # Called after import, the same body reads the module's final binding.
    after_import = _returned(function)
    assert isinstance(after_import, EvaluationRef)
    assert after_import.evaluation == second
    # The method frame the class statement constructs is read again at the
    # with, as ``bind_method_call`` reads it.
    frame = function.source_visible_call_frame()
    at_with = construct_at_module_execution_site(
        site, lambda: frame_at_current_module_execution_site(frame)
    )
    assert at_with.module_execution_site == site
    returned = at_with.body.statements[-1]
    assert isinstance(returned, ReturnSugar)
    assert isinstance(returned.value, EvaluationRefSugar)
    assert returned.value.evaluation == first


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
