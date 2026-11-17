"""A read of a module attribute the import system set is the one undecided
read off the module, never the free name (#7757, carry undecided).

The nine-step lane (main 13e3413ad) refused 36 functions and classes by
``proofir.scope.ScopedFormula`` with ``illegal free var(s): __file__`` (pandas
13, numpy 23: ``os.path.dirname(__file__)`` in a function, ``HERE =
os.path.abspath(os.path.dirname(__file__))`` at module level, read on by a
class), and one by ``__builtins__`` (``getattr(__builtins__, '__dict__',
__builtins__)``).  The import system binds these in the module's own
namespace before the body runs; nothing in the source binds them, so the
read fell through to ``NameSugar``'s free ``Var``.

Each read is now the two-faced undecided read of that attribute off the
module (``python:module(<m>)``): it completes with an uninterpreted result
under its completes atom, halts with an undetermined raise under the
complement, and owes the ``undecided`` member.  No path or module name is
decided, and no ``NameError`` is named.

``__name__``, ``__doc__``, ``__spec__``, ``__loader__`` and ``__package__``
are spelled in the builtin namespace too (``builtins.__name__ ==
"builtins"``); a module's read of one reaches its own namespace first, so it
is no longer the builtin's (``builtin_reference_at``).

THE DISCRIMINATION: a source binding of the name (a module assignment, a
parameter, a ``global`` writer) and a star import keep their own binding.
"""

from __future__ import annotations

from sugar_source_tree.nodes import Name

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect

from test_import_bound_callee_is_closed import _function_outcome
from test_module_global_evaluation_reference import _source
from test_undecided_binding_reads import _completed_posts_are_scoped

_MODULE = "module_global_evaluation"


def _reads(text: str, name: str):
    """``(unit, [span of every read of name])`` for ``text``."""
    tree = _source(text)
    spans = [
        node.line_col_span()
        for node in tree.nodes()
        if isinstance(node, Name) and node.id == name
    ]
    assert spans, text
    return tree.unit, spans


def _reached(text: str, name: str) -> list:
    unit, spans = _reads(text, name)
    return [unit.interpreter_module_attribute_at(name, span) for span in spans]


def test_a_file_read_in_a_function_is_the_module_attribute() -> None:
    assert _reached("def f():\n    return __file__\n", "__file__") == [_MODULE]


def test_a_file_read_at_module_level_is_the_module_attribute() -> None:
    assert _reached("import os\n\nHERE = os.path.dirname(__file__)\n", "__file__") == [
        _MODULE
    ]


def test_builtins_name_and_spec_are_module_attributes() -> None:
    for name in ("__builtins__", "__name__", "__spec__", "__doc__"):
        assert _reached(f"def f():\n    return {name}\n", name) == [_MODULE], name


def test_a_module_name_read_is_never_the_builtin_namespace_attribute() -> None:
    # ``builtins.__name__`` is "builtins"; the module's own ``__name__``
    # shadows it.  The builtin reference is withheld for every module
    # attribute the import system sets.
    unit, (span,) = _reads("def f():\n    return __name__\n", "__name__")
    assert unit.builtin_reference_at("__name__", span) is None
    # A true builtin is still the builtin.
    unit, (span,) = _reads("def f():\n    return len\n", "len")
    assert unit.builtin_reference_at("len", span) == "python:builtins.len"


def test_a_source_binding_keeps_the_name() -> None:
    # THE DISCRIMINATION: the source binds it, so the read is that binding.
    bound = (
        ("__file__ = 'x'\n\n\ndef f():\n    return __file__\n", "__file__"),
        ("def f(__file__):\n    return __file__\n", "__file__"),
        (
            "def g():\n    global __doc__\n    __doc__ = 'x'\n\n\n"
            "def f():\n    return __doc__\n",
            "__doc__",
        ),
    )
    for text, name in bound:
        assert set(_reached(text, name)) == {None}, text


def test_a_star_import_keeps_the_name() -> None:
    assert set(
        _reached("from m import *\n\n\ndef f():\n    return __file__\n", "__file__")
    ) == {None}


def test_class_body_names_are_no_module_attributes() -> None:
    assert _reached("class C:\n    x = __qualname__\n", "__qualname__") == [None]


def test_a_file_read_is_two_faced_owed_and_never_the_free_name() -> None:
    outcome = _function_outcome("def f():\n    return __file__\n")
    posts = _completed_posts_are_scoped(outcome)
    assert any("__file__" in repr(post) for post in posts), posts
    assert any(
        isinstance(halt.effect, UndeterminedRaiseEffect) for halt in outcome.halts()
    ), outcome.exits
    assert outcome.owed_items(), outcome.exits


def test_a_builtins_read_through_getattr_is_never_the_free_name() -> None:
    _completed_posts_are_scoped(
        _function_outcome(
            "def f():\n    return getattr(__builtins__, '__dict__', __builtins__)\n"
        )
    )
