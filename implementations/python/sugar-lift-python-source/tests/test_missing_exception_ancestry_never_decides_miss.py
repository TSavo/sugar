"""Missing exception ancestry never decides that an ``except`` arm misses.

``_matches_single_raise_effect`` read an absent ``exception_type_mro`` as the
empty ancestry, so ``raise JSONDecodeError`` / ``except ValueError`` was a
decided miss and the function lifted as always raising -- but
``JSONDecodeError`` IS a ``ValueError``. Three sources of that false miss are
closed here:

- an import-bound raised class has no ancestry testimony at all; the arm now
  retains ``adt.is_python_type(raised, handler)`` and both faces survive;
- a source class's ancestry stopped at its first builtin base (``class
  E(ValueError)`` did not reach ``Exception``) and was returned truncated when a
  base could not be walked; builtin bases now splice the language's own
  ancestry, and an unwalkable base leaves the whole ancestry unavailable;
- ``IOError`` / ``EnvironmentError`` minted identities of classes that do not
  exist; Python binds both names to ``OSError``.

A closed ancestry still decides a miss against a canonical (builtin or source
class) handler; an ``import`` handler coordinate names a path, not a class, so
it never settles a miss.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.outcome import Completed, Halted
from sugar_source_tree.nodes import FunctionDef, Name

from test_contextlib_suppress_source_exit_faces import _corpus, _open


def _source_file(tmp_path: Path, source: str):
    return _open(_corpus(tmp_path, source))


def _exits(tmp_path: Path, source: str):
    source_file = _source_file(tmp_path, source)
    func = next(
        n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    return func.sugar().desugar()


def _try(raise_line: str, handler: str, prelude: str = "") -> str:
    return (
        f"{prelude}def f():\n"
        "    try:\n"
        f"        {raise_line}\n"
        f"    except {handler}:\n"
        "        return 1\n"
    )


def _is_split_by_retained_type_test(exits) -> bool:
    completed = [face for face in exits.exits if isinstance(face, Completed)]
    halted = [
        face
        for face in exits.exits
        if isinstance(face, Halted) and isinstance(face.effect, RaiseEffect)
    ]
    # The caught return is the try's own completed face, guarded by the
    # retained type test; the escaping halt carries the complement.
    return (
        len(completed) == 1
        and len(halted) == 1
        and getattr(completed[0].guard, "name", None) == "adt.is_python_type"
        and getattr(halted[0].guard, "kind", None) == "not"
        and "adt.is_python_type" in repr(halted[0].guard)
    )


@pytest.mark.parametrize(
    "prelude, raise_line",
    [
        ("from json import JSONDecodeError\n", "raise JSONDecodeError"),
        ("import json\n", "raise json.JSONDecodeError"),
        (
            "from json import JSONDecodeError\nclass E(JSONDecodeError):\n    pass\n",
            'raise E("m", "d", 0)',
        ),
        (
            "import json\nclass E(json.JSONDecodeError):\n    pass\n",
            'raise E("m", "d", 0)',
        ),
    ],
    ids=["imported-name", "imported-attribute", "local-sub-of-imported", "local-sub-of-dotted"],
)
def test_unauthenticated_ancestry_retains_the_match(tmp_path, prelude, raise_line) -> None:
    exits = _exits(tmp_path, _try(raise_line, "ValueError", prelude))
    assert _is_split_by_retained_type_test(exits)


@pytest.mark.parametrize(
    "prelude, raise_line, handler",
    [
        ("class E(ValueError):\n    pass\n", "raise E()", "Exception"),
        ("class E(ValueError):\n    pass\n", "raise E()", "BaseException"),
        (
            "class B(KeyError):\n    pass\nclass E(B):\n    pass\n",
            "raise E()",
            "LookupError",
        ),
        ("", "raise IOError()", "OSError"),
        ("", "raise OSError()", "IOError"),
        ("", "raise FileNotFoundError()", "EnvironmentError"),
    ],
    ids=["source-sub-exception", "source-sub-base", "source-chain", "ioerror", "oserror", "envalias"],
)
def test_authenticated_ancestry_decides_the_match(tmp_path, prelude, raise_line, handler) -> None:
    exits = _exits(tmp_path, _try(raise_line, handler, prelude))
    assert exits.exits and all(isinstance(face, Completed) for face in exits.exits)


@pytest.mark.parametrize(
    "prelude, raise_line, handler",
    [
        ("", "raise KeyError()", "ValueError"),
        ("class E(ValueError):\n    pass\n", "raise E()", "KeyError"),
    ],
    ids=["builtin", "source-class"],
)
def test_closed_ancestry_still_decides_a_miss(tmp_path, prelude, raise_line, handler) -> None:
    exits = _exits(tmp_path, _try(raise_line, handler, prelude))
    assert exits.exits and all(
        isinstance(face, Halted) and isinstance(face.effect, RaiseEffect)
        for face in exits.exits
    )


def test_import_handler_coordinate_never_settles_a_miss(tmp_path) -> None:
    exits = _exits(
        tmp_path, _try("raise ValueError()", "json.JSONDecodeError", "import json\n")
    )
    assert _is_split_by_retained_type_test(exits)


def test_import_alias_of_the_raised_builtin_is_not_a_miss(tmp_path) -> None:
    # ``socket.error is OSError``: main lifted this as always raising.
    exits = _exits(tmp_path, _try("raise OSError()", "socket.error", "import socket\n"))
    assert _is_split_by_retained_type_test(exits)


def _class_name(source_file, name: str):
    return next(
        n for n in source_file.nodes() if isinstance(n, Name) and n.id == name
    )


def test_source_class_ancestry_splices_builtin_bases(tmp_path) -> None:
    source_file = _source_file(
        tmp_path, "class E(ValueError):\n    pass\ndef f():\n    raise E()\n"
    )
    node = _class_name(source_file, "E")
    mro = repr(source_file.root.unit.exception_type_mro(node))
    for ancestor in ("ValueError", "Exception", "BaseException"):
        assert f"value='{ancestor}'" in mro


@pytest.mark.parametrize(
    "prelude",
    [
        "import json\nclass E(json.JSONDecodeError):\n    pass\n",
        "from json import JSONDecodeError\nclass E(JSONDecodeError):\n    pass\n",
        "from json import JSONDecodeError\nclass B(JSONDecodeError):\n    pass\nclass E(B):\n    pass\n",
    ],
)
def test_unwalkable_base_leaves_ancestry_unavailable(tmp_path, prelude) -> None:
    source_file = _source_file(tmp_path, prelude + "def f():\n    raise E()\n")
    node = _class_name(source_file, "E")
    assert source_file.root.unit.exception_type_mro(node) is None
