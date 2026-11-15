"""A ``with`` head whose class is decided not to be a manager.

``with x:`` looks ``__enter__``/``__exit__`` up on ``type(x)``.  The head is
reduced, and where the one class-namespace lookup on the value's type decides
that it binds no ``__enter__`` (or no ``__exit__``), the ``with`` raises the
interpreter's own ``TypeError`` ("'X' object does not support the context
manager protocol", or "... (missed __exit__ method)") before any enter and
before the body (``ReducedManagerProtocolV1``, #7757).

What a decorated function's call returns is the one decorator application's
(``DecoratorApplicationSugar``, #7757): no proof is read from a decorator's
body, and a method decorator is admitted only where that application returns
its argument (``builtin_decorator_step``).
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.manager_protocol_absence_refusal import (
    cited_language_base,
    observed_non_manager_with_refusal,
)

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
    assert halt.producer_node_owner == "ReducedManagerProtocolV1"
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
    assert not context.source_call_frames


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


@pytest.mark.parametrize(
    ("module_tail", "proven"),
    [
        # a parameter named ``setattr`` is the parameter, not the builtin
        ("def f(setattr, n):\n    setattr(M, n, 1)\n", True),
        # a parameter named ``exec`` is the parameter, not the builtin
        ("def f(exec):\n    exec('x')\n", True),
        # the builtin ``setattr`` under another spelling is still the builtin
        (
            "from builtins import setattr as put\n"
            "def f(n):\n    put(M, n, 1)\n",
            False,
        ),
        # the builtin ``exec`` under another spelling is still the builtin
        ("from builtins import exec as run\ndef f():\n    run('x')\n", False),
        # the unshadowed builtin with a computed attribute name
        ("def f(n):\n    setattr(M, n, 1)\n", False),
        # a computed name on an imported module may retarget a base it holds
        ("import abc\ndef f(n):\n    setattr(abc, n, 1)\n", False),
    ],
    ids=[
        "setattr-parameter",
        "exec-parameter",
        "setattr-alias",
        "exec-alias",
        "setattr-builtin",
        "setattr-module-receiver",
    ],
)
def test_a_module_writer_is_known_by_its_binding(module_tail, proven):
    """The module scan reads each callee through the binding its read
    reaches (``language_callee_of`` / ``reads_dynamic_global_writer``), never
    its spelling (#7757): a shadowing parameter is not the builtin, and the
    builtin under an alias is."""
    from sugar_lift_python_source.manager_protocol_absence import (
        prove_manager_protocol_absence,
    )

    source = "class M:\n    pass\n" + module_tail
    proof = prove_manager_protocol_absence(_class(source, "M"))
    assert (proof is not None) is proven


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
