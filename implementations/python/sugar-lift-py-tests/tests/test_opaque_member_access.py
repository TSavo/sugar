"""Opaque member and subscript reads are two-faced (#7585, #7587, #7757 item 13).

An unexecuted call authenticates which call produced the receiver, but not its
runtime type or members.  A completed coordinate alone would silently choose
the success edge; a guessed ``AttributeError`` would silently choose the
failure edge.  Neither is chosen: the lookup completes as the coordinate
``attr:<name>(<receiver>)`` only under ``python:attribute.completes(...)`` and
halts with an ``UndeterminedRaiseEffect`` (no exception type named) under the
complement.
"""

import os
import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1


def _attribute_faces(src):
    directory = tempfile.mkdtemp()
    path = os.path.join(directory, "m.py")
    with open(path, "w", encoding="utf-8") as source_file:
        source_file.write(src)
    function = next(
        SourceFile(
            path_source(path),
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        ).functions()
    )
    return function.sugar().desugar(None)


def _attribute_completion_and_halt(src):
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome import Halted

    exits = _attribute_faces(src).exits
    halts = [
        f
        for f in exits
        if isinstance(f, Halted)
        and isinstance(f.effect, UndeterminedRaiseEffect)
        and f.effect.producer_node_owner == "CallSiteValue.attribute"
    ]
    import re

    # The temporary directory is per run; the source seat is not the claim.
    guards = re.sub(
        r"/tmp/[^/']+/", "<dir>/", " ".join(str(getattr(f, "guard", "")) for f in exits)
    )
    return halts, guards, exits


def test_opaque_attribute_is_two_faced():
    halts, guards, _ = _attribute_completion_and_halt(
        "def f(x):\n    return g(x).foo\n"
    )
    assert len(halts) == 1
    assert "python:attribute.completes" in guards


def test_opaque_subscript_is_two_faced():
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome import Halted

    exits = _attribute_faces("def f(x):\n    return g(x)[0]\n").exits
    halts = [
        f
        for f in exits
        if isinstance(f, Halted) and isinstance(f.effect, UndeterminedRaiseEffect)
    ]
    guards = " ".join(str(getattr(f, "guard", "")) for f in exits)

    assert halts
    assert "python:subscript.completes" in guards
    assert "KeyError" not in repr(halts)
    assert "IndexError" not in repr(halts)


def test_opaque_attribute_names_no_exception_type():
    halts, _, _ = _attribute_completion_and_halt("def f(x):\n    return g(x).foo\n")
    assert "AttributeError" not in repr(halts[0].effect)


def test_opaque_attribute_faces_are_reproducible():
    first = _attribute_completion_and_halt("def f(x):\n    return g(x).foo\n")[1]
    second = _attribute_completion_and_halt("def f(x):\n    return g(x).foo\n")[1]
    assert first == second


def test_opaque_attribute_name_is_carried_verbatim():
    foo = _attribute_completion_and_halt("def f(x):\n    return g(x).foo\n")[1]
    bar = _attribute_completion_and_halt("def f(x):\n    return g(x).bar\n")[1]
    assert "foo" in foo and "bar" not in foo
    assert "bar" in bar


if __name__ == "__main__":
    for name in sorted(n for n in dir() if n.startswith("test_")):
        globals()[name]()
        print("ok:", name)
