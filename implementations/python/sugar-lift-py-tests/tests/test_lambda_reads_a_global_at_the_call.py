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
3. A lambda a walrus lets escape a comprehension, from the element or a
   condition (``[(g := lambda: x) for x in xs if g()]; g()``), reads the
   comprehension's cell at each call: the member current at a call inside
   the evaluation that made it (#7944's in-place rule), the final member at
   a call after the comprehension (``final_member_coordinate``), refused by
   name where the call is placed in neither.  Never the member current where
   the lambda was made.
4. A lambda a walrus lets escape a generator expression (``list((g :=
   lambda: x) for x in xs)``) reads the cell the same way, a run being a
   consumption of the generator: the member current at a call inside a run;
   the final member at a call after it only where the generator is consumed
   whole in place (``GeneratorExp._consumed_whole_in_place``); refused by
   name everywhere else (a stored generator, ``any``, ``set``, a shadowed
   ``list``).
5. A lambda a generator expression yields, with no walrus -- the element
   itself (``list(lambda: x for x in xs)``) or a lambda an inner
   comprehension in the element stores (``([lambda: x for _ in ys] for x in
   xs)``) -- escapes the generator the same way and is read by the same rule
   (``GeneratorExp.substitute``, ``_escaping_at_the_call``): ``fs =
   list(lambda: x for x in [1, 2]); fs[0]()`` is 2, and a stored
   generator's yielded lambda called after the run is refused by name.
6. Every lambda in a comprehension or generator expression is read so,
   whatever route it takes out: returned by a call in the element (``(g(lambda:
   x) for x in xs)``), held by an inner generator (``((y for y in [lambda:
   x]) for x in xs)``), stored by a call (``[keep(lambda: x) for x in xs]``),
   called in place (``sorted(vs, key=lambda v: v + x)``).  The escape route
   is never guessed from the lambda's shape (``_escaping_at_the_call``); the
   call decides the member.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.floor.call_site_value import _ctx_with_curried_args
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.comprehension_sugar import ComprehensionSugar
from sugar_lift_py_tests.sugar.computed_call_sugar import ComputedCallSugar
from sugar_lift_py_tests.sugar.evaluation_ref_sugar import EvaluationRefSugar
from sugar_lift_py_tests.sugar.lambda_sugar import LambdaSugar
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
    GeneratorExp,
    Lambda,
    ListComp,
    Name,
    NamedExpr,
    _function_holding,
    comprehension_evaluation_coordinate,
    construct_at_module_execution_site,
    final_member_coordinate,
    lambda_evaluation_coordinate,
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


ESCAPES_FROM_THE_ELEMENT = (
    "def f(xs):\n    ys = [(g := lambda: x) for x in xs]\n    return g()\n"
)
CALLED_INSIDE_AND_AFTER = (
    "def f(xs, g):\n    ys = [(g := lambda: x) for x in xs if g()]\n    return g()\n"
)
ESCAPES_FROM_A_CONDITION = (
    "def f(xs):\n    ys = [x for x in xs if (g := lambda: x)]\n    return g()\n"
)


def _assert_reads_the_cell_at_the_call(lam: Lambda, coordinate: str) -> None:
    """The body reads the cell at the call: both the member coordinate and
    its final one, never the member coordinate alone (the member current
    where the lambda was made)."""
    reads = [node for node in lam.body.walk() if isinstance(node, EvaluationRef)]
    assert [read.evaluation for read in reads] == [final_member_coordinate(coordinate)]
    assert all(read.cell is True for read in reads)
    assert [read.current for read in reads] == [coordinate]
    # The lambda value carries the final member and the evaluation it was
    # made in.
    assert lam._closure_coordinates() == (final_member_coordinate(coordinate),)
    assert lam._evaluation_coordinates() == (
        (
            lambda_evaluation_coordinate(coordinate),
            comprehension_evaluation_coordinate(coordinate),
        ),
    )


def test_a_walrus_escaping_lambda_reads_the_cell_at_the_call() -> None:
    comp = _comprehension(ESCAPES_FROM_THE_ELEMENT)
    coordinate = ListComp._generator_binding_coordinate(comp, 0, comp.generators[0])
    walrus = comp.elt
    assert isinstance(walrus, NamedExpr)
    lam = walrus.value
    assert isinstance(lam, Lambda)
    _assert_reads_the_cell_at_the_call(lam, coordinate)


def test_a_lambda_the_comprehension_calls_reads_the_cell_at_the_call() -> None:
    # ``g()`` in the condition runs while the comprehension runs, and the
    # ``g()`` after it runs once it is done: one body serves both, so it is
    # neither the creation-time member nor the final one alone.
    comp = _comprehension(CALLED_INSIDE_AND_AFTER)
    coordinate = ListComp._generator_binding_coordinate(comp, 0, comp.generators[0])
    (lam,) = _lambdas([comp.elt])
    _assert_reads_the_cell_at_the_call(lam, coordinate)


def test_a_walrus_in_a_condition_lets_its_lambda_escape() -> None:
    comp = _comprehension(ESCAPES_FROM_A_CONDITION)
    coordinate = ListComp._generator_binding_coordinate(comp, 0, comp.generators[0])
    (condition,) = comp.generators[0].ifs
    (lam,) = _lambdas([condition])
    _assert_reads_the_cell_at_the_call(lam, coordinate)


CALLED_IN_PLACE = "def f(xs):\n    ys = [(lambda: x)() for x in xs]\n    return ys\n"
SORTED_KEY_IN_PLACE = (
    "def f(xs, vs):\n    ys = [sorted(vs, key=lambda v: v + x) for x in xs]\n"
    "    return ys\n"
)


@pytest.mark.parametrize("source", [CALLED_IN_PLACE, SORTED_KEY_IN_PLACE])
def test_a_lambda_called_in_place_reads_the_cell_at_the_call(source: str) -> None:
    # Its shape is not asked: the body reads the cell at the call, as every
    # lambda in a comprehension does (``_escaping_at_the_call``).
    comp = _comprehension(source)
    coordinate = ListComp._generator_binding_coordinate(comp, 0, comp.generators[0])
    (lam,) = _lambdas([comp.elt])
    _assert_reads_the_cell_at_the_call(lam, coordinate)


@pytest.mark.parametrize("source", [CALLED_IN_PLACE, SORTED_KEY_IN_PLACE])
def test_a_lambda_called_in_place_reads_the_member_current_at_the_call(
    source: str,
) -> None:
    # Called where it is made (``(lambda: x)()``, ``sorted``'s ``key``): the
    # call runs inside the evaluation that made the lambda, so the cell holds
    # the member current at the call -- never the final member.
    comp = _comprehension(source)
    sugar = comp.sugar()
    assert isinstance(sugar, ComprehensionSugar)
    generator = sugar.generators[0]
    (lam,) = _lambdas([comp.elt])
    (read,) = [node for node in lam.body.walk() if isinstance(node, EvaluationRef)]
    evaluation = _evaluation(sugar, generator, TermValue(3))
    made = sugar._member_ctx(generator, TermValue(1), evaluation)
    callable_ = lam.sugar().desugar(made).completed_value()
    called = _called(callable_, made)
    assert read.sugar().desugar(called) == ExitSet.completed(TermValue(1))


# -- 3. the call places the read ----------------------------------------------


def _escaping(source: str = ESCAPES_FROM_THE_ELEMENT):
    """The comprehension's sugar, its one generator, and the escaping
    lambda's sugar."""
    comp = _comprehension(source)
    sugar = comp.sugar()
    assert isinstance(sugar, ComprehensionSugar)
    (lam,) = _lambdas([comp.elt, *comp.generators[0].ifs])
    lam_sugar = lam.sugar()
    assert isinstance(lam_sugar, LambdaSugar)
    return sugar, sugar.generators[0], lam_sugar


def _evaluation(sugar, generator, final):
    """A context inside one evaluation of the comprehension, with ``final``
    its final member."""
    ctx = sugar._evaluation_ctx(ReduceContext.root(owner="walrus-escape"))
    return sugar._final_member_ctx(generator, final, ctx)


def _called(callable_, ctx):
    """``ctx`` as the lambda's call binds it: the closure the value carries."""
    return _ctx_with_curried_args(ctx, (), (), (), callable_.closure)


def test_every_evaluation_of_the_comprehension_is_its_own() -> None:
    sugar, generator, _lam = _escaping()
    coordinate = comprehension_evaluation_coordinate(generator.binding_coordinate_cid)
    root = ReduceContext.root(owner="walrus-escape")
    first = sugar._evaluation_ctx(root).temporal.value_if_bound(coordinate)
    second = sugar._evaluation_ctx(root).temporal.value_if_bound(coordinate)
    assert first is not None
    assert second is not None
    assert first is not second
    assert root.temporal.value_if_bound(coordinate) is None


def test_the_lambda_carries_the_final_member_and_its_evaluation() -> None:
    sugar, generator, lam = _escaping()
    member = generator.binding_coordinate_cid
    evaluation = _evaluation(sugar, generator, TermValue(3))
    made_in = evaluation.temporal.value_if_bound(
        comprehension_evaluation_coordinate(member)
    )
    made = sugar._member_ctx(generator, TermValue(1), evaluation)
    callable_ = lam.desugar(made).completed_value()
    assert callable_.closure[0] == (final_member_coordinate(member), TermValue(3))
    carried, value = callable_.closure[1]
    assert carried == lambda_evaluation_coordinate(member)
    assert value is made_in


def test_a_call_inside_reads_the_member_current_at_the_call() -> None:
    sugar, generator, lam = _escaping()
    evaluation = _evaluation(sugar, generator, TermValue(3))
    made = sugar._member_ctx(generator, TermValue(1), evaluation)
    callable_ = lam.desugar(made).completed_value()
    # Called by the member that made it: that member.
    read = lam.body.desugar(_called(callable_, made))
    assert read == ExitSet.completed(TermValue(1))
    # Called by a later member of the same evaluation (``if g()``): the
    # member current at the call, never the one it was made under.
    later = sugar._member_ctx(generator, TermValue(2), evaluation)
    read = lam.body.desugar(_called(callable_, later))
    assert read == ExitSet.completed(TermValue(2))


def test_a_call_after_the_comprehension_reads_the_final_member() -> None:
    sugar, generator, lam = _escaping()
    evaluation = _evaluation(sugar, generator, TermValue(3))
    made = sugar._member_ctx(generator, TermValue(1), evaluation)
    callable_ = lam.desugar(made).completed_value()
    after = ReduceContext.root(owner="after-the-comprehension")
    read = lam.body.desugar(_called(callable_, after))
    assert read == ExitSet.completed(TermValue(3))


def test_a_call_inside_another_evaluation_is_refused_by_name() -> None:
    sugar, generator, lam = _escaping()
    first = _evaluation(sugar, generator, TermValue(3))
    made = sugar._member_ctx(generator, TermValue(1), first)
    callable_ = lam.desugar(made).completed_value()
    # The comprehension runs again (a loop, a second call of ``f``) and the
    # first evaluation's lambda is called inside it: neither that
    # evaluation's current member nor this one's.
    second = sugar._member_ctx(
        generator, TermValue(5), _evaluation(sugar, generator, TermValue(6))
    )
    with pytest.raises(SugarNotWritten, match="not made in"):
        lam.body.desugar(_called(callable_, second))


def test_an_unplaced_read_of_the_cell_is_refused_by_name() -> None:
    sugar, generator, lam = _escaping()
    # No evaluation runs and the lambda carries no final member.
    with pytest.raises(SugarNotWritten, match="no final member"):
        lam.body.desugar(ReduceContext.root(owner="unplaced"))
    # An evaluation runs, and the body is read with no lambda value around
    # it: no evaluation it was made in.
    inside = sugar._member_ctx(
        generator, TermValue(1), _evaluation(sugar, generator, TermValue(3))
    )
    with pytest.raises(SugarNotWritten, match="carries none"):
        lam.body.desugar(inside)


def test_a_condition_walrus_lambda_is_placed_by_its_call() -> None:
    sugar, generator, lam = _escaping(ESCAPES_FROM_A_CONDITION)
    evaluation = _evaluation(sugar, generator, TermValue(3))
    made = sugar._member_ctx(generator, TermValue(1), evaluation)
    callable_ = lam.desugar(made).completed_value()
    later = sugar._member_ctx(generator, TermValue(2), evaluation)
    read = lam.body.desugar(_called(callable_, later))
    assert read == ExitSet.completed(TermValue(2))
    after = ReduceContext.root(owner="after-the-comprehension")
    read = lam.body.desugar(_called(callable_, after))
    assert read == ExitSet.completed(TermValue(3))


# -- 4. a lambda escaping a generator expression through a walrus ------------


CONSUMED_IN_PLACE = (
    "def f(xs):\n    ys = list((g := lambda: x) for x in xs)\n    return ys[0]()\n"
)
STORED = (
    "def f(xs):\n"
    "    gen = ((g := lambda: x) for x in xs)\n"
    "    h = next(gen)\n"
    "    return h()\n"
)


def _generator(source: str) -> GeneratorExp:
    """The one generator expression of ``f``'s substituted body."""
    body = _function(_source(source)).substitute({}).body
    (gen,) = [
        node
        for statement in body
        for node in statement.walk()
        if isinstance(node, GeneratorExp)
    ]
    return gen


def _consumed(consumer: str) -> str:
    return (
        f"def f(xs):\n    ys = {consumer}((g := lambda: x) for x in xs)\n"
        "    return ys\n"
    )


def _escaping_generator(source: str):
    """The generator's sugar, its one generator, and the escaping lambda's
    sugar."""
    gen = _generator(source)
    sugar = gen.sugar()
    assert isinstance(sugar, ComprehensionSugar)
    assert sugar.kind == "py.generatorexp"
    (lam,) = _lambdas([gen.elt])
    lam_sugar = lam.sugar()
    assert isinstance(lam_sugar, LambdaSugar)
    return sugar, sugar.generators[0], lam_sugar


def test_a_generator_walrus_lambda_reads_the_cell_at_the_call() -> None:
    # Consumed in place or stored, the body never reads the member current
    # where the lambda was made.
    for source in (CONSUMED_IN_PLACE, STORED):
        gen = _generator(source)
        coordinate = ListComp._generator_binding_coordinate(
            gen, 0, gen.generators[0]
        )
        (lam,) = _lambdas([gen.elt])
        _assert_reads_the_cell_at_the_call(lam, coordinate)


def test_only_a_generator_consumed_whole_in_place_places_its_final_member() -> (
    None
):
    assert _generator(CONSUMED_IN_PLACE).sugar().final_member is True
    assert _generator(_consumed("tuple")).sugar().final_member is True
    assert _generator(_consumed("sorted")).sugar().final_member is True
    # Stored and consumed later, or in part.
    assert _generator(STORED).sugar().final_member is False
    # ``any`` stops at the first deciding member; ``set`` hashes each member
    # as it goes; ``iter`` keeps the generator.
    for consumer in ("any", "all", "set", "iter"):
        assert _generator(_consumed(consumer)).sugar().final_member is False
    # A ``list`` that is not the builtin.
    shadowed = (
        "def f(xs, list):\n    ys = list((g := lambda: x) for x in xs)\n"
        "    return ys\n"
    )
    assert _generator(shadowed).sugar().final_member is False


def test_a_generator_consumed_in_place_reads_the_member_at_each_call() -> None:
    sugar, generator, lam = _escaping_generator(CONSUMED_IN_PLACE)
    member = generator.binding_coordinate_cid
    evaluation = _evaluation(sugar, generator, TermValue(3))
    made = sugar._member_ctx(generator, TermValue(1), evaluation)
    callable_ = lam.desugar(made).completed_value()
    assert (final_member_coordinate(member), TermValue(3)) in callable_.closure
    # Called inside the run, by a later member: the member current at the
    # call, never the one it was made under.
    later = sugar._member_ctx(generator, TermValue(2), evaluation)
    read = lam.body.desugar(_called(callable_, later))
    assert read == ExitSet.completed(TermValue(2))
    # Called after ``list(...)`` drained it: the final member.
    after = ReduceContext.root(owner="after-the-generator")
    read = lam.body.desugar(_called(callable_, after))
    assert read == ExitSet.completed(TermValue(3))


def test_a_stored_generators_lambda_called_later_is_refused_by_name() -> None:
    sugar, generator, lam = _escaping_generator(STORED)
    member = generator.binding_coordinate_cid
    evaluation = _evaluation(sugar, generator, TermValue(3))
    made = sugar._member_ctx(generator, TermValue(1), evaluation)
    callable_ = lam.desugar(made).completed_value()
    # No final member is placed, so none is carried.
    assert all(
        carried != final_member_coordinate(member)
        for carried, _value in callable_.closure
    )
    # Inside a run of the generator: still the member current at the call.
    later = sugar._member_ctx(generator, TermValue(2), evaluation)
    read = lam.body.desugar(_called(callable_, later))
    assert read == ExitSet.completed(TermValue(2))
    # After it (``h = next(gen); h()``): how far it was consumed is not
    # decided here, and the read is refused by name, never the member
    # current where the lambda was made.
    after = ReduceContext.root(owner="after-the-generator")
    with pytest.raises(SugarNotWritten, match="not consumed whole in place"):
        lam.body.desugar(_called(callable_, after))


# -- 5. a lambda a generator expression yields, with no walrus ----------------


YIELDED_CONSUMED_IN_PLACE = (
    "def f():\n    fs = list(lambda: x for x in [1, 2])\n    return fs[0]()\n"
)
YIELDED_STORED = (
    "def f(xs):\n"
    "    gen = (lambda: x for x in xs)\n"
    "    h = next(gen)\n"
    "    return h()\n"
)
YIELDED_BY_AN_INNER_COMPREHENSION = (
    "def f(xs, ys):\n"
    "    gen = ([lambda: x for _ in ys] for x in xs)\n"
    "    h = next(gen)[0]\n"
    "    return h()\n"
)


def test_a_yielded_lambda_reads_the_cell_at_the_call() -> None:
    # Yielded directly or stored by an inner comprehension the generator
    # yields, consumed in place or stored: the body never reads the member
    # current where the lambda was made.
    for source in (
        YIELDED_CONSUMED_IN_PLACE,
        YIELDED_STORED,
        YIELDED_BY_AN_INNER_COMPREHENSION,
    ):
        gen = _generator(source)
        coordinate = ListComp._generator_binding_coordinate(
            gen, 0, gen.generators[0]
        )
        (lam,) = _lambdas([gen.elt])
        _assert_reads_the_cell_at_the_call(lam, coordinate)


def test_a_lambda_list_drains_from_a_generator_reads_the_final_member() -> None:
    # ``fs = list(lambda: x for x in [1, 2]); fs[0]()`` is 2: ``list`` drains
    # the generator before ``fs[0]`` is called, and the cell then holds the
    # final member, never the 1 the lambda was made under.
    assert _generator(YIELDED_CONSUMED_IN_PLACE).sugar().final_member is True
    sugar, generator, lam = _escaping_generator(YIELDED_CONSUMED_IN_PLACE)
    member = generator.binding_coordinate_cid
    evaluation = _evaluation(sugar, generator, TermValue(2))
    made = sugar._member_ctx(generator, TermValue(1), evaluation)
    callable_ = lam.desugar(made).completed_value()
    assert (final_member_coordinate(member), TermValue(2)) in callable_.closure
    after = ReduceContext.root(owner="after-the-generator")
    read = lam.body.desugar(_called(callable_, after))
    assert read == ExitSet.completed(TermValue(2))
    # Called inside the run (by the consumer before the next member): the
    # member current at the call.
    read = lam.body.desugar(_called(callable_, made))
    assert read == ExitSet.completed(TermValue(1))
    later = sugar._member_ctx(generator, TermValue(2), evaluation)
    read = lam.body.desugar(_called(callable_, later))
    assert read == ExitSet.completed(TermValue(2))


@pytest.mark.parametrize("source", [YIELDED_STORED, YIELDED_BY_AN_INNER_COMPREHENSION])
def test_a_stored_generators_yielded_lambda_called_later_is_refused(
    source: str,
) -> None:
    assert _generator(source).sugar().final_member is False
    sugar, generator, lam = _escaping_generator(source)
    member = generator.binding_coordinate_cid
    evaluation = _evaluation(sugar, generator, TermValue(3))
    made = sugar._member_ctx(generator, TermValue(1), evaluation)
    callable_ = lam.desugar(made).completed_value()
    # No final member is placed, so none is carried.
    assert all(
        carried != final_member_coordinate(member)
        for carried, _value in callable_.closure
    )
    # Inside a run of the generator: the member current at the call.
    later = sugar._member_ctx(generator, TermValue(2), evaluation)
    read = lam.body.desugar(_called(callable_, later))
    assert read == ExitSet.completed(TermValue(2))
    # After it (``h = next(gen); h()``): refused by name, never the member
    # current where the lambda was made.
    after = ReduceContext.root(owner="after-the-generator")
    with pytest.raises(SugarNotWritten, match="not consumed whole in place"):
        lam.body.desugar(_called(callable_, after))


# -- 6. every lambda, whatever route it escapes by ----------------------------


RETURNED_BY_A_CALL = (
    "def f(xs, g):\n"
    "    gen = (g(lambda: x) for x in xs)\n"
    "    h = next(gen)\n"
    "    return h()\n"
)
RETURNED_BY_A_CALL_CONSUMED_IN_PLACE = (
    "def f(xs, g):\n    fs = list(g(lambda: x) for x in xs)\n    return fs[0]()\n"
)
HELD_BY_AN_INNER_GENERATOR = (
    "def f(xs):\n"
    "    gen = ((y for y in [lambda: x]) for x in xs)\n"
    "    h = next(next(gen))\n"
    "    return h()\n"
)
STORED_BY_A_CALL = (
    "def f(xs, keep):\n    ys = [keep(lambda: x) for x in xs]\n    return ys\n"
)


def _outer_generator(source: str) -> GeneratorExp:
    """The generator expression of ``f``'s substituted body whose element is
    a generator expression."""
    body = _function(_source(source)).substitute({}).body
    (gen,) = [
        node
        for statement in body
        for node in statement.walk()
        if isinstance(node, GeneratorExp) and isinstance(node.elt, GeneratorExp)
    ]
    return gen


@pytest.mark.parametrize(
    "source", [RETURNED_BY_A_CALL, RETURNED_BY_A_CALL_CONSUMED_IN_PLACE]
)
def test_a_lambda_a_call_returns_reads_the_cell_at_the_call(source: str) -> None:
    gen = _generator(source)
    coordinate = ListComp._generator_binding_coordinate(gen, 0, gen.generators[0])
    (lam,) = _lambdas([gen.elt])
    _assert_reads_the_cell_at_the_call(lam, coordinate)


def test_a_lambda_an_inner_generator_holds_reads_the_outer_cell_at_the_call() -> (
    None
):
    gen = _outer_generator(HELD_BY_AN_INNER_GENERATOR)
    coordinate = ListComp._generator_binding_coordinate(gen, 0, gen.generators[0])
    (lam,) = _lambdas([gen.elt])
    _assert_reads_the_cell_at_the_call(lam, coordinate)


def test_a_lambda_a_call_stores_reads_the_cell_at_the_call() -> None:
    comp = _comprehension(STORED_BY_A_CALL)
    coordinate = ListComp._generator_binding_coordinate(comp, 0, comp.generators[0])
    (lam,) = _lambdas([comp.elt])
    _assert_reads_the_cell_at_the_call(lam, coordinate)


def test_a_returned_lambda_of_a_stored_generator_called_later_is_refused() -> None:
    # ``h = next(gen); h()``: how far ``gen`` was consumed at the call is not
    # decided here, so the read is refused by name -- never the member
    # current where the lambda was made.
    assert _generator(RETURNED_BY_A_CALL).sugar().final_member is False
    sugar, generator, lam = _escaping_generator(RETURNED_BY_A_CALL)
    evaluation = _evaluation(sugar, generator, TermValue(3))
    made = sugar._member_ctx(generator, TermValue(1), evaluation)
    callable_ = lam.desugar(made).completed_value()
    later = sugar._member_ctx(generator, TermValue(2), evaluation)
    read = lam.body.desugar(_called(callable_, later))
    assert read == ExitSet.completed(TermValue(2))
    after = ReduceContext.root(owner="after-the-generator")
    with pytest.raises(SugarNotWritten, match="not consumed whole in place"):
        lam.body.desugar(_called(callable_, after))


def test_a_returned_lambda_list_drains_reads_the_final_member() -> None:
    assert _generator(RETURNED_BY_A_CALL_CONSUMED_IN_PLACE).sugar().final_member
    sugar, generator, lam = _escaping_generator(RETURNED_BY_A_CALL_CONSUMED_IN_PLACE)
    evaluation = _evaluation(sugar, generator, TermValue(2))
    made = sugar._member_ctx(generator, TermValue(1), evaluation)
    callable_ = lam.desugar(made).completed_value()
    after = ReduceContext.root(owner="after-the-generator")
    read = lam.body.desugar(_called(callable_, after))
    assert read == ExitSet.completed(TermValue(2))


def test_a_lambda_an_inner_generator_holds_called_later_is_refused() -> None:
    gen = _outer_generator(HELD_BY_AN_INNER_GENERATOR)
    sugar = gen.sugar()
    assert isinstance(sugar, ComprehensionSugar)
    assert sugar.final_member is False
    generator = sugar.generators[0]
    (lam,) = _lambdas([gen.elt])
    lam_sugar = lam.sugar()
    assert isinstance(lam_sugar, LambdaSugar)
    evaluation = _evaluation(sugar, generator, TermValue(3))
    made = sugar._member_ctx(generator, TermValue(1), evaluation)
    callable_ = lam_sugar.desugar(made).completed_value()
    later = sugar._member_ctx(generator, TermValue(2), evaluation)
    read = lam_sugar.body.desugar(_called(callable_, later))
    assert read == ExitSet.completed(TermValue(2))
    after = ReduceContext.root(owner="after-the-generator")
    with pytest.raises(SugarNotWritten, match="not consumed whole in place"):
        lam_sugar.body.desugar(_called(callable_, after))


def test_a_lambda_a_call_stores_reads_the_final_member_after_the_run() -> None:
    # An eager comprehension runs whole where it is made: a call after it
    # reads the final member; a call inside it, the member current then.
    sugar, generator, lam = _escaping(STORED_BY_A_CALL)
    evaluation = _evaluation(sugar, generator, TermValue(3))
    made = sugar._member_ctx(generator, TermValue(1), evaluation)
    callable_ = lam.desugar(made).completed_value()
    later = sugar._member_ctx(generator, TermValue(2), evaluation)
    read = lam.body.desugar(_called(callable_, later))
    assert read == ExitSet.completed(TermValue(2))
    after = ReduceContext.root(owner="after-the-comprehension")
    read = lam.body.desugar(_called(callable_, after))
    assert read == ExitSet.completed(TermValue(3))
