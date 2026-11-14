"""A ``with`` head whose class is proven, from source, not to be a manager.

``with x:`` looks ``__enter__``/``__exit__`` up on ``type(x)``'s MRO.  When
every class of that C3 MRO is a module ``class`` statement read here or a
cited language base (``object``, ``abc.ABC``, their attribute sets read from
the interpreter) and none binds ``__enter__`` (or ``__exit__``), the head is
evaluated and then the ``with`` raises the interpreter's own ``TypeError``
("'X' object does not support the context manager protocol", or "... (missed
__exit__ method)") before any enter and before the body.  This covers
``@asynccontextmanager`` at a sync ``with`` (its ``_AsyncGeneratorContextManager``
MRO is read from contextlib's source) and same-module classes.  Any base that
is neither, a class decorator, a metaclass, or a module that could install the
protocol keeps the runtime-selected gap.
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

ACM = "import contextlib\n@contextlib.asynccontextmanager\nasync def cm(a):\n    yield a\n"


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


def test_asynccontextmanager_at_a_sync_with_raises_type_error(tmp_path):
    source = ACM + "def f():\n    with cm(1):\n        return 1\n"
    _type_error_halt(tmp_path, source, "_AsyncGeneratorContextManager")


def test_the_proof_reads_contextlibs_mro(tmp_path):
    source = ACM + "def f():\n    with cm(1):\n        return 1\n"
    source_file = _open(_corpus(tmp_path, source))
    context = source_file.root.unit.construction_context
    (proof,) = context.source_non_manager_heads.values()
    import contextlib

    runtime_mro = tuple(
        cls.__name__ for cls in contextlib._AsyncGeneratorContextManager.__mro__
    )
    assert tuple(name.rsplit(":", 1)[-1].rsplit(".", 1)[-1] for name in proof.linearization) == runtime_mro
    assert proof.has_enter is False and proof.has_exit is False


def test_the_type_error_reaches_an_except_arm_and_the_body_never_runs(tmp_path):
    source = ACM + (
        "def f():\n"
        "    try:\n"
        "        with cm(1):\n"
        "            return 1\n"
        "    except TypeError:\n"
        "        return 2\n"
    )
    returns, halts = _split(tmp_path, source)
    assert returns == [TermValue(2)]
    assert halts == []


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
