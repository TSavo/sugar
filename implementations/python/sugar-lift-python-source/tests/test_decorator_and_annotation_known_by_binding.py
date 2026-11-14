"""A decorator, an annotation marker and a builtin are known by their binding,
never by their spelling (#7757).

``contextlib.contextmanager`` (``call_applies_own_frame``),
``dataclasses.dataclass`` and the field markers it reads by identity
(``ClassDef._dataclass_generated_init_fields``), the ``typing.Final``
qualifier (``value_pins._is_final_annotation``) and the builtin ``open``
are each reached only through the unit's binding lookup
(``SourceUnit.language_callee_of`` / ``builtin_reference_at``): an aliased
import reaches them, a source definition spelled the same does not.
"""

from __future__ import annotations

from sugar_lift_python_source.value_pins import _is_final_annotation
from sugar_source_tree.nodes import (
    AnnAssign,
    Call,
    ClassDef,
    FunctionDef,
    LanguageCallee,
    Name,
    call_applies_own_frame,
)

from test_cited_unreadable_manager import _unit


def _node(source: str, kind, name: str):
    """The first ``kind`` definition named ``name`` in ``source``'s unit."""
    unit = _unit(source)
    for node in unit.typed_module.walk():
        if isinstance(node, kind) and node.name == name:
            return unit, node
    raise AssertionError(f"no {kind.__name__} {name!r}")


def _annotation(source: str, target: str):
    unit = _unit(source)
    for node in unit.typed_module.walk():
        if (
            isinstance(node, AnnAssign)
            and isinstance(node.target, Name)
            and node.target.id == target
        ):
            return node.annotation
    raise AssertionError(f"no annotated {target!r}")


def _open_call(source: str):
    unit = _unit(source)
    for node in unit.typed_module.walk():
        if (
            isinstance(node, Call)
            and isinstance(node.func, Name)
            and node.func.id == "open"
        ):
            return unit, node
    raise AssertionError("no call of open")


# --- contextlib.contextmanager ---


def test_an_aliased_contextmanager_is_recognised():
    unit, g = _node(
        "from contextlib import contextmanager as cm\n\n"
        "@cm\n"
        "def g():\n"
        "    yield 1\n",
        FunctionDef,
        "g",
    )
    assert (
        unit.language_callee_of(g.decorators[0])
        is LanguageCallee.CONTEXTLIB_CONTEXTMANAGER
    )
    assert call_applies_own_frame(g)


def test_a_source_function_named_contextmanager_is_not():
    unit, g = _node(
        "def contextmanager(f):\n"
        "    return f\n\n"
        "@contextmanager\n"
        "def g():\n"
        "    yield 1\n",
        FunctionDef,
        "g",
    )
    assert unit.language_callee_of(g.decorators[0]) is None
    assert not call_applies_own_frame(g)


# --- dataclasses.dataclass and its field markers ---


def test_an_aliased_dataclass_writes_its_init():
    _, point = _node(
        "from dataclasses import dataclass as dc\n\n"
        "@dc\n"
        "class P:\n"
        "    x: int\n",
        ClassDef,
        "P",
    )
    fields = point._dataclass_generated_init_fields()
    assert fields is not None
    assert tuple(name for name, *_ in fields) == ("x",)


def test_a_source_function_named_dataclass_writes_nothing():
    _, point = _node(
        "def dataclass(c):\n"
        "    return c\n\n"
        "@dataclass\n"
        "class P:\n"
        "    x: int\n",
        ClassDef,
        "P",
    )
    assert point._dataclass_generated_init_fields() is None


def test_an_aliased_classvar_is_no_init_field():
    _, point = _node(
        "from dataclasses import dataclass\n"
        "from typing import ClassVar as CV\n\n"
        "@dataclass\n"
        "class P:\n"
        "    x: CV[int] = 0\n",
        ClassDef,
        "P",
    )
    assert point._dataclass_generated_init_fields() is None


def test_a_source_class_named_classvar_is_an_ordinary_field():
    _, point = _node(
        "from dataclasses import dataclass\n\n"
        "class ClassVar:\n"
        "    pass\n\n"
        "@dataclass\n"
        "class P:\n"
        "    x: ClassVar\n",
        ClassDef,
        "P",
    )
    fields = point._dataclass_generated_init_fields()
    assert fields is not None
    assert tuple(name for name, *_ in fields) == ("x",)


# --- typing.Final ---


def test_an_aliased_final_confesses():
    annotation = _annotation("from typing import Final as F\n\nX: F = 1\n", "X")
    assert _is_final_annotation(annotation)


def test_a_source_class_named_final_confesses_nothing():
    annotation = _annotation("class Final:\n    pass\n\nX: Final = 1\n", "X")
    assert not _is_final_annotation(annotation)


# --- the builtin open ---


def test_open_nothing_rebinds_is_the_builtin():
    unit, call = _open_call("def f(p):\n    return open(p)\n")
    assert (
        unit.builtin_reference_at("open", call.func.line_col_span())
        == "python:builtins.open"
    )


def test_a_source_function_named_open_is_not_the_builtin():
    unit, call = _open_call(
        "def open(p):\n    return p\n\ndef f(p):\n    return open(p)\n"
    )
    assert unit.builtin_reference_at("open", call.func.line_col_span()) is None
    assert unit.language_callee_of(call.func) is None
