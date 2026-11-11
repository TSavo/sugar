"""``name = Class.method`` exports the classmethod bound to ``Class`` (#7667).

Lib/tarfile.py ends ``open = TarFile.open``; ``TarFile.open`` is a
``@classmethod``.  Looking it up on the class runs ``classmethod.__get__``
(Objects/funcobject.c ``cm_descr_get``), which binds the class: calling
``tarfile.open(fileobj=...)`` runs the method with ``cls`` = ``TarFile``.
The export door called that module-level assignment ``dynamic-export``
(pandas tests/io/test_gcs.py, ``with tarfile.open(fileobj=BytesIO(...))``).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from sugar_lift_python_source.dependency_export_adapter import class_bound_classmethod
from sugar_source_tree.panic import SourceTreePanic

from test_contextmanager_generator_protocol import _function_rows, _imported


def _impl(mark: int, export: str = "cm = Box.make\n", decorator: str = "@classmethod") -> str:
    return (
        "class Box:\n"
        "    def __init__(self, v):\n"
        "        self.v = v\n"
        "    def __enter__(self):\n"
        "        if self.v != 1:\n"
        "            raise KeyError(1)\n"
        "        return 1\n"
        "    def __exit__(self, *exc):\n"
        "        return False\n"
        f"    {decorator}\n"
        f"    def make(cls, v={mark}):\n"
        "        return cls(v)\n"
        f"{export}"
    )


def _rows(tmp_path: Path, source: str):
    tree, with_node = _imported(tmp_path, source, "pass", contextlib_enrolled=False)
    return _function_rows(tree, with_node)[1]


def test_cls_is_the_class_the_method_was_looked_up_on(tmp_path) -> None:
    # ``cls(v)`` constructs a ``Box`` from the default ``v=1`` (the caller
    # supplied nothing, so nothing landed on ``cls``'s slot), and its
    # ``__enter__`` returns: no KeyError face.
    assert _rows(tmp_path, _impl(1)) == [("return", 7)]


def test_a_different_default_reaches_the_raise(tmp_path) -> None:
    with pytest.raises(SourceTreePanic, match="enter-may-halt"):
        _rows(tmp_path, _impl(2))


def _shape(source: str):
    tree = ast.parse(source)
    statement = tree.body[-1]
    return class_bound_classmethod(tree.body, statement, "cm")


def test_the_export_door_admits_only_the_exact_shape() -> None:
    assert _shape(_impl(1)) is not None
    # A plain method looked up on the class is the bare function, not bound.
    assert _shape(_impl(1, decorator="@staticmethod")) is None
    # The class name rebound at module level: which class is not decided.
    assert _shape(_impl(1, export="Box = object\ncm = Box.make\n")) is None
    # ``classmethod`` rebound by the module is not the builtin descriptor.
    assert _shape("classmethod = staticmethod\n" + _impl(1)) is None
    # Bound on an instance, or an attribute of something else.
    assert _shape(_impl(1, export="cm = Box(1).make\n")) is None
    assert _shape(_impl(1, export="cm = Box.__init__\n")) is None
