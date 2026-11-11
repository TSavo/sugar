"""``@dataclasses.dataclass`` writes the constructor its fields spell (#7665).

``pandas.io.common._get_filepath_or_buffer`` returns
``IOArgs(filepath_or_buffer=..., encoding=..., ...)``; ``IOArgs`` has no
source ``__init__``: Lib/dataclasses.py ``_init_fn`` writes
``__init__(self, f1, f2=<default>, ...)`` from the class's annotated fields in
order, one ``self.f = f`` store each, and ``field(default_factory=F)`` calls
``F()`` when the argument is omitted.  Binding those keyword actuals to the
bare class body was ``call-binding: unconsumed call actual``.

Only the bare stdlib decorator is modelled; any decorator argument, a source
``__post_init__``, or a dataclass base keeps the old refusal.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_source_tree.panic import SourceTreePanic

from test_contextmanager_generator_protocol import _function_rows, _imported


def _impl(decorator: str, fields: str, construct: str, check: str, extra: str = "") -> str:
    return (
        "import dataclasses\n"
        "from typing import Generic, TypeVar\n"
        "T = TypeVar('T')\n"
        f"{decorator}\n"
        "class Args(Generic[T]):\n"
        f"{fields}"
        f"{extra}"
        "class M:\n"
        "    def __init__(self, args):\n"
        "        self.args = args\n"
        "    def __enter__(self):\n"
        f"        if {check}:\n"
        "            raise KeyError(1)\n"
        "        return 1\n"
        "    def __exit__(self, *exc):\n"
        "        return False\n"
        "def cm():\n"
        f"    args = {construct}\n"
        "    return M(args)\n"
    )


_FIELDS = (
    "    a: int\n"
    "    b: int = 2\n"
    "    c: list = dataclasses.field(default_factory=list)\n"
)


def _rows(tmp_path: Path, source: str):
    tree, with_node = _imported(tmp_path, source, "pass", contextlib_enrolled=False)
    return _function_rows(tree, with_node)[1]


@pytest.mark.parametrize(
    ("construct", "check"),
    (
        ("Args(a=1)", "self.args.b != 2"),  # the field default
        ("Args(a=1)", "self.args.a != 1"),  # keyword actual
        ("Args(1, 5)", "self.args.b != 5"),  # positional, in field order
        ("Args(a=1, b=7)", "self.args.b != 7"),
        ("Args(a=1)", "len(self.args.c) != 0"),  # factory called when omitted
    ),
)
def test_fields_are_the_constructor_parameters(tmp_path, construct, check) -> None:
    source = _impl("@dataclasses.dataclass", _FIELDS, construct, check)
    rows = _rows(tmp_path, source)
    # The stored field decides ``__enter__``: it returns, and never raises
    # the KeyError a wrong value would.  (The class body's own
    # ``dataclasses.field(...)`` call keeps its undetermined face: nothing
    # here testifies what that unresolved callee does.)
    assert ("return", 7) in rows
    assert ("halt", "KeyError") not in rows


def test_a_wrong_field_value_reaches_the_raise(tmp_path) -> None:
    source = _impl("@dataclasses.dataclass", _FIELDS, "Args(a=1)", "self.args.b != 3")
    with pytest.raises(SourceTreePanic, match="enter-may-halt"):
        _rows(tmp_path, source)


_UNMODELLED = (
    ("@dataclasses.dataclass(frozen=True)", _FIELDS),
    ("@dataclasses.dataclass", _FIELDS + "    def __post_init__(self):\n        self.b = 0\n"),
    ("@dataclasses.dataclass", "    a: int\n    b: int = len('xy')\n"),
    ("@dataclasses.dataclass", "    a: int\n    b: int = dataclasses.field(default_factory=lambda: 2)\n"),
)


@pytest.mark.parametrize(("decorator", "fields"), _UNMODELLED)
def test_unmodelled_dataclass_shapes_keep_the_refusal(tmp_path, decorator, fields) -> None:
    source = _impl(decorator, fields, "Args(a=1)", "self.args.b != 2")
    with pytest.raises(SourceTreePanic, match="call-binding"):
        _rows(tmp_path, source)
