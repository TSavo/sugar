"""A same-file ``@contextlib.contextmanager`` generator's call is its edge.

A same-module ``@contextmanager`` generator used as a With head still has its
frame seated by the call's name (``call_applies_own_frame``, #7757), but the
call is the definition's coordinate and edge, joined at prove (#7757 step 6,
the owner's ruling of 2026-11-15, "Edge, join at prove"): the generator body
is never run to its first yield at lift.  The With enters the value the head
reduced to (``WithReducedManagerSugar``): a call result whose type nothing
here decides, so ``__enter__`` and ``__exit__`` are each undecided and owed.

The helpers below are shared by the with-head tests of this package.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.outcome import Halted
from sugar_lift_py_tests.sugar.with_source_resource_sugar import (
    WithReducedManagerSugar,
)
from sugar_source_tree.nodes import With

import test_contextlib_suppress_source_exit_faces as opener
from test_contextlib_suppress_source_exit_faces import _corpus


_SUPPRESSES_VALUE_ERROR = (
    "from contextlib import contextmanager\n"
    "@contextmanager\n"
    "def cm():\n"
    "    try:\n"
    "        yield 1\n"
    "    except ValueError:\n"
    "        pass\n"
)


def _with(tmp_path: Path, source: str):
    source_file = opener._open(_corpus(tmp_path, source))
    return source_file, next(n for n in source_file.nodes() if isinstance(n, With))


def _imported(tmp_path: Path, implementation: str, body: str, *, contextlib_enrolled):
    """``with cm():`` over the manager ``implementation`` defines.

    No dependency body is ever read (#7757): an imported call answers from
    the import table and the imported proofs only.  So the manager's source
    stands in the consumer's own file, and its call is its coordinate and
    edge like any same-file call (#7757 steps 5 and 6).  The consumer is constructed under the step-3 table
    its own ``with`` items enroll (the undecided row: the manager is what the
    head reduces to).  ``contextlib_enrolled`` changes nothing it constructs."""
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_source_tree.tree import SourceFile

    del contextlib_enrolled
    consumer = (
        f"{implementation}\n"
        f"def f():\n    with cm():\n        {body}\n    return 7\n"
    )
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    context = TreeConstructionContextV1()
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=context,
    )
    # The consumer's own ``with``: the last ``with cm():`` line of the file.
    lines = consumer.splitlines()
    line = len(lines) - lines[::-1].index("    with cm():")
    return tree, next(
        n for n in tree.nodes() if isinstance(n, With) and n.lineno == line
    )


def _manager(header: str, body: str) -> str:
    return f"{header}def f():\n    with cm():\n        {body}\n    return 7\n"


def _function_rows(source_file, with_node):
    """Every return/halt ``f`` can leave by (the reader both consumers share)."""
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_source_tree.nodes import FunctionDef

    func = next(
        n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    rows = []
    for face in func.sugar().desugar().exits:
        if isinstance(face, Halted):
            rows.append(("halt", getattr(face.effect, "exception_name", None)))
            continue
        for entry in getattr(getattr(face.value, "record", None), "statements", ()):
            name = type(entry).__name__
            if name in ("ReturnValue", "GuardedReturn") and "value=7)" in repr(
                entry.value
            ):
                rows.append(("return", 7))
            elif isinstance(entry, ExitSet) and entry.halts() == entry.exits:
                for halt in entry.halts():
                    rows.append(("halt", getattr(halt.effect, "exception_name", None)))
    return type(with_node.sugar()), sorted(rows, key=lambda row: (row[0], str(row[1])))


def test_a_local_contextmanager_call_is_its_edge(tmp_path):
    """Verdict moved (#7757 step 6): the With over a same-file
    ``@contextmanager`` generator was ``GeneratorWithSugar``, which ran the
    generator to its first yield and split the body's raise on its ``except``
    arms.  The head's call is now the definition's edge, and the With enters
    the value it reduced to: an undecided manager, owed."""
    opened = _with(tmp_path, _manager(_SUPPRESSES_VALUE_ERROR, "pass"))
    sugar, rows = _function_rows(*opened)
    assert sugar is WithReducedManagerSugar
    assert ("halt", None) in rows


def test_an_undecorated_local_generator_head_is_the_undecided_manager(tmp_path):
    """Verdict moved (#7757 step 6): ``cm()`` of an undecorated generator
    function was decided to return a generator object, so the With raised
    TypeError before enter and body (``GeneratorObjectWithSugar``).  What the
    call returns is now what ``cm``'s contract states, joined at prove: here
    the With enters an undecided manager, and no TypeError is decided."""
    source_file, with_node = _with(
        tmp_path,
        "def cm():\n    yield 1\ndef f():\n    with cm():\n        pass\n    return 7\n",
    )
    sugar, rows = _function_rows(source_file, with_node)
    assert sugar is WithReducedManagerSugar
    assert ("halt", "TypeError") not in rows
    assert ("halt", None) in rows
