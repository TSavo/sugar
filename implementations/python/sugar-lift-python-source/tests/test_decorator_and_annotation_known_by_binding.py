"""A decorator, an annotation marker and a builtin are known by their binding,
never by their spelling (#7757).

``contextlib.contextmanager`` (``call_applies_own_frame``),
``dataclasses.dataclass`` and the field markers it reads by identity
(``ClassDef._dataclass_generated_init_fields``) and the builtin ``open``
are each reached only through the unit's binding lookup
(``SourceUnit.language_callee_of`` / ``builtin_reference_at``): an aliased
import reaches them, a source definition spelled the same does not.  An
annotation naming a binding the lifter does not read (an import of a module
other than the markers' own) may be a marker: the dataclass's ``__init__``
is then undecided, never written as if the field were plain.
"""

from __future__ import annotations

from sugar_source_tree.nodes import (
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


def _field_names(source: str):
    """The fields of class ``P``'s dataclass-written ``__init__``, or None
    where that ``__init__`` is undecided (the class call is then the one
    unanswered call, ``builtin_decorator_application``)."""
    _, point = _node(source, ClassDef, "P")
    fields = point._dataclass_generated_init_fields()
    return None if fields is None else tuple(name for name, *_ in fields)


def test_a_marker_imported_through_another_module_leaves_init_undecided():
    # ``typing_extensions.ClassVar`` may be ``typing.ClassVar``: only that
    # module's proof could say, so the field is never read as plain.
    assert (
        _field_names(
            "from dataclasses import dataclass\n"
            "from typing_extensions import ClassVar\n\n"
            "@dataclass\n"
            "class P:\n"
            "    x: ClassVar[int] = 0\n"
        )
        is None
    )
    assert (
        _field_names(
            "import dataclasses\n"
            "import typing_extensions\n\n"
            "@dataclasses.dataclass\n"
            "class P:\n"
            "    x: typing_extensions.ClassVar[int] = 0\n"
        )
        is None
    )


def test_any_annotation_bound_outside_the_read_modules_leaves_init_undecided():
    assert (
        _field_names(
            "from dataclasses import dataclass\n"
            "import numpy as np\n\n"
            "@dataclass\n"
            "class P:\n"
            "    x: np.ndarray\n"
        )
        is None
    )
    # A module-level alias is an assignment, not a binding read here.
    assert (
        _field_names(
            "from dataclasses import dataclass\n"
            "from typing import ClassVar\n\n"
            "CV = ClassVar\n\n"
            "@dataclass\n"
            "class P:\n"
            "    x: CV[int] = 0\n"
        )
        is None
    )


def test_annotations_bound_in_the_read_modules_write_init():
    assert _field_names(
        "from dataclasses import dataclass\n"
        "import typing\n"
        "from typing import Optional\n\n"
        "class Q:\n"
        "    pass\n\n"
        "@dataclass\n"
        "class P:\n"
        "    a: int\n"
        "    b: Optional[Q]\n"
        "    c: typing.List[int]\n"
        "    d: int | None = None\n"
    ) == ("a", "b", "c", "d")


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
