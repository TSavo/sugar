"""A ``with`` head whose class is proven, from source, not to be a manager.

``with x:`` looks ``__enter__``/``__exit__`` up on ``type(x)``'s MRO.  When
every class of that C3 MRO is a module ``class`` statement read here or a
cited language base (``object``, ``abc.ABC``, their attribute sets read from
the interpreter) and none binds ``__enter__`` (or ``__exit__``), the head is
evaluated and then the ``with`` raises the interpreter's own ``TypeError``
("'X' object does not support the context manager protocol", or "... (missed
__exit__ method)") before any enter and before the body.  This covers
same-module classes.  Any base that is neither, a class decorator, a
metaclass, or a module that could install the protocol keeps the gap.

What a decorated function's call returns is the one decorator application's
(``DecoratorApplicationSugar``, #7757): no proof is read from a decorator's
body, and a method decorator is admitted only where that application returns
its argument (``builtin_decorator_step``).
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.manager_protocol_absence_refusal import (
    cited_language_base,
    observed_non_manager_with_refusal,
)
from sugar_source_tree.panic import SugarNotWritten

from test_assignment_evaluates_rhs import _rows
from test_contextlib_suppress_source_exit_faces import _corpus, _open
from test_undetermined_raise_except_matching import _exits

def _split(tmp_path, source):
    rows = _rows(_exits(tmp_path, source))
    returns = [payload for kind, payload, _ in rows if kind == "return"]
    halts = [payload for kind, payload, _ in rows if kind == "halt"]
    return returns, halts


def _type_error_halt(tmp_path, source, type_name, *, has_enter=False):
    returns, halts = _split(tmp_path, source)
    assert returns == []
    (halt,) = halts
    assert isinstance(halt, RaiseEffect)
    assert halt.producer_node_owner == "NonManagerObjectWithSugar"
    refusal = observed_non_manager_with_refusal(
        type_name, has_enter=has_enter, has_exit=False
    )
    assert refusal.exception_name == "TypeError"
    assert halt.exception_name == "TypeError"
    assert halt.raised_value == refusal.message
    return halt


def test_the_refusal_text_is_the_interpreters():
    plain = observed_non_manager_with_refusal("M", has_enter=False, has_exit=False)
    assert plain.message == "'M' object does not support the context manager protocol"
    missed_exit = observed_non_manager_with_refusal("M", has_enter=True, has_exit=False)
    assert missed_exit.message.endswith("(missed __exit__ method)")


def test_cited_bases_are_read_from_the_interpreter():
    from sugar_source_tree.nodes import LanguageCallee

    obj = cited_language_base(LanguageCallee.BUILTIN_OBJECT)
    abc_base = cited_language_base(LanguageCallee.ABC_ABC)
    assert obj.linearization == ("builtins.object",)
    assert abc_base.linearization == ("abc.ABC", "builtins.object")
    assert obj.tail == ()
    assert abc_base.tail == (LanguageCallee.BUILTIN_OBJECT,)
    assert not obj.protocol_names and not abc_base.protocol_names
    assert not abc_base.metaclass_overrides_call
    assert not abc_base.subclass_gains & {"__enter__", "__exit__"}
    # A binding no citation answers for (the builtin ``list``) is not cited.
    assert cited_language_base(LanguageCallee.BUILTIN_LIST) is None


def test_a_decorated_async_def_head_is_the_decorator_application(tmp_path):
    """``@d async def cm`` binds ``cm`` to ``d(cm)``: what ``cm(1)`` returns is
    the one decorator application's.  Nothing reads ``d``'s body to prove the
    class it constructs lacks the protocol, and ``cm``'s own frame is never
    seated for the call (#7757)."""
    source = (
        "class Wrapper:\n"
        "    def __init__(self, gen):\n"
        "        self.gen = gen\n"
        "def d(func):\n"
        "    def helper(*args, **kwds):\n"
        "        return Wrapper(func(*args, **kwds))\n"
        "    return helper\n"
        "@d\n"
        "async def cm(a):\n"
        "    yield a\n"
        "def f():\n"
        "    with cm(1):\n"
        "        return 1\n"
    )
    source_file = _open(_corpus(tmp_path, source))
    context = source_file.root.unit.construction_context
    assert not context.source_non_manager_heads
    assert not context.source_manager_provider_calls


def _class(source, name):
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_source_tree.nodes import ClassDef
    from sugar_source_tree.tree import SourceFile

    tree = SourceFile(
        (source, "m.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    return next(
        node
        for node in tree.nodes()
        if isinstance(node, ClassDef) and node.name == name
    )


def test_a_method_decorator_the_application_returns_unchanged_is_admitted():
    """``typing.final`` returns its argument (the one decorator application's
    identity), so the method stays a plain function and the proof stands."""
    from sugar_lift_python_source.manager_protocol_absence import (
        prove_manager_protocol_absence,
    )

    source = (
        "import typing\n"
        "class M:\n"
        "    @typing.final\n"
        "    def g(self):\n"
        "        return 1\n"
    )
    proof = prove_manager_protocol_absence(_class(source, "M"))
    assert proof is not None
    assert proof.has_enter is False and proof.has_exit is False


@pytest.mark.parametrize(
    ("header", "decorator"),
    [
        # a source decorator may return anything
        ("def d(fn):\n    return fn\n", "@d"),
        # a builtin the one application refuses by name
        ("import functools\n", "@functools.lru_cache"),
    ],
    ids=["source-decorator", "refused-builtin"],
)
def test_a_method_decorator_the_application_does_not_return_unchanged_is_unproven(
    header, decorator
):
    from sugar_lift_python_source.manager_protocol_absence import (
        prove_manager_protocol_absence,
    )

    source = header + (
        "class M:\n"
        f"    {decorator}\n"
        "    def g(self):\n"
        "        return 1\n"
    )
    assert prove_manager_protocol_absence(_class(source, "M")) is None


@pytest.mark.parametrize(
    "shadow",
    [
        # the base is the function's parameter
        "def f(B):\n",
        # the base is the function's own class statement
        "def f():\n    class B:\n        pass\n",
    ],
    ids=["parameter", "local-class"],
)
def test_a_base_shadowed_locally_is_the_local_binding(shadow):
    """A base resolves through the binding its read reaches
    (``SourceUnit.module_definition_at``), never the module's ``class``
    statement of that spelling (#7757): the local ``B`` is not the module's
    ``B``, so the module class's ``__enter__`` is never read into ``M``'s MRO
    and the proof is not given."""
    from sugar_lift_python_source.manager_protocol_absence import (
        prove_manager_protocol_absence,
    )

    module_base = "class B:\n    def __enter__(self):\n        return 1\n"
    derived = "    class M(B):\n        pass\n    return M\n"
    unshadowed = prove_manager_protocol_absence(
        _class(module_base + "def f():\n" + derived, "M")
    )
    assert unshadowed is not None and unshadowed.has_enter is True
    assert (
        prove_manager_protocol_absence(_class(module_base + shadow + derived, "M"))
        is None
    )


def test_a_callee_shadowed_by_a_parameter_is_not_the_module_class(tmp_path):
    """The ``with`` head's callee resolves through the binding its read
    reaches: ``M`` is ``f``'s parameter, so the module's ``class M`` (which
    lacks the protocol) is never read as the head's class; ``g``'s ``M`` is
    the module's, and its head is (#7757)."""
    source = (
        "class M:\n    pass\n"
        "def f(M):\n    with M():\n        return 1\n"
        "def g():\n    with M():\n        return 1\n"
    )
    source_file = _open(_corpus(tmp_path, source))
    heads = source_file.root.unit.construction_context.source_non_manager_heads
    assert len(heads) == 1, heads
    (proof,) = heads.values()
    assert proof.type_name == "M"


def test_a_local_class_without_enter_raises_type_error(tmp_path):
    _type_error_halt(
        tmp_path, "class M:\n    pass\ndef f():\n    with M():\n        return 1\n", "M"
    )


def test_an_inherited_enter_without_exit_raises_the_missed_exit_text(tmp_path):
    source = (
        "class B:\n    def __enter__(self):\n        return 1\n"
        "class M(B):\n    pass\n"
        "def f():\n    with M():\n        return 1\n"
    )
    _type_error_halt(tmp_path, source, "M", has_enter=True)


def test_contextmanager_is_still_a_manager(tmp_path):
    source = (
        "import contextlib\n@contextlib.contextmanager\ndef cm():\n    yield 1\n"
        "def f():\n    with cm():\n        return 1\n"
    )
    returns, _ = _split(tmp_path, source)
    assert returns == [TermValue(1)]


@pytest.mark.parametrize(
    "source",
    [
        # the module installs the protocol after the class statement
        "class M:\n    pass\nM.__enter__ = lambda s: 1\n"
        "def f():\n    with M():\n        return 1\n",
        # a class decorator may return anything
        "def d(c):\n    return c\n@d\nclass M:\n    pass\n"
        "def f():\n    with M():\n        return 1\n",
        # an unresolved base
        "import textwrap\nclass M(textwrap.TextWrapper):\n    pass\n"
        "def f():\n    with M():\n        return 1\n",
        # a constructor that may raise keeps the gap (its faces are not carried)
        "class M:\n    def __init__(self, x):\n        if x:\n            raise ValueError('v')\n"
        "def f():\n    with M(1):\n        return 1\n",
    ],
    ids=["patched", "class-decorator", "unresolved-base", "raising-constructor"],
)
def test_unproven_heads_keep_the_gap(tmp_path, source):
    with pytest.raises((SugarNotWritten, ConstructionPanic)):
        _split(tmp_path, source)
