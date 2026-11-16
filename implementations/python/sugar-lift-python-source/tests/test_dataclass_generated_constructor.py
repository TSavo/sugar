"""``@dataclasses.dataclass`` writes the constructor its fields spell (#7665).

``pandas.io.common._get_filepath_or_buffer`` returns
``IOArgs(filepath_or_buffer=..., encoding=..., ...)``; ``IOArgs`` has no
source ``__init__``: Lib/dataclasses.py ``_init_fn`` writes
``__init__(self, f1, f2=<default>, ...)`` from the class's annotated fields in
order, one ``self.f = f`` store each, and ``field(default_factory=F)`` calls
``F()`` when the argument is omitted.

Only the bare stdlib decorator is modelled; any decorator argument, a source
``__post_init__``, a default that is not a constant, or a factory that is not
a bare name leaves the written ``__init__`` undecided.

What a call of the class does is the class's constructor contract, joined at
prove (#7757 steps 6 and 9): a call of a same-file class is its coordinate
and edge, and no caller follows a manager's or a constructor's body at lift.
So these read the one place the lifter decides the written ``__init__``,
``ClassDef._dataclass_generated_init_fields``, the fields the class's
constructor frame binds.
"""

from __future__ import annotations

import pytest

from sugar_source_tree.nodes import ClassDef

from test_decorator_and_annotation_known_by_binding import _node


def _impl(decorator: str, fields: str) -> str:
    return (
        "import dataclasses\n"
        "from typing import Generic, TypeVar\n"
        "T = TypeVar('T')\n"
        f"{decorator}\n"
        "class Args(Generic[T]):\n"
        f"{fields}"
    )


_FIELDS = (
    "    a: int\n"
    "    b: int = 2\n"
    "    c: list = dataclasses.field(default_factory=list)\n"
)


def _fields(source: str):
    _, args = _node(source, ClassDef, "Args")
    return args._dataclass_generated_init_fields()


def test_fields_are_the_constructor_parameters() -> None:
    # The written ``__init__(self, a, b=2, c=<list()>)``: the fields in
    # source order, the constant default stored as written, and the factory
    # the frame calls when the argument is omitted.
    fields = _fields(_impl("@dataclasses.dataclass", _FIELDS))
    assert fields is not None
    assert tuple(name for name, *_ in fields) == ("a", "b", "c")
    (_, _, a_default, a_factory), (_, _, b_default, b_factory), (
        _,
        _,
        c_default,
        c_factory,
    ) = fields
    assert a_default is None and a_factory is None
    assert b_default.value == 2 and b_factory is None
    assert c_default is None and c_factory.id == "list"


_UNMODELLED = (
    ("@dataclasses.dataclass(frozen=True)", _FIELDS),
    ("@dataclasses.dataclass", _FIELDS + "    def __post_init__(self):\n        self.b = 0\n"),
    ("@dataclasses.dataclass", "    a: int\n    b: int = len('xy')\n"),
    ("@dataclasses.dataclass", "    a: int\n    b: int = dataclasses.field(default_factory=lambda: 2)\n"),
)


@pytest.mark.parametrize(("decorator", "fields"), _UNMODELLED)
def test_unmodelled_dataclass_shapes_write_no_init(decorator, fields) -> None:
    # Nothing here models the shape exactly, so no ``__init__`` is written:
    # the class call stays the one unanswered call, never a frame built as
    # if the fields were plain.
    assert _fields(_impl(decorator, fields)) is None
