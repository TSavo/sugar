"""A ``with`` head whose class is decided not to be a manager.

``with x:`` looks ``__enter__``/``__exit__`` up on ``type(x)``.  The head is
reduced, and where the one class-namespace lookup on the value's type decides
that it binds no ``__enter__`` (or no ``__exit__``), the ``with`` raises the
interpreter's own ``TypeError`` ("'X' object does not support the context
manager protocol", or "... (missed __exit__ method)") before any enter and
before the body (``ReducedManagerProtocolV1``, #7757).

A same-file class's call result is the dispatched manager (#8744): its
``__enter__``/``__exit__`` are calls joined at prove, where the lookup that
finds none is decided, so no TypeError is decided at lift for it.

What a decorated function's call returns is the one decorator application's
(``DecoratorApplicationSugar``, #7757): no proof is read from a decorator's
body.
"""

from __future__ import annotations

from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.manager_protocol_absence_refusal import (
    cited_language_base,
    observed_non_manager_with_refusal,
)

from test_assignment_evaluates_rhs import _rows
from test_undetermined_raise_except_matching import _exits

def _split(tmp_path, source):
    rows = _rows(_exits(tmp_path, source))
    returns = [payload for kind, payload, _ in rows if kind == "return"]
    halts = [payload for kind, payload, _ in rows if kind == "halt"]
    return returns, halts


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


def test_contextmanager_is_still_a_manager(tmp_path):
    source = (
        "import contextlib\n@contextlib.contextmanager\ndef cm():\n    yield 1\n"
        "def f():\n    with cm():\n        return 1\n"
    )
    returns, _ = _split(tmp_path, source)
    assert returns == [TermValue(1)]
