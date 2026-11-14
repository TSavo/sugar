"""A lambda body runs when the lambda is called, so every free name it reads
is read at the call (#7757 item 7, residue of #7975).

1. A module global: a module-level lambda, or one in a class body or a
   ``def`` body, reads it the way a ``def``'s body does
   (``FunctionDef._module_global_references``): through the module's binding
   where the lambda is called (``Lambda._module_global_references``,
   ``_module_references_where_called``), the module's final binding when it
   is called after import, refused by name where the module body does not
   decide it.  The lambda's substitution holds the global out of its body
   (``Lambda._module_globals_read``, CPython's symtable of the lambda); the
   binding standing where the lambda was made is never read.
2. A lambda in a ``def``'s defaults or decorators stands in the function
   around that ``def`` (``_function_holding``): its body reads that
   function's locals through captured coordinates (#7975), and a global as
   in 1.
3. A lambda a walrus lets escape a comprehension
   (``[(g := lambda: x) for x in xs]``) reads the comprehension's cell, the
   final member (#7944, ``final_member_coordinate``), unless the
   comprehension also reads the walrus's name (it may be called while the
   comprehension runs).
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.sugar.computed_call_sugar import ComputedCallSugar
from sugar_lift_py_tests.sugar.evaluation_ref_sugar import EvaluationRefSugar
from sugar_lift_py_tests.sugar.return_sugar import ReturnSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import (
    AnnAssign,
    Assign,
    BindingCoordinateRef,
    Call,
    ClassDef,
    EvaluationRef,
    FunctionDef,
    Lambda,
    ListComp,
    Name,
    NamedExpr,
    _function_holding,
    construct_at_module_execution_site,
    final_member_coordinate,
)
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _source(source: str) -> SourceFile:
    return SourceFile(
        (source, "lambda_global.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _assignment_keys(tree: SourceFile, name: str) -> list[str]:
    """The key of ``name``'s projection of each module-level ``name = e``,
    in source order."""
    body = tree.root.substitute({}).body
    return [
        dict(node.target_evaluations())[name]
        for node in body
        if isinstance(node, (Assign, AnnAssign))
        and name in dict(node.target_evaluations())
    ]


def _assigned(body, name: str):
    """The value of the module-level (or block-level) ``name = e`` in
    ``body``."""
    return next(
        node.value
        for node in body
        if isinstance(node, Assign)
        and isinstance(node.targets[0], Name)
        and node.targets[0].id == name
    )


def _function(tree: SourceFile, name: str = "f") -> FunctionDef:
    return next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == name
    )


def _lambdas(nodes) -> list:
    return [
        node for root in nodes for node in root.walk() if isinstance(node, Lambda)
    ]


def _returned_at(lam: Lambda, site):
    """What the lambda's call frame, constructed at module execution
    ``site`` (None: called after import), returns."""
    frame = construct_at_module_execution_site(site, lam.source_visible_call_frame)
    returned = frame.body.statements[-1]
    assert isinstance(returned, ReturnSugar)
    return returned.value


def _site_of(tree: SourceFile, name: str):
    """The module execution site of the module-level ``name = e``'s call."""
    body = tree.root.substitute({}).body
    call = _assigned(body, name)
    assert isinstance(call, Call)
    site = call.unit.module_execution_site(call)
    assert site is not None
    return call, site


# -- 1. a module-level lambda reads a global where it is called --------------


def test_the_threading_records_a_global_only_a_lambda_reads() -> None:
    tree = _source("X = 1\nY = 2\ng = lambda: X\nX = 2\n")
    unit = tree.root.unit
    # The symtable scan covers lambda scopes: ``X`` is threaded, ``Y`` is not.
    assert unit.module_threaded_names() == frozenset({"X"})


def test_the_module_lambda_holds_the_global_out_of_its_body() -> None:
    tree = _source("X = 1\ng = lambda: X\nX = 2\n")
    lam = _assigned(tree.root.substitute({}).body, "g")
    assert isinstance(lam, Lambda)
    # Not the binding of ``X = 1`` standing where the lambda was made.
    assert isinstance(lam.body, Name)
    assert lam._module_globals_read() == frozenset({"X"})


def test_a_module_lambda_called_after_import_reads_the_final_binding() -> None:
    tree = _source("X = 1\ng = lambda: X\nX = 2\n")
    first, second = _assignment_keys(tree, "X")
    lam = _assigned(tree.root.substitute({}).body, "g")
    read = _returned_at(lam, None)
    assert isinstance(read, EvaluationRefSugar)
    assert read.evaluation == second
    assert read.evaluation != first


def test_a_module_lambda_called_after_a_rebind_reads_the_rebind() -> None:
    tree = _source("X = 1\ng = lambda: X\nX = 2\ny = g()\nX = 3\n")
    first, second, third = _assignment_keys(tree, "X")
    call, site = _site_of(tree, "y")
    lam = _assigned(tree.root.substitute({}).body, "g")
    read = _returned_at(lam, site)
    assert isinstance(read, EvaluationRefSugar)
    assert read.evaluation == second
    assert read.evaluation not in (first, third)
    # The call constructs the lambda's frame at its own site.
    sugar = call.sugar()
    assert isinstance(sugar, ComputedCallSugar)
    assert sugar.source_call_frame is not None
    assert sugar.source_call_frame.module_execution_site == site


def test_a_module_lambda_called_before_a_rebind_reads_the_first_binding() -> None:
    tree = _source("X = 1\ng = lambda: X\ny = g()\nX = 2\n")
    first, second = _assignment_keys(tree, "X")
    _call, site = _site_of(tree, "y")
    lam = _assigned(tree.root.substitute({}).body, "g")
    read = _returned_at(lam, site)
    assert isinstance(read, EvaluationRefSugar)
    assert read.evaluation == first
    assert read.evaluation != second


def test_a_global_unbound_at_the_lambda_call_is_undecided() -> None:
    tree = _source("g = lambda: X\ny = g()\nX = 1\n")
    _call, site = _site_of(tree, "y")
    lam = _assigned(tree.root.substitute({}).body, "g")
    with pytest.raises(
        SugarNotWritten, match="undecided module binding of `X` where `lambda`"
    ):
        _returned_at(lam, site)


def test_a_formal_of_the_globals_name_is_not_the_global() -> None:
    tree = _source("X = 1\ng = lambda X: X\nh = lambda: X\nX = 2\n")
    body = tree.root.substitute({}).body
    assert _assigned(body, "g")._module_globals_read() == frozenset()
    assert _assigned(body, "h")._module_globals_read() == frozenset({"X"})


# -- 1. a lambda in a class body or a def body reads a global at its call ----


def test_a_class_body_lambda_reads_the_global_where_it_is_called() -> None:
    tree = _source("X = 1\nclass C:\n    f = lambda self: X\nX = 2\n")
    first, second = _assignment_keys(tree, "X")
    (lam,) = _lambdas(tree.root.substitute({}).body)
    assert isinstance(lam.body, Name)
    read = _returned_at(lam, None)
    assert isinstance(read, EvaluationRefSugar)
    # Not the binding the class statement saw.
    assert read.evaluation == second
    assert read.evaluation != first


def test_the_class_statement_does_not_read_its_lambdas_globals() -> None:
    # ``X`` is unbound when the class statement runs; only the lambda reads
    # it, and only when it is called.
    tree = _source("class C:\n    f = lambda self: X\nX = 1\n")
    definition = next(node for node in tree.nodes() if isinstance(node, ClassDef))
    assert definition._module_name_references() == {}


def test_a_lambda_in_a_def_reads_the_global_where_it_is_called() -> None:
    tree = _source(
        "X = 1\ndef f():\n    g = lambda: X\n    return g()\ny = f()\nX = 2\n"
    )
    first, second = _assignment_keys(tree, "X")
    _call, site = _site_of(tree, "y")
    lam = _assigned(_function(tree).substitute({}).body, "g")
    assert isinstance(lam, Lambda)
    assert isinstance(lam.body, Name)
    at_call = _returned_at(lam, site)
    assert isinstance(at_call, EvaluationRefSugar)
    assert at_call.evaluation == first
    after_import = _returned_at(lam, None)
    assert isinstance(after_import, EvaluationRefSugar)
    assert after_import.evaluation == second


# -- 2. a lambda in a def's defaults or decorators ---------------------------


DEFAULT_IN_NESTED_DEF = (
    "def g():\n"
    "    x = 1\n"
    "    def f(a=lambda: x):\n"
    "        return a\n"
    "    x = 2\n"
    "    return f\n"
)
DECORATOR_IN_NESTED_DEF = (
    "def g():\n"
    "    x = 1\n"
    "    @(lambda fn: (fn, x))\n"
    "    def f():\n"
    "        return 0\n"
    "    x = 2\n"
    "    return f\n"
)


@pytest.mark.parametrize("source", [DEFAULT_IN_NESTED_DEF, DECORATOR_IN_NESTED_DEF])
def test_a_signature_lambda_stands_in_the_function_around_the_def(
    source: str,
) -> None:
    tree = _source(source)
    (lam,) = _lambdas([_function(tree, "g")])
    holder = _function_holding(lam)
    assert isinstance(holder, FunctionDef)
    assert holder.name == "g"


@pytest.mark.parametrize("source", [DEFAULT_IN_NESTED_DEF, DECORATOR_IN_NESTED_DEF])
def test_a_signature_lambda_reads_the_enclosing_cell_through_a_coordinate(
    source: str,
) -> None:
    tree = _source(source)
    (lam,) = _lambdas(_function(tree, "g").substitute({}).body)
    names, coordinates = lam._captured_bindings()
    assert names == ("x",)
    # Never the binding of ``x = 1`` standing where the ``def`` ran.
    reads = [
        node
        for node in lam.body.walk()
        if isinstance(node, (BindingCoordinateRef, EvaluationRef))
    ]
    assert reads
    assert all(isinstance(node, BindingCoordinateRef) for node in reads)
    assert {node.coordinate.cid for node in reads} == {coordinates[0].cid}
    frame = lam.source_visible_call_frame()
    assert frame.captured_names == ("x",)


def test_a_module_def_default_lambda_reads_the_global_at_its_call() -> None:
    tree = _source("X = 1\ndef f(a=lambda: X):\n    return a\nX = 2\n")
    first, second = _assignment_keys(tree, "X")
    (lam,) = _lambdas([_function(tree)])
    assert _function_holding(lam) is None
    substituted = lam.substitute({})
    assert substituted._captured_bindings() == ((), ())
    assert isinstance(substituted.body, Name)
    read = _returned_at(substituted, None)
    assert isinstance(read, EvaluationRefSugar)
    assert read.evaluation == second
    assert read.evaluation != first


# -- 3. a lambda escaping a comprehension through a walrus --------------------


def _comprehension(source: str) -> ListComp:
    body = _function(_source(source)).substitute({}).body
    comp = _assigned(body, "ys")
    assert isinstance(comp, ListComp)
    return comp


def test_a_walrus_escaping_lambda_reads_the_final_member() -> None:
    comp = _comprehension(
        "def f(xs):\n    ys = [(g := lambda: x) for x in xs]\n    return g()\n"
    )
    coordinate = ListComp._generator_binding_coordinate(comp, 0, comp.generators[0])
    walrus = comp.elt
    assert isinstance(walrus, NamedExpr)
    lam = walrus.value
    assert isinstance(lam, Lambda)
    reads = [node for node in lam.body.walk() if isinstance(node, EvaluationRef)]
    assert [read.evaluation for read in reads] == [final_member_coordinate(coordinate)]
    assert all(read.cell is True for read in reads)
    # The lambda value carries the final member it reads.
    assert lam._closure_coordinates() == (final_member_coordinate(coordinate),)


def test_a_walrus_lambda_the_comprehension_calls_reads_the_current_member() -> None:
    comp = _comprehension(
        "def f(xs):\n    ys = [((g := lambda: x), g()) for x in xs]\n    return ys\n"
    )
    coordinate = ListComp._generator_binding_coordinate(comp, 0, comp.generators[0])
    (lam,) = _lambdas([comp.elt])
    # ``g()`` runs while the comprehension runs: not the final member.
    assert isinstance(lam.body, EvaluationRef)
    assert lam.body.evaluation == coordinate
    assert getattr(lam.body, "cell", False) is not True
