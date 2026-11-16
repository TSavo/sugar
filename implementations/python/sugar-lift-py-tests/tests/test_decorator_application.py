"""A decorated ``def``/``class`` binds ``d1(d2(<definition>))`` (#7757).

The decorator application is one door (``DecoratedDefinitionRef``,
``DecoratorApplicationSugar``): the statement applies its decorators once and
binds the result under its evaluation key, a read or call of the name (``*``
and ``**`` calls among them) reads that key and calls the result, and the
definition's own body is never run in its place.  A ``def`` statement's body
runs only at a call; a method's implicit first argument is the one its
lookup binds.  A source decorator is applied through the one call routine; a
builtin one through the one builtin door with its real semantics or a refusal
by name; an imported one is the ``undecided`` member under its target symbol.

Before this, a call of a decorated module function seated the function's own
frame (``SourceUnit.source_function_definition_for_call`` answered the
decorated definition), so ``@d def f`` ran ``f``'s plain body: a wrong value.
"""

from __future__ import annotations

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.nodes import (
    Call,
    ClassDef,
    DecoratedDefinitionRef,
    FunctionDef,
    Name,
    _module_reference_state,
)
from sugar_source_tree.tree import SourceFile

from frame_fresh import FRAME_FRESH


def _tree(source: str, context=None) -> SourceFile:
    return SourceFile(
        (source, "test_decorator_application.py", blake3_512_of(source.encode())),
        construction_context=(
            context or TreeConstructionContextV1.for_test_without_workspace()
        ),
    )


def _test_function_outcome(source: str):
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    tree = _tree(source)
    (function,) = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name.startswith("test_")
    )
    return function_universe_outcome(function)


def _raises(outcome, exception: str) -> list:
    from sugar_lift_py_tests.outcome import Halted

    return [
        face
        for face in getattr(outcome, "exits", ())
        if isinstance(face, Halted)
        and getattr(face.effect, "exception_name", None) == exception
    ]


def _call_of(tree: SourceFile, name: str) -> Call:
    return next(
        node
        for node in tree.nodes()
        if isinstance(node, Call)
        and isinstance(node.func, Name)
        and node.func.id == name
    )


# ---------------------------------------------------------------------------
# A call of a same-file definition is its coordinate and edge (#7757 steps 5
# and 6, the owner's ruling of 2026-11-15, "Edge, join at prove"): the
# reduction never applies the callee's body, so what the body returns or
# raises is no face of the caller's reduction.  The call stands as
# ``call:<module>.<qualname>(<actuals>, py.default(...), ...)``, owed under
# the callee's join symbol, and prove joins it to the callee's contract.  A
# join symbol needs a workspace root (``FunctionDef.bridge_source_symbol``),
# so these read a file opened under one, by the one opener.
# ---------------------------------------------------------------------------


def _rooted_tree(tmp_path, source: str, module: str = "subject") -> SourceFile:
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction

    path = tmp_path / f"{module}.py"
    path.write_text(source)
    return open_source_file_for_construction(path, root=tmp_path)


def _rooted_outcome(tmp_path, source: str, module: str = "subject"):
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    tree = _rooted_tree(tmp_path, source, module)
    (function,) = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name.startswith("test_")
    )
    return function_universe_outcome(function)


def _owed_symbols(outcome) -> set:
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    return {item.symbol for item in owed_calls(outcome)}


def _owes_symbol_starting(outcome, prefix: str) -> bool:
    return any(
        isinstance(symbol, str) and symbol.startswith(prefix)
        for symbol in _owed_symbols(outcome)
    )


def _edge_term(outcome, target: str):
    """The one call term ``call:<target>...`` of the edges the reduction
    holds: each halt of such a call is named by the call it came from
    (``python:raised(<call term>, <occurrence>)``,
    ``UnknownCalleeCallV1.faces``).  ``target`` is the callee's join symbol
    without its ``python:`` namespace, or a prefix of it ending in ``@`` for
    a definition inside a function scope."""
    from sugar_lift_py_tests.outcome import Halted

    terms = set()
    for face in getattr(outcome, "exits", ()):
        if not isinstance(face, Halted):
            continue
        raised = getattr(face.effect, "raised_by_call", None)
        if raised is None:
            continue
        term = raised.args[0]
        name = getattr(term, "name", "")
        if name == f"call:{target}" or (
            target.endswith("@") and name.startswith(f"call:{target}")
        ):
            terms.add(term)
    assert len(terms) == 1, (target, terms, outcome)
    (term,) = terms
    return term


def _supplied_defaults(term) -> dict:
    """``{param: value term}`` of each ``py.default(param, value)`` the call
    term carries: the value the ``def`` statement bound for a formal the
    call omits."""
    return {
        arg.args[0].value: arg.args[1]
        for arg in term.args
        if getattr(arg, "name", None) == "py.default"
    }


def _positional(term) -> tuple:
    """The call term's operands that are no ``py.*`` input."""
    return tuple(
        arg
        for arg in term.args
        if not str(getattr(arg, "name", "")).startswith("py.")
    )


def _lambda_defaults(term) -> list:
    """The value term of each default a function value carries
    (``LambdaCallable.to_term``) anywhere under ``term``: a
    ``py.default(<param>, <value>)`` of a value stated as its join symbol
    (``python:function``), a ``python:lambda_default`` of one that names
    none."""
    found = []
    stack = [(term, False)]
    while stack:
        item, in_function = stack.pop()
        name = getattr(item, "name", None)
        if name == "python:lambda_default" or (in_function and name == "py.default"):
            found.append(item.args[1])
        inner = in_function or name == "python:function"
        stack.extend((arg, inner) for arg in getattr(item, "args", ()) or ())
    return found


# ---------------------------------------------------------------------------
# A call of a decorated function is never the function's own frame.
# ---------------------------------------------------------------------------

_DECORATED = """\
def replace(fn):
    return lambda n: n * 10


@replace
def scale(n):
    return n


def test_scale():
    value = scale(2)
    assert value == 20
"""


def test_a_decorated_function_is_not_its_call_frame() -> None:
    tree = _tree(_DECORATED)
    call = _call_of(tree, "scale")
    assert call.unit.source_function_definition_for_call(call) is None
    decorated = call.unit.decorated_definition_for_call(call)
    assert isinstance(decorated, FunctionDef)
    assert decorated.name == "scale"


def test_an_undecorated_function_keeps_its_call_frame() -> None:
    tree = _tree(_DECORATED.replace("@replace\n", ""))
    call = _call_of(tree, "scale")
    assert call.unit.source_function_definition_for_call(call) is not None
    assert call.unit.decorated_definition_for_call(call) is None


# ---------------------------------------------------------------------------
# A function-body read of an undecorated module ``def``'s name is the
# function its statement built (#7757).
# ---------------------------------------------------------------------------

_PASSED = """\
def g():
    return 1


def h(f):
    return f()


def test_f():
    return h(g)


alias = g
"""


def test_a_function_body_read_of_a_module_def_is_its_function_value() -> None:
    """``h(g)`` in a function reads ``g`` as the function its ``def``
    statement built: the one application with no decorator to apply and no
    default evaluated at the read, over the definition's own frame.  The
    read is never the bare name with no function value behind it.  A read
    the module body itself runs (``alias = g``) stands before or after the
    ``def`` statement in that run and is not answered by this reader."""
    from sugar_lift_py_tests.sugar.decorator_application_sugar import (
        DecoratorApplicationSugar,
    )

    tree = _tree(_PASSED)
    reads = {
        node.line_col_span().start_line: node
        for node in tree.nodes()
        if isinstance(node, Name) and node.id == "g"
    }
    in_function, in_module = reads[10], reads[13]
    definition = in_function.unit.function_definition_for_read(in_function)
    assert isinstance(definition, FunctionDef)
    assert definition.name == "g"
    assert in_module.unit.function_definition_for_read(in_module) is None

    value = in_function.sugar()
    assert isinstance(value, DecoratorApplicationSugar)
    assert value.definition_name == "g"
    assert value.decorators == ()
    assert value.defaults == ()
    assert value.definition_frame is not None
    assert value.evaluation is None


def test_every_once_bound_def_is_read_as_its_function_whatever_its_kind() -> None:
    """A plain ``def``, a generator function and an ``async def`` bound once
    are each read as the function its statement built (#7757: one call door,
    whatever the definition's kind); a name the module binds twice is not one
    definition's and is not."""
    from sugar_source_tree.nodes import AsyncFunctionDef

    tree = _tree(
        "def gen():\n    yield 1\n\n\n"
        "async def co():\n    return 1\n\n\n"
        "def twice():\n    return 1\n\n\n"
        "twice = None\n\n\n"
        "def plain():\n    return 1\n\n\n"
        "def test_f():\n    return [gen, co, twice, plain]\n"
    )
    answers = {
        node.id: node.unit.function_definition_for_read(node)
        for node in tree.nodes()
        if isinstance(node, Name) and node.id in {"gen", "co", "twice", "plain"}
    }
    assert isinstance(answers["gen"], FunctionDef)
    assert answers["gen"].name == "gen"
    assert isinstance(answers["co"], AsyncFunctionDef)
    assert answers["co"].name == "co"
    assert answers["twice"] is None
    assert isinstance(answers["plain"], FunctionDef)
    assert answers["plain"].name == "plain"


def test_a_generator_coroutine_or_manager_called_by_name_is_its_edge(
    tmp_path,
) -> None:
    """A generator function, an ``async def`` and a ``contextmanager``
    generator called by name are each called through the function its
    statement built: the definition's coordinate and edge, as a plain
    ``def``'s call is (#7757, one call door), never a frame seated by the
    name.  No body runs at the call: the lying half's ``ZeroDivisionError``
    is no face of the caller's reduction."""
    source = """\
import contextlib


def gen(n):
    yield {x}


async def co(n):
    return {x}


@contextlib.contextmanager
def cm(n):
    yield {x}


def test_f():
    a = gen(1)
    b = co(1)
    c = cm(1)
    return 3
"""
    for module, x in (("truthful", "n"), ("lying", "1 // 0")):
        outcome = _rooted_outcome(tmp_path, source.format(x=x), module)
        owed = _owed_symbols(outcome)
        for name in ("gen", "co", "cm"):
            assert f"python:{module}.{name}" in owed, (name, outcome)
        assert _raises(outcome, "ZeroDivisionError") == []


def test_a_def_bound_to_a_local_name_is_called_through_its_function(
    tmp_path,
) -> None:
    """``f = g; f()``: ``f`` holds the function ``g``'s ``def`` statement
    built, and the call through it is ``g``'s coordinate and edge, as
    ``g()`` is (#7757 step 5, #8705).  ``g``'s body is never applied here:
    the lying half's ``ZeroDivisionError`` is ``g``'s contract's halt,
    joined at prove (#8690), no face of this reduction."""
    source = """\
def g():
    return {x}


def test_f():
    f = g
    a = f()
    return 3
"""
    for module, x in (("truthful", "1"), ("lying", "1 // 0")):
        outcome = _rooted_outcome(tmp_path, source.format(x=x), module)
        assert f"python:{module}.g" in _owed_symbols(outcome), outcome
        assert _positional(_edge_term(outcome, f"{module}.g")) == ()
        assert _raises(outcome, "ZeroDivisionError") == []


# ---------------------------------------------------------------------------
# A source decorator's result is what the call runs.
# ---------------------------------------------------------------------------

_SOURCE_DECORATOR = """\
def fail(n):
    raise ValueError('decorated')


def replace(fn):
    return lambda n: {wrapper}


@replace
def scale(n):
{body}


def test_scale():
    value = scale(2)
    assert value == 20
"""


def test_a_source_decorator_replaces_a_raising_body(tmp_path) -> None:
    """The bare body raises; the decorator's result does not.  ``scale`` is
    what the module run's ``replace(scale)`` returned: that application is
    ``replace``'s edge (#7757 step 5, #8705), owed by every function that
    reads the name, and the bare body is never run."""
    outcome = _rooted_outcome(
        tmp_path,
        _SOURCE_DECORATOR.format(
            wrapper="n * 10", body="    raise ValueError('plain body')"
        ),
    )
    assert "python:subject.replace" in _owed_symbols(outcome), outcome
    assert _raises(outcome, "ValueError") == []


def test_a_source_decorator_changes_what_the_call_does(tmp_path) -> None:
    """The bare body returns; the decorator's result raises.  Its result is
    what the call calls: the call of ``replace``'s result, which neither the
    lift nor prove decides until a call of a call's result is dispatched at
    prove (survey step 8 on #7757, an owner ruling).  Decided here before
    step 5 by following ``replace``'s body (its one face the ``ValueError``);
    now ``replace``'s edge is owed and no face names the raise."""
    outcome = _rooted_outcome(
        tmp_path, _SOURCE_DECORATOR.format(wrapper="fail(n)", body="    return n")
    )
    assert "python:subject.replace" in _owed_symbols(outcome), outcome
    assert _raises(outcome, "ValueError") == []


def test_a_decorated_local_function_calls_the_decorators_result(tmp_path) -> None:
    """The statement applies ``replace`` where it runs, in ``test_scale``:
    that application is ``replace``'s edge, its actual the function the
    local ``def`` built; the bare body is never run."""
    source = """\
def replace(fn):
    return lambda n: n * 10


def test_scale():
    @replace
    def scale(n):
        raise ValueError('plain body')

    value = scale(2)
    assert value == 20
"""
    outcome = _rooted_outcome(tmp_path, source)
    assert "python:subject.replace" in _owed_symbols(outcome), outcome
    (actual,) = _positional(_edge_term(outcome, "subject.replace"))
    # The function the ``def`` built, stated as its join symbol (#7757
    # step 9): a call of what ``replace`` returns joins at prove.
    assert getattr(actual, "name", None) == "python:function"
    assert actual.args[0].value.startswith(
        "python:subject.test_scale.<locals>.scale@"
    ), actual
    assert _raises(outcome, "ValueError") == []


# ---------------------------------------------------------------------------
# An imported decorator is undecided, never the plain body.
# ---------------------------------------------------------------------------

_IMPORTED = """\
from elsewhere import wrap


@wrap
def scale(n):
    raise ValueError('plain body')


def test_scale():
    value = scale(2)
    assert value == 20
"""


def test_an_imported_decorator_is_undecided_never_the_plain_body() -> None:
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    outcome = _test_function_outcome(_IMPORTED)
    assert _raises(outcome, "ValueError") == []
    assert "python:elsewhere.wrap" in {item.symbol for item in owed_calls(outcome)}


# ---------------------------------------------------------------------------
# Builtin decorators go through the one builtin door.
# ---------------------------------------------------------------------------


def test_a_staticmethod_read_off_its_class_takes_no_implicit_argument(
    tmp_path,
) -> None:
    """``Box.pick(3)`` of a ``staticmethod`` is the one dispatched call
    looked up on ``Box`` with the one written actual and nothing implicit
    (#7757 entry 6: prove looks it up and binds it by the kind the class's
    namespace row states).  The body is never applied here: its
    ``ValueError`` is ``pick``'s contract's halt, joined at prove, so
    neither body's raise is a face here."""
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.ir import num

    source = """\
class Box:
    @staticmethod
    def pick(n):
{body}
"""
    for module, body in (
        ("returns", "        return n"),
        ("raises", "        raise ValueError('static')"),
    ):
        box, ctx = _rooted_class_value(tmp_path, source.format(body=body), module)
        outcome = box.call_method_value(
            "pick", (TermValue(3),), owner="test", blame="pick-site", ctx=ctx
        )
        term = _edge_term(outcome, "dispatch:pick")
        assert _positional(term) == (num(3),)
        assert _lookup(term) == (f"python:{module}.Box", "")
        assert "ValueError" not in _halt_names(outcome)


def test_a_property_getter_runs_on_the_instance_read(tmp_path) -> None:
    """``Receiver().value``: ``Receiver()`` is the class's edge (#7757 step
    6, #8738) and ``value`` a member of that call's result, the undecided
    read (``CallSiteValue.attribute``): the getter runs on an instance only
    a dispatch at prove could select (survey step 8 on #7757, an owner
    ruling).  Before step 6 the getter's ``ValueError`` was this reduction's
    one face; now no face names it."""
    source = """\
class Receiver:
    @property
    def value(self):
        raise ValueError('getter')


def test_value():
    found = Receiver().value
    assert found == 1
"""
    outcome = _rooted_outcome(tmp_path, source)
    assert "python:subject.Receiver" in _owed_symbols(outcome), outcome
    assert _raises(outcome, "ValueError") == []


def test_typing_final_returns_the_function(tmp_path) -> None:
    """``typing.final`` returns its argument, so ``check`` is the function
    its ``def`` built and ``check(2)`` its edge (#7757 step 5): the body's
    ``ValueError`` is ``check``'s contract's halt, joined at prove."""
    from sugar_lift_py_tests.ir import num

    outcome = _rooted_outcome(
        tmp_path,
        """\
from typing import final


@final
def check(n):
    raise ValueError('final body')


def test_check():
    value = check(2)
    assert value == 2
""",
    )
    assert "python:subject.check" in _owed_symbols(outcome), outcome
    assert _positional(_edge_term(outcome, "subject.check")) == (num(2),)
    assert _raises(outcome, "ValueError") == []


def test_a_builtin_decorator_is_decided_by_the_one_builtin_arm() -> None:
    """Every reader of a builtin decorator's semantics (the statement's
    application, an explicit ``final(f)`` through an import member, the
    manager-protocol absence proof) asks ``builtin_decorator_step``: identity
    where the application returns its argument, unanswered (the ``undecided``
    member under the builtin's target symbol) otherwise, and None for a
    decorator whose binding is no builtin."""
    from sugar_source_tree.nodes import builtin_decorator_step

    tree = _tree(
        """\
import abc
import functools
import typing


def d(fn):
    return fn


@typing.final
@abc.abstractmethod
@functools.lru_cache
@d
def g():
    return 1
"""
    )
    g = next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == "g"
    )
    steps = [builtin_decorator_step(g, d) for d in g.decorators]
    kinds = [getattr(step, "kind", None) for step in steps]
    assert kinds == ["identity", "identity", "unanswered", None]
    assert steps[2].symbol == "python:functools.lru_cache"


def test_an_lru_cache_function_is_undecided_never_the_plain_body() -> None:
    """``@functools.lru_cache`` is applied by nothing here: a call of the
    name is the ``undecided`` member under its target symbol, never the
    plain body and never a refusal of the statement."""
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    outcome = _test_function_outcome(
        """\
import functools


@functools.lru_cache
def scale(n):
    raise ValueError('plain body')


def test_scale():
    value = scale(2)
    assert value == 20
"""
    )
    assert _raises(outcome, "ValueError") == []
    assert "python:functools.lru_cache" in {
        item.symbol for item in owed_calls(outcome)
    }


# ---------------------------------------------------------------------------
# A module reader binds a decorated name to the application.
# ---------------------------------------------------------------------------


def test_a_module_reader_binds_a_decorated_name_to_its_application() -> None:
    tree = _tree(
        """\
def replace(fn):
    return lambda n: n * 10


scale = None


@replace
def scale(n):
    return n


def f():
    return scale(2)
""",
        TreeConstructionContextV1.for_source_call_construction(),
    )
    function = next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == "f"
    )
    final = function.unit.module_bindings_at(None, {"scale"})["scale"]
    assert isinstance(final, DecoratedDefinitionRef)
    assert final.definition_name == "scale"
    assert _module_reference_state(final) is final


# ---------------------------------------------------------------------------
# Prove binds what the lookup binds (#8011 residue, #7757 entry 6).
# ---------------------------------------------------------------------------


def _rooted_class_value(tmp_path, source: str, module: str = "subject"):
    """``_class_value`` of a file opened under a workspace root, so a call
    of a method is the one dispatched edge, naming the class it is looked up
    on (``receiver_dispatch.dispatch_edge_call``)."""
    from sugar_lift_py_tests.context.reduce_context import ReduceContext

    tree = _rooted_tree(tmp_path, source, module)
    (class_def,) = tuple(node for node in tree.nodes() if isinstance(node, ClassDef))
    ctx = ReduceContext.root(owner="test")
    return class_def.sugar().desugar(ctx).completed_value(), ctx


def _halt_names(outcome) -> list:
    from sugar_lift_py_tests.outcome import Halted

    return [
        face.effect.exception_name
        for face in getattr(outcome, "exits", ())
        if isinstance(face, Halted)
    ]


def _lookup(term) -> tuple:
    """``(on, after)`` of the one ``py.lookup(<on>, <after>)`` the dispatched
    call term carries (``receiver_dispatch.lookup_term``)."""
    (lookup,) = tuple(
        arg for arg in term.args if getattr(arg, "name", None) == "py.lookup"
    )
    return tuple(part.value for part in lookup.args)


def test_a_plain_function_read_off_its_class_takes_no_implicit_argument(
    tmp_path,
) -> None:
    """``Box.pick(3)`` calls ``pick(3)``: the function looked up on the class
    is unbound.  The call is the one dispatched call looked up on the class
    object ``Box`` (#7757 entry 6: one MRO lookup, at prove), with that one
    actual as written and no receiver; which function runs and how it binds
    is prove's (``consistency::dispatched_target``).  The body's raise is its
    contract's halt, joined at prove, never a face here."""
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.ir import num

    for module, body in (
        ("returns", "        return n"),
        ("raises", "        raise ValueError('unbound')"),
    ):
        box, ctx = _rooted_class_value(
            tmp_path, f"class Box:\n    def pick(n):\n{body}\n", module
        )
        outcome = box.call_method_value(
            "pick", (TermValue(3),), owner="test", blame="pick-site", ctx=ctx
        )
        term = _edge_term(outcome, "dispatch:pick")
        assert _positional(term) == (num(3),)
        assert _lookup(term) == (f"python:{module}.Box", "")
        assert "ValueError" not in _halt_names(outcome)


def test_a_plain_function_read_off_its_class_takes_its_receiver_as_written(
    tmp_path,
) -> None:
    """``Box.pick(obj, 3)`` passes ``obj`` as written: two actuals, nothing
    implicit, on the dispatched call looked up on ``Box`` (#7757 entry 6)."""
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.ir import num

    box, ctx = _rooted_class_value(
        tmp_path, "class Box:\n    def pick(self, n):\n        raise ValueError('ran')\n"
    )
    outcome = box.call_method_value(
        "pick",
        (TermValue(1), TermValue(3)),
        owner="test",
        blame="pick-site",
        ctx=ctx,
    )
    term = _edge_term(outcome, "dispatch:pick")
    assert _positional(term) == (num(1), num(3))
    assert _lookup(term) == ("python:subject.Box", "")
    assert "ValueError" not in _halt_names(outcome)


def test_a_classmethod_read_off_its_class_binds_the_class(tmp_path) -> None:
    """``Box.make(3)`` of a ``classmethod``: the dispatched call looked up on
    ``Box`` carries the written actual alone; prove binds the class first by
    the kind the class's namespace row states (``classmethod``, with the
    class object it states), never the lift (#7757 entry 6)."""
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.ir import num
    from sugar_lift_py_tests.tree_enumerate import _class_namespace_facts

    box, ctx = _rooted_class_value(
        tmp_path,
        "class Box:\n"
        "    @classmethod\n"
        "    def make(cls, n):\n"
        "        raise ValueError('ran')\n",
    )
    outcome = box.call_method_value(
        "make", (TermValue(3),), owner="test", blame="make-site", ctx=ctx
    )
    term = _edge_term(outcome, "dispatch:make")
    assert _positional(term) == (num(3),)
    assert _lookup(term) == ("python:subject.Box", "")
    assert "ValueError" not in _halt_names(outcome)
    _symbol, _mro, binds, class_object = _class_namespace_facts(box.class_definition)
    assert ("make", "classmethod", "python:subject.Box.make") in binds
    assert class_object is not None


def test_an_instance_lookup_binds_by_descriptor_kind(tmp_path) -> None:
    """Read off an instance: a ``staticmethod`` binds nothing and a
    ``classmethod`` binds the instance's class, never the instance.  The
    call is the one dispatched call over the instance's class (#7757 step
    8): the instance and the written actual, the method chosen and bound at
    prove by the kind the class's namespace row states -- never an edge to
    the method chosen here."""
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.ir import num
    from sugar_lift_py_tests.tree_enumerate import _class_namespace_facts

    for decorator, formals in (("staticmethod", "n"), ("classmethod", "cls, n")):
        box, ctx = _rooted_class_value(
            tmp_path,
            "class Box:\n"
            f"    @{decorator}\n"
            f"    def pick({formals}):\n"
            "        raise ValueError('ran')\n",
            decorator,
        )
        receiver = box.fresh_receiver("receiver-cid", allocation=FRAME_FRESH)
        outcome = receiver.call_method_value(
            "pick", (TermValue(3),), owner="test", blame="pick-site", ctx=ctx
        )
        term = _edge_term(outcome, "dispatch:pick")
        # The receiver is the first positional argument, its identity term
        # (``py.object.identity``, which ``_positional`` sets aside with the
        # ``py.*`` inputs), then the written actual (``dispatch_edge_call``).
        assert term.args[0] == receiver.to_term(owner="pick-site"), decorator
        assert _positional(term) == (num(3),), decorator
        assert any(
            getattr(arg, "name", None) == "py.class" for arg in term.args
        ), decorator
        assert "ValueError" not in _halt_names(outcome), decorator
        _symbol, _mro, binds, class_object = _class_namespace_facts(
            box.class_definition
        )
        assert ("pick", decorator, f"python:{decorator}.Box.pick") in binds, decorator
        assert (class_object is not None) == (decorator == "classmethod")


# ---------------------------------------------------------------------------
# A ``*``/``**`` call of a decorated name calls the decorators' result.
# ---------------------------------------------------------------------------


_SPREAD = """\
def fail(n):
    raise ValueError('decorated')


def replace(fn):
    return lambda n: {wrapper}


@replace
def scale(n):
    raise ValueError('plain body')


def test_scale():
    value = scale(*(2,))
    assert value == 20
"""


def test_a_spread_call_of_a_decorated_name_calls_its_application(tmp_path) -> None:
    """``scale(*(2,))`` calls what the module run's ``replace(scale)``
    returned, never the plain body.  That application is ``replace``'s edge
    (#7757 step 5, #8705), owed by the reader; what its result does when
    called is decided by neither the lift nor prove until a call of a
    call's result is dispatched at prove (survey step 8 on #7757).  Before
    step 5 the raising wrapper's ``ValueError`` was this reduction's one
    face; now no face names it."""
    for module, wrapper in (("scales", "n * 10"), ("raises", "fail(n)")):
        outcome = _rooted_outcome(tmp_path, _SPREAD.format(wrapper=wrapper), module)
        assert f"python:{module}.replace" in _owed_symbols(outcome), outcome
        assert _raises(outcome, "ValueError") == []


def test_a_spread_call_of_a_decorated_local_name_calls_its_application(
    tmp_path,
) -> None:
    outcome = _rooted_outcome(
        tmp_path,
        """\
def replace(fn):
    return lambda n: n * 10


def test_scale():
    @replace
    def scale(n):
        raise ValueError('plain body')

    value = scale(*(2,))
    assert value == 20
""",
    )
    assert "python:subject.replace" in _owed_symbols(outcome), outcome
    assert _raises(outcome, "ValueError") == []


# ---------------------------------------------------------------------------
# The decorators apply once, at the statement; every read reads its key.
# ---------------------------------------------------------------------------


def test_a_decorated_statement_and_its_reads_share_one_evaluation_key() -> None:
    tree = _tree(
        """\
def replace(fn):
    return lambda n: n * 10


def test_scale():
    @replace
    def scale(n):
        return n

    value = scale(2)
    assert value == 20
"""
    )
    function = next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == "test_scale"
    )
    statement, assignment = function.substitute({}).body[:2]
    bound = getattr(statement, "decorated_value", None)
    assert isinstance(bound, DecoratedDefinitionRef)
    key = getattr(bound, "evaluation", None)
    assert isinstance(key, str)
    read = assignment.value.func
    assert isinstance(read, DecoratedDefinitionRef)
    assert getattr(read, "evaluation", None) == key


def test_a_read_of_a_bound_key_never_applies_the_decorators_again() -> None:
    """With the statement's key bound, the read is the bound value: the
    decorator (here one that refuses whenever applied) is not run again.
    Unbound, the read is refused by name as every read of an unbound key is
    (``evaluation_ref_sugar.refuse_unbound_evaluation``, #7757 item 21): the
    decorators are never applied in the read's place, so the refusal names
    the key, never the decorator's own refusal."""
    import pytest

    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.floor.scope_rebind import ScopeRebind
    from sugar_lift_py_tests.gap.panic import ConstructionPanic
    from sugar_lift_py_tests.sugar.decorator_application_sugar import (
        DecoratorApplicationSugar,
        DecoratorStepV1,
    )
    from sugar_lift_py_tests.temporal.temporal_context import EVALUATION_PREFIX

    class _AppliedAgain:
        def desugar(self, ctx):
            raise AssertionError("applied again")

    key = EVALUATION_PREFIX + "blake3-512:decorated-definition/scale"
    read = DecoratorApplicationSugar(
        definition_name="scale",
        decorators=(DecoratorStepV1.apply("site", "boom", callee=_AppliedAgain()),),
        definition_frame=None,
        definition_class=None,
        refusal=None,
        site="site",
        evaluation=key,
    )
    ctx = ReduceContext.root(owner="test")
    value = TermValue(7)
    bound = ScopeRebind(key, value).extend_scope(ctx)
    assert read.desugar(bound).completed_value() is value
    with pytest.raises(ConstructionPanic, match="unbound") as refused:
        read.desugar(ctx)
    assert key in str(refused.value)
    assert "applied again" not in str(refused.value)


# ---------------------------------------------------------------------------
# A ``def`` statement binds the function; its body runs only at a call.
# ---------------------------------------------------------------------------


def test_an_uncalled_nested_def_contributes_no_face_of_its_body() -> None:
    outcome = _test_function_outcome(
        """\
def test_inner():
    def inner():
        raise ValueError('never called')

    assert 1 == 1
"""
    )
    assert _raises(outcome, "ValueError") == []


def test_a_called_nested_def_raises_at_the_call(tmp_path) -> None:
    """``inner()`` is the local ``def``'s edge (#7757 step 5, #8705): its
    ``ValueError`` is ``inner``'s contract's halt, which prove joins at this
    call (#8690).  Before step 5 the body was followed and the raise was a
    face of this reduction; now no face names it."""
    outcome = _rooted_outcome(
        tmp_path,
        """\
def test_inner():
    def inner():
        raise ValueError('called')

    inner()
""",
    )
    assert _owes_symbol_starting(
        outcome, "python:subject.test_inner.<locals>.inner@"
    ), outcome
    assert _positional(_edge_term(outcome, "subject.test_inner.<locals>.inner@")) == ()
    assert _raises(outcome, "ValueError") == []


# ---------------------------------------------------------------------------
# A ``def`` statement evaluates its defaults once; a call reads their keys.
# ---------------------------------------------------------------------------


def _function_named(tree, name: str):
    return next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == name
    )


def test_a_default_is_evaluated_at_its_def_statement() -> None:
    """Python evaluates ``1 // 0`` when the ``def`` statement runs, whether or
    not ``f`` is ever called.  Before, the statement was inert and the default
    evaluated only at a call, so this function completed."""
    raising = _test_function_outcome(
        """\
def test_default():
    def f(a=1 // 0):
        return a

    assert 1 == 1
"""
    )
    assert _raises(raising, "ZeroDivisionError") != []
    plain = _test_function_outcome(
        """\
def test_default():
    def f(a=1):
        return a

    assert 1 == 1
"""
    )
    assert _raises(plain, "ZeroDivisionError") == []


def test_a_default_is_the_binding_at_its_def_statement(tmp_path) -> None:
    """``x = 1; def f(a=x); x = 2; f()`` is 1: the call binds the value the
    statement evaluated, never the default expression read again at the
    call.  The call is ``f``'s edge (#7757 step 5, #8705), and it supplies
    that value as ``py.default(a, 1)``, which prove's one binder binds to
    the contract's ``default:a`` (#8693, #8698); the claim over it is
    decided at prove, no longer at this reduction."""
    from sugar_lift_py_tests.ir import num

    source = """\
def test_default():
    x = 1

    def f(a=x):
        return a

    x = 2
    assert f() == {expected}
"""
    for module, expected in (("truthful", 1), ("lying", 2)):
        outcome = _rooted_outcome(tmp_path, source.format(expected=expected), module)
        term = _edge_term(outcome, f"{module}.test_default.<locals>.f@")
        assert _positional(term) == ()
        assert _supplied_defaults(term) == {"a": num(1)}, term


def test_a_method_default_is_the_binding_at_its_class_statement(tmp_path) -> None:
    """``x = 1; class C: def m(self, a=x): ...; x = 2; C().m()`` is 1: the
    class body runs the method's ``def`` statement, which evaluates the
    default once; the call binds that value (#8020), never ``x`` read again
    at the call.  ``C()`` is the class's edge (#7757 step 6, #8738) and
    ``.m`` a member of that call's result: the undecided read, so the
    method's call names no definition and supplies no default until a
    method of a call's result is dispatched at prove (survey step 8 on
    #7757, an owner ruling).  Open on both halves today; the class value
    carrying the default its statement evaluated is
    ``test_the_class_statement_evaluates_its_methods_defaults``."""
    source = """\
def test_default():
    x = 1

    class C:
        def m(self, a=x):
            return a

    x = 2
    assert C().m() == {expected}
"""
    for module, expected in (("truthful", 1), ("lying", 2)):
        outcome = _rooted_outcome(tmp_path, source.format(expected=expected), module)
        assert _owes_symbol_starting(
            outcome, f"python:{module}.test_default.<locals>.C@"
        ), outcome
        assert not _owes_symbol_starting(
            outcome, f"python:{module}.test_default.<locals>.C.m@"
        ), outcome


def _binds_the_statements_value(
    tmp_path, source: str, target: str, *, param: str = "a"
) -> None:
    """Each half's call of ``target`` (a join symbol without its namespace,
    under the half's module) supplies the value the statement bound, 1, as
    ``py.default(<param>, 1)``, never ``x`` read again at the call (2): the
    edge of a same-file call (#7757 steps 5 and 6), joined at prove, where
    the claim over it is decided (#8693).  Decided at this reduction before
    those steps, by following the callee's body."""
    from sugar_lift_py_tests.ir import num

    for module, expected in (("truthful", 1), ("lying", 2)):
        outcome = _rooted_outcome(tmp_path, source.format(expected=expected), module)
        term = _edge_term(outcome, f"{module}.{target}")
        assert _supplied_defaults(term).get(param) == num(1), term


def _decorator_received_the_statements_default(
    tmp_path, source: str, decorator: str
) -> None:
    """Each half's ``decorator`` edge (#7757 step 5) takes the function the
    ``def`` statement built, carrying the default it evaluated, 1
    (``python:lambda_default``, ``LambdaCallable.to_term``), never ``x``
    read again.  The call of what the decorator returned is a call of a
    call's result: decided by neither the lift nor prove until it is
    dispatched at prove (survey step 8 on #7757), so the claim is open on
    both halves today."""
    from sugar_lift_py_tests.ir import num

    for module, expected in (("truthful", 1), ("lying", 2)):
        outcome = _rooted_outcome(tmp_path, source.format(expected=expected), module)
        assert _owes_symbol_starting(outcome, f"python:{module}.{decorator}"), outcome
        if decorator.endswith("@"):
            (function,) = _positional(_edge_term(outcome, f"{module}.{decorator}"))
            assert _lambda_defaults(function) == [num(1)], function


def test_a_decorated_default_is_the_binding_at_its_def_statement(tmp_path) -> None:
    """``x = 1; @deco def f(a=x); x = 2; f()`` is 1: the statement evaluates
    the default after the decorator expression and before the decorator
    applies; the function the decorator returns carries it and the call
    binds it, never ``x`` read again at the call."""
    _decorator_received_the_statements_default(
        tmp_path,
        """\
def test_default():
    x = 1

    def deco(fn):
        return fn

    @deco
    def f(a=x):
        return a

    x = 2
    assert f() == {expected}
""",
        "test_default.<locals>.deco@",
    )


def test_a_decorated_module_default_is_its_statements_binding(tmp_path) -> None:
    """The same at module level, called after import: the call reads the
    value the module run's statement bound, ``deco``'s result, whose
    application the module run made and the reader owes."""
    _decorator_received_the_statements_default(
        tmp_path,
        """\
x = 1


def deco(fn):
    return fn


@deco
def f(a=x):
    return a


x = 2


def test_default():
    assert f() == {expected}
""",
        "deco",
    )


def test_a_decorated_default_that_raises_raises_at_the_def_statement() -> None:
    """Python evaluates a decorated ``def``'s defaults when the statement
    runs, whether or not the function is ever called."""
    raising = _test_function_outcome(
        """\
def test_default():
    def deco(fn):
        return fn

    @deco
    def f(a=1 // 0):
        return a

    assert 1 == 1
"""
    )
    assert _raises(raising, "ZeroDivisionError") != []


def test_a_staticmethod_default_is_the_binding_at_its_class_statement(
    tmp_path,
) -> None:
    """``@staticmethod def m(a=x)``: the class body runs the ``def``
    statement, which evaluates the default before the descriptor applies;
    ``C.m()`` binds that value."""
    _binds_the_statements_value(
        tmp_path,
        """\
def test_default():
    x = 1

    class C:
        @staticmethod
        def m(a=x):
            return a

    x = 2
    assert C.m() == {expected}
""",
        "test_default.<locals>.C.m@",
    )


def test_a_classmethod_default_is_the_binding_at_its_class_statement(
    tmp_path,
) -> None:
    _binds_the_statements_value(
        tmp_path,
        """\
def test_default():
    x = 1

    class C:
        @classmethod
        def m(cls, a=x):
            return a

    x = 2
    assert C.m() == {expected}
""",
        "test_default.<locals>.C.m@",
    )


# ---------------------------------------------------------------------------
# ``C.m()`` on a function-local class reads ``C`` through its class statement.
# ---------------------------------------------------------------------------


def test_a_local_class_descriptor_called_off_its_class_runs_its_body(
    tmp_path,
) -> None:
    """``C.m()`` where ``class C`` stands in the function: ``C`` is the
    class its statement builds, ``m`` the member the one class-namespace
    lookup selects, and the call is ``m``'s edge (#7757 step 6, #8738) over
    what its descriptor binds (a ``staticmethod`` nothing, a ``classmethod``
    the class).  Before, ``C`` read as a free name and the call was the
    unanswered call of ``m`` with no definition; then (before step 6) the
    body ran and its raise was the one face.  The raise is now ``m``'s
    contract's halt, joined at prove."""
    for decorator, formals, implicit in (
        ("staticmethod", "", 0),
        ("classmethod", "cls", 1),
    ):
        outcome = _rooted_outcome(
            tmp_path,
            "def test_local():\n"
            "    class C:\n"
            f"        @{decorator}\n"
            f"        def m({formals}):\n"
            "            raise ValueError('ran')\n"
            "\n"
            "    C.m()\n",
            decorator,
        )
        term = _edge_term(outcome, f"{decorator}.test_local.<locals>.C.m@")
        assert len(_positional(term)) == implicit, decorator
        assert _raises(outcome, "ValueError") == [], decorator


def test_a_local_class_plain_function_takes_its_actuals(tmp_path) -> None:
    """A plain function read off its local class is unbound: ``C.m(5)``
    binds ``n`` to ``5``: ``m``'s edge with that one actual (#7757 step 6),
    whose return prove reads off ``m``'s contract."""
    from sugar_lift_py_tests.ir import num

    source = """\
def test_local():
    class C:
        def m(n):
            return n

    assert C.m(5) == {expected}
"""
    for module, expected in (("truthful", 5), ("lying", 6)):
        outcome = _rooted_outcome(tmp_path, source.format(expected=expected), module)
        term = _edge_term(outcome, f"{module}.test_local.<locals>.C.m@")
        assert _positional(term) == (num(5),), term


def test_a_local_class_statement_binds_its_name_under_its_evaluation_key() -> None:
    """An undecorated local ``class C`` binds ``C`` as an assignment binds
    its target: to the statement's value under its evaluation key
    (``DecoratedDefinitionRef``), the one read of the name for a call, a
    method receiver, an attribute, a base and a decorator alike.  The class
    statement never stands for the name, and the receiver-only second read
    is gone."""
    import sugar_source_tree.nodes as nodes
    from sugar_source_tree.nodes import (
        _LEXICALLY_BOUND_NAMES,
        _definition_evaluation_key,
        _local_definition_binding,
        call_applies_own_frame,
    )

    tree = _tree(
        "def test_local():\n"
        "    class C:\n"
        "        @staticmethod\n"
        "        def m():\n"
        "            return 1\n"
        "\n"
        "    C.m()\n"
    )
    (class_def,) = tuple(node for node in tree.nodes() if isinstance(node, ClassDef))
    assert not call_applies_own_frame(class_def)
    scope = {_LEXICALLY_BOUND_NAMES: frozenset({"C"})}
    binding = _local_definition_binding(class_def, scope)
    assert binding is not None
    bound = binding["C"]
    assert isinstance(bound, DecoratedDefinitionRef)
    assert bound.evaluation == _definition_evaluation_key(class_def, scope)
    assert not hasattr(nodes, "_local_class_receiver")


def test_a_module_reader_binds_an_undecorated_class_to_its_statements_value() -> (
    None
):
    """A module ``class C`` a function reads is the module run's value of
    ``C`` under the statement's key (``DecoratedDefinitionRef``), which a
    frame called after import binds to that value (``ModuleFinalValue``),
    never the class statement run again in the caller's frame."""
    from sugar_lift_py_tests.sugar.call_site_sugar import (
        _collect_final_evaluations,
    )

    tree = _tree(
        """\
x = 1


class C:
    def __init__(self, a=x):
        self.a = a


def f():
    return C()
""",
        TreeConstructionContextV1.for_source_call_construction(),
    )
    function = next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == "f"
    )
    final = function.unit.module_bindings_at(None, {"C"})["C"]
    assert isinstance(final, DecoratedDefinitionRef)
    assert final.definition_name == "C"
    assert _module_reference_state(final) is final
    evaluations: list = []
    _collect_final_evaluations(final, evaluations, [])
    assert evaluations == [final.evaluation]


def test_an_init_default_is_the_binding_at_its_class_statement(tmp_path) -> None:
    """``x = 1; class C: def __init__(self, a=x): self.a = a; x = 2;
    C().a`` is 1: the class body runs the ``__init__`` statement, which
    evaluates the default; the class value carries it and the class call
    binds it, never ``x`` read again at the call.  ``C()`` is the class's
    edge (#7757 step 6, #8738) supplying ``py.default(a, 1)``; ``.a`` is
    read through the class's contract at prove (#8746)."""
    _binds_the_statements_value(
        tmp_path,
        """\
x = 1


class C:
    def __init__(self, a=x):
        self.a = a


x = 2


def test_default():
    assert C().a == {expected}
""",
        "C",
    )


def test_a_source_new_default_is_the_binding_at_its_class_statement(
    tmp_path,
) -> None:
    """The same for a source ``__new__`` the class call runs: its default
    is the value its ``def`` statement evaluated in the class body, which
    the class's edge supplies (#7757 step 6)."""
    _binds_the_statements_value(
        tmp_path,
        """\
x = 1


class C:
    def __new__(cls, a=x):
        obj = super(C, cls).__new__(cls)
        obj.a = a
        return obj


x = 2


def test_default():
    assert C().a == {expected}
""",
        "C",
    )


def test_a_spread_class_call_binds_the_init_default_of_its_class_statement(
    tmp_path,
) -> None:
    """``C(*(5,))`` is the class call ``C(5)`` is
    (``ClassDefinitionValue.callable_application_with``): the omitted ``b`` binds
    the value the ``__init__`` statement evaluated when the class body ran,
    never an undecided read and never ``x`` read again at the call.  The
    class's edge (#7757 step 6) supplies ``5`` and ``py.default(b, 1)``."""
    _binds_the_statements_value(
        tmp_path,
        """\
x = 1


class C:
    def __init__(self, a, b=x):
        self.a = a
        self.b = b


x = 2


def test_default():
    assert C(*(5,)).b == {expected}
""",
        "C",
        param="b",
    )


def test_a_class_call_reads_its_constructors_defaults_off_the_class() -> None:
    """The constructor frame's default reads the key the class value
    carries for ``__init__``; it is never the default expression."""
    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.sugar.default_value_sugar import DefaultValueSugar

    tree = _tree("class Box:\n    def __init__(self, n=3):\n        self.n = n\n")
    (class_def,) = tuple(node for node in tree.nodes() if isinstance(node, ClassDef))
    box = (
        class_def.sugar()
        .desugar(ReduceContext.root(owner="test"))
        .completed_value()
    )
    (read,) = class_def.source_visible_constructor_frame().default_sugars
    assert isinstance(read, DefaultValueSugar)
    assert [key for key, _value in box.constructor_defaults()] == [read.evaluation]


def test_no_default_expression_is_evaluated_at_a_call() -> None:
    """The call-time default evaluation is gone: a frame's default is only
    the read of its key, and every definition's defaults are constructed by
    the one statement door."""
    import dataclasses

    import sugar_source_tree.nodes as nodes
    from sugar_lift_py_tests.sugar.default_value_sugar import DefaultValueSugar

    assert [field.name for field in dataclasses.fields(DefaultValueSugar)] == [
        "evaluation",
        "site",
    ]
    assert not hasattr(nodes, "_lambda_default_value_sugar")


def test_the_class_statement_evaluates_its_methods_defaults() -> None:
    """The class value carries each method default under the key the
    method's frame reads, and a default that raises raises at the class
    statement, whether or not the method is ever called."""
    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.sugar.default_value_sugar import DefaultValueSugar

    tree = _tree("class Box:\n    def pick(self, n=3):\n        return n\n")
    (class_def,) = tuple(node for node in tree.nodes() if isinstance(node, ClassDef))
    box = (
        class_def.sugar()
        .desugar(ReduceContext.root(owner="test"))
        .completed_value()
    )
    frame = _function_named(tree, "pick").source_visible_call_frame()
    (read,) = tuple(
        default.evaluation
        for default in frame.default_sugars
        if isinstance(default, DefaultValueSugar)
    )
    assert [key for key, _value in box.method_defaults] == [read]
    raising = _test_function_outcome(
        """\
def test_default():
    class Box:
        def pick(self, n=1 // 0):
            return n

    assert 1 == 1
"""
    )
    assert _raises(raising, "ZeroDivisionError") != []


def test_the_class_statement_evaluates_its_methods_decorators() -> None:
    """Python evaluates a method's decorator expressions when its ``def``
    statement runs, which is when the class body runs: a decorator that
    raises raises at the class statement, whether or not the method is ever
    called."""
    raising = _test_function_outcome(
        """\
def test_decorator():
    class Box:
        @(1 // 0)
        def pick(self):
            return 1

    assert 1 == 1
"""
    )
    assert _raises(raising, "ZeroDivisionError") != []


def test_the_class_body_applies_a_source_decorator_where_it_runs(tmp_path) -> None:
    """A class-body ``def`` under a source decorator is the one decorator
    application, as a decorated ``def`` in a module or function body is
    (#7757): Python calls ``replace(pick)`` when the class body runs, so
    that call is ``replace``'s edge at the class statement, owed, its
    actual the function the ``def`` built, and every face of it the class
    statement's.  Before, the class body evaluated the decorator expression
    and applied nothing: no edge, so a decorator that raises was a dropped
    halt.  The plain body is never run."""
    source = """\
def replace(fn):
    return lambda self: 7


def test_box():
    class Box:
        @replace
        def pick(self):
            raise ValueError('plain body')

    assert 1 == 1
"""
    outcome = _rooted_outcome(tmp_path, source)
    assert "python:subject.replace" in _owed_symbols(outcome), outcome
    (actual,) = _positional(_edge_term(outcome, "subject.replace"))
    assert getattr(actual, "name", None) == "python:function", actual
    assert _raises(outcome, "ValueError") == []


def test_a_builtin_descriptor_stays_the_descriptor_tables(tmp_path) -> None:
    """``staticmethod``, ``classmethod``, ``property`` and a property's own
    ``@x.setter`` are builtins the class body's descriptor table models
    (``ClassDef.descriptor_table_models``): the class statement applies
    none of them, so it owes nothing for them, while a source decorator
    beside them is applied and owed."""
    source = """\
def replace(fn):
    return fn


def test_box():
    class Box:
        @property
        def size(self):
            return 1

        @size.setter
        def size(self, value):
            pass

        @staticmethod
        def make():
            return 2

        @classmethod
        def build(cls):
            return 3

        @replace
        def pick(self):
            return 4

    assert 1 == 1
"""
    tree = _rooted_tree(tmp_path, source)
    (box,) = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, ClassDef) and node.name == "Box"
    )
    methods = tuple(item for item in box.body if isinstance(item, FunctionDef))
    assert [box.descriptor_table_models(method) for method in methods] == [
        True,  # @property
        True,  # @size.setter of the body's own property
        True,  # @staticmethod
        True,  # @classmethod
        False,  # @replace: the one application
    ]
    outcome = _rooted_outcome(tmp_path, source)
    owed = _owed_symbols(outcome)
    assert "python:subject.replace" in owed, outcome
    for builtin in ("property", "staticmethod", "classmethod", "setter"):
        assert not any(builtin in str(symbol) for symbol in owed), owed


def test_a_def_statement_evaluates_its_annotations() -> None:
    """Without ``from __future__ import annotations`` Python evaluates a
    ``def``'s annotations when the statement runs, after its defaults: an
    annotation that raises raises there, whether or not the function is ever
    called."""
    raising = _test_function_outcome(
        """\
def test_annotation():
    def f(a: 1 // 0):
        return a

    assert 1 == 1
"""
    )
    assert _raises(raising, "ZeroDivisionError") != []


def test_the_class_statement_evaluates_its_keyword_values() -> None:
    """Python evaluates a class keyword's value (``metaclass=...``) where
    the class statement runs, after the bases and before the body: a value
    that raises raises at the class statement."""
    raising = _test_function_outcome(
        """\
def test_keyword():
    class Box(metaclass=1 // 0):
        pass

    assert 1 == 1
"""
    )
    assert _raises(raising, "ZeroDivisionError") != []


def test_the_statement_and_the_frame_name_one_default_key() -> None:
    """The ``def`` statement binds each default under the key every frame
    of the definition reads."""
    from sugar_lift_py_tests.sugar.default_value_sugar import (
        DefaultValueSugar,
        DefinitionDefaultsSugar,
    )

    tree = _tree(
        """\
def test_default():
    def f(a, b=2, *, c=3):
        return a

    return f(1)
"""
    )
    function = _function_named(tree, "test_default")
    statement = function.substitute({}).body[0]
    sugar = function._sugar_body_statement(statement)
    assert isinstance(sugar, DefinitionDefaultsSugar)
    frame = _function_named(tree, "f").source_visible_call_frame()
    assert frame.default_sugars[0] is None
    read = tuple(
        default.evaluation
        for default in frame.default_sugars
        if isinstance(default, DefaultValueSugar)
    )
    assert read == tuple(key for key, _index in sugar.evaluations)
    assert len(set(read)) == 2


def test_a_default_read_is_the_one_bound_value_for_every_call() -> None:
    """With the statement's key bound, every call binds the same object (a
    mutable default is shared, as in Python); unbound, the call is refused
    by name: no default expression is ever evaluated at a call."""
    import pytest

    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.floor.scope_rebind import ScopeRebind
    from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap
    from sugar_lift_py_tests.sugar.default_value_sugar import DefaultValueSugar
    from sugar_lift_py_tests.temporal.temporal_context import EVALUATION_PREFIX

    key = EVALUATION_PREFIX + "blake3-512:definition-default/f/a"
    read = DefaultValueSugar(evaluation=key, site="site")
    ctx = ReduceContext.root(owner="test")
    value = TermValue(7)
    bound = ScopeRebind(key, value).extend_scope(ctx)
    assert read.desugar(bound).completed_value() is value
    assert read.desugar(bound).completed_value() is value
    with pytest.raises(SourceCallBindingGap, match="default not bound"):
        read.desugar(ctx)


# ---------------------------------------------------------------------------
# ``Class.m(...)`` of a classmethod binds through the one method door.
# ---------------------------------------------------------------------------


_CLASSMETHOD = """\
class Box:
    @classmethod
    def make(cls, n):
        {body}


def test_make():
    Box.make(3)
"""


def test_a_classmethod_frame_takes_its_class_as_a_formal() -> None:
    assert not hasattr(FunctionDef, "bound_classmethod_call_frame")
    tree = _tree(_CLASSMETHOD.format(body="return n"))
    frame = _function_named(tree, "make").source_visible_call_frame()
    assert frame.parameters == ("cls", "n")
    assert not hasattr(frame, "bound_receiver_class")


def test_a_classmethod_called_off_its_class_runs_its_body(tmp_path) -> None:
    """``Box.make(3)`` is ``make``'s edge (#7757 step 6, #8738), the class
    then ``3``: its ``ValueError`` is ``make``'s contract's halt, joined at
    prove (#8690), no longer a face of this reduction."""
    from sugar_lift_py_tests.ir import num

    outcome = _rooted_outcome(
        tmp_path, _CLASSMETHOD.format(body="raise ValueError('ran')")
    )
    assert "python:subject.Box.make" in _owed_symbols(outcome), outcome
    implicit, written = _positional(_edge_term(outcome, "subject.Box.make"))
    assert written == num(3)
    assert implicit != num(3)
    assert _raises(outcome, "ValueError") == []


# ---------------------------------------------------------------------------
# A function body's nested ``def`` stays in its frame and binds its name.
# ---------------------------------------------------------------------------


_OUTER = """\
def outer():
    def inner():
        raise ValueError('called')

    return inner()


def test_outer():
    outer()
"""


def test_a_frame_holds_no_body() -> None:
    """A ``def``'s frame is its signature (#7757): its body, the nested
    ``def`` statement among it, is the function's own universe's, never
    rebuilt in the frame for a call."""
    tree = _tree(_OUTER)
    frame = _function_named(tree, "outer").source_visible_call_frame()
    assert frame.body is None
    assert frame.parameters == ()


def test_a_call_into_a_frame_reaches_its_nested_def_through_the_call(
    tmp_path,
) -> None:
    """``outer()`` is ``outer``'s edge (#7757 step 5, #8705); ``inner``'s
    raise reaches it through ``outer``'s contract, whose own call of
    ``inner`` is joined in turn at prove (#8679, #8690).  Before step 5 the
    two bodies were followed and the raise was a face here; now no face
    names it."""
    outcome = _rooted_outcome(tmp_path, _OUTER)
    assert "python:subject.outer" in _owed_symbols(outcome), outcome
    assert _positional(_edge_term(outcome, "subject.outer")) == ()
    assert _raises(outcome, "ValueError") == []


# ---------------------------------------------------------------------------
# A staticmethod or classmethod read off an instance is a callable value.
# ---------------------------------------------------------------------------


def test_a_descriptor_read_off_an_instance_is_a_callable_value(tmp_path) -> None:
    """``m = obj.sm; m(3)``: the read is the value the descriptor binds, and
    its call is the one dispatched call over the instance's class: the
    instance and the written actual, bound at prove by the kind the class's
    namespace row states (nothing for a ``staticmethod``, the class for a
    ``classmethod``, #7757 step 8).  Before, the read was refused.  The
    body's raise is its contract's halt, joined at prove."""
    from sugar_lift_py_tests.callable_application import CallableApplication
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.floor.bound_method_value import BoundMethodValue
    from sugar_lift_py_tests.ir import num

    for decorator, formals in (("staticmethod", "n"), ("classmethod", "cls, n")):
        box, ctx = _rooted_class_value(
            tmp_path,
            "class Box:\n"
            f"    @{decorator}\n"
            f"    def pick({formals}):\n"
            "        raise ValueError('ran')\n",
            decorator,
        )
        receiver = box.fresh_receiver("receiver-cid", allocation=FRAME_FRESH)
        read = receiver.attribute("pick", "pick-site", ctx).completed_value()
        assert isinstance(read, BoundMethodValue), decorator
        outcome = read.callable_application_with(
            CallableApplication((TermValue(3),), (), "pick-site", owner="test"), ctx
        )
        term = _edge_term(outcome, "dispatch:pick")
        # The instance the read bound rides first, as its identity term
        # (``py.object.identity``, set aside by ``_positional`` with the
        # ``py.*`` inputs), then the written actual (``dispatch_edge_call``).
        assert term.args[0] == receiver.to_term(owner="pick-site"), decorator
        assert _positional(term) == (num(3),), decorator
        assert "ValueError" not in _halt_names(outcome), decorator


# ---------------------------------------------------------------------------
# A lambda's defaults are evaluated where the lambda expression is evaluated.
# ---------------------------------------------------------------------------


def test_a_lambda_default_is_the_binding_where_the_lambda_is_evaluated(
    tmp_path,
) -> None:
    """``x = 1; f = lambda a=x: a; x = 2; f()`` is 1: the lambda expression
    evaluates its default, its value carries it, and the call binds the
    carried value; the default expression is never evaluated at the call.
    The call is the lambda's edge (#7757 steps 5 and 6, #8705, #8742), and it
    supplies that value as ``py.default(a, 1)``, which prove's one binder
    binds to the lambda contract's ``default:a`` (#8687, #8693, #8698), never
    ``x`` read again at the call (2).  The claim over it is decided at prove,
    no longer at this reduction (was: the truthful half completed, the lying
    half raised ``AssertionError``)."""
    from sugar_lift_py_tests.ir import num

    source = """\
def test_default():
    x = 1
    f = lambda a=x: a
    x = 2
    assert f() == {expected}
"""
    for module, expected in (("truthful", 1), ("lying", 2)):
        outcome = _rooted_outcome(tmp_path, source.format(expected=expected), module)
        term = _edge_term(outcome, f"{module}.test_default.<locals>.<lambda>@")
        assert _positional(term) == (), term
        assert _supplied_defaults(term) == {"a": num(1)}, term


def test_a_lambda_default_that_raises_raises_at_the_lambda_expression() -> None:
    """Python evaluates ``1 // 0`` where the lambda expression is evaluated,
    whether or not the lambda is ever called."""
    raising = _test_function_outcome(
        """\
def test_default():
    f = lambda a=1 // 0: a
    assert 1 == 1
"""
    )
    assert _raises(raising, "ZeroDivisionError") != []


def test_a_lambda_value_carries_its_defaults_under_the_frames_keys() -> None:
    """The lambda value carries each evaluated default under the key its
    frame's ``DefaultValueSugar`` reads, and the frame never evaluates the
    expression itself."""
    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.floor import LambdaCallable
    from sugar_lift_py_tests.sugar.default_value_sugar import DefaultValueSugar
    from sugar_source_tree.nodes import Lambda

    tree = _tree("def test_default():\n    return (lambda a, b=2: b)(1)\n")
    lam = next(node for node in tree.nodes() if isinstance(node, Lambda))
    sugar = lam.substitute({}).sugar()
    value = sugar.desugar(ReduceContext.root(owner="test")).completed_value()
    assert isinstance(value, LambdaCallable)
    frame = lam.source_visible_call_frame()
    assert frame.default_sugars[0] is None
    read = frame.default_sugars[1]
    assert isinstance(read, DefaultValueSugar)
    assert not hasattr(read, "value")
    ((key, carried),) = value.defaults
    assert key == read.evaluation
    assert carried.to_term(owner="test") is not None


# ---------------------------------------------------------------------------
# A specialised body never carries a default expression.
# ---------------------------------------------------------------------------


def test_no_default_expression_appears_in_a_specialised_body() -> None:
    """``bind_node_actuals`` gives an omitted formal its own coordinate,
    which the one binder binds from the default's key: the default
    expression is never copied into the body."""
    from sugar_source_tree.nodes import BindingCoordinateRef

    tree = _tree(
        "def f(a, b=7):\n    return b\n\n\ndef test_f():\n    assert f(1) == 7\n"
    )
    definition = _function_named(tree, "f")
    frame = definition.source_visible_call_frame()
    bound = frame.bind_node_actuals(tuple(_call_of(tree, "f").args), ())
    entry = bound.runtime_entries[1]
    assert isinstance(entry.state, BindingCoordinateRef), entry.state
    assert entry.state.coordinate == frame.formal_coordinates[1]
    default = definition.params[1].default
    assert all(
        item.state is not default
        and item.state.fragment.seal().cid != default.fragment.seal().cid
        for item in bound.runtime_entries
    )


def test_an_omitted_formal_still_binds_its_default_at_the_call(tmp_path) -> None:
    """``f(1)`` omits ``b``: ``f``'s edge (#7757 step 5, #8705) supplies the
    value its ``def`` statement bound as ``py.default(b, 7)``, which prove's
    one binder binds to the contract's ``default:b`` (#8693, #8698).  The
    claim is decided at prove (the solver twin is
    ``test_function_value_application_twins[module-def-default]``), no
    longer at this reduction."""
    from sugar_lift_py_tests.ir import num

    source = (
        "def f(a, b=7):\n    return b\n\n\n"
        "def test_f():\n    assert f(1) == {expected}\n"
    )
    for module, expected in (("truthful", 7), ("lying", 8)):
        outcome = _rooted_outcome(tmp_path, source.format(expected=expected), module)
        term = _edge_term(outcome, f"{module}.f")
        assert _positional(term) == (num(1),), term
        assert _supplied_defaults(term) == {"b": num(7)}, term


# ---------------------------------------------------------------------------
# A decorator whose value nothing here resolves is its unanswered call.
# ---------------------------------------------------------------------------


def test_a_decorator_whose_value_is_undecided_is_its_unanswered_call() -> None:
    """``@property`` in a class body that binds its own ``property``
    (``pandas/tests/test_errors.py``'s ``Foo``): no builtin door reads the
    name, so the decorator is applied as the value its read reduced to.
    Where that value is undecided (a ``SymbolicValue``), applying it is the
    one unanswered call of a value (``computed_call_sugar.
    unanswered_value_call``), as ``d(f)`` written as a call is: one
    completion and the undetermined raise, owed.  It was a construction
    panic (``SymbolicValue`` has no ``callable_application_with``) where
    the class body applied its methods' decorators (#8962)."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.floor import SymbolicValue, TermValue
    from sugar_lift_py_tests.ir import make_var
    from sugar_lift_py_tests.outcome import Completed, Halted
    from sugar_lift_py_tests.sugar.decorator_application_sugar import (
        DecoratorStepV1,
    )
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    tree = _tree(
        "class Foo:\n"
        "    @property\n"
        "    def property(self):\n"
        "        return 1\n"
    )
    (method,) = [node for node in tree.nodes() if isinstance(node, FunctionDef)]
    site = method.decorators[0].fragment
    step = DecoratorStepV1.apply(site, "property", callee=method.decorators[0])

    outcome = step.applied(SymbolicValue(make_var("property")), TermValue(1), None)

    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    halted = [face for face in outcome.exits if isinstance(face, Halted)]
    assert len(completed) == 1 and len(halted) == 1, outcome
    assert isinstance(halted[0].effect, UndeterminedRaiseEffect), halted[0].effect
    assert halted[0].effect.exception_name is None
    assert owed_calls(outcome), outcome
