"""Opaque member operations refuse until a producer owns their runtime edges.

An unexecuted call authenticates which call produced the receiver, but not its
runtime type or members.  A completed ``py.getattr`` coordinate would silently
choose the success edge; a guessed ``AttributeError`` would silently choose the
failure edge.  Neither choice has source testimony, so both attribute and
subscript operations remain named construction refusals.
"""

import os
import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile


def _attribute_refusal(src):
    from sugar_source_tree.panic import SugarNotWritten

    directory = tempfile.mkdtemp()
    path = os.path.join(directory, "m.py")
    with open(path, "w", encoding="utf-8") as source_file:
        source_file.write(src)
    function = next(SourceFile(path_source(path)).functions())
    try:
        function.sugar().desugar(None)
    except SugarNotWritten as refusal:
        return refusal
    raise AssertionError("opaque member operation invented a completed coordinate")


def _subscript_refusal(src):
    from sugar_source_tree.panic import SugarNotWritten

    directory = tempfile.mkdtemp()
    path = os.path.join(directory, "m.py")
    with open(path, "w", encoding="utf-8") as source_file:
        source_file.write(src)
    function = next(SourceFile(path_source(path)).functions())
    try:
        function.sugar().desugar(None)
    except SugarNotWritten as refusal:
        return refusal
    raise AssertionError("opaque subscript invented a completed coordinate or panic")


def test_opaque_attribute_is_named_undecided():
    info = _attribute_refusal("def f(x):\n    return g(x).foo\n")

    assert info.owner == "CallSiteValue.attribute"
    assert info.observed.endswith("CallSiteValue.foo")
    assert "source-authenticated attribute success or exceptional exit" in (
        info.requested
    )


def test_opaque_subscript_is_named_undecided():
    refusal = _subscript_refusal("def f(x):\n    return g(x)[0]\n")

    assert refusal.owner == "CallSiteValue.subscript"
    assert "undecided receiver runtime type" in refusal.observed
    assert "KeyError" not in refusal.observed
    assert "IndexError" not in refusal.observed


def test_opaque_attribute_uses_the_typed_construction_refusal():
    info = _attribute_refusal("def f(x):\n    return g(x).foo\n")

    assert type(info).__name__ == "SugarNotWritten"
    assert "AttributeError" not in info.observed
    assert "AttributeError" not in info.requested


def test_opaque_attribute_refusal_is_reproducible():
    first = _attribute_refusal("def f(x):\n    return g(x).foo\n")
    second = _attribute_refusal("def f(x):\n    return g(x).foo\n")

    assert (first.owner, first.observed, first.requested) == (
        second.owner,
        second.observed,
        second.requested,
    )


def test_opaque_attribute_name_is_carried_verbatim():
    foo = _attribute_refusal("def f(x):\n    return g(x).foo\n")
    bar = _attribute_refusal("def f(x):\n    return g(x).bar\n")

    assert foo.observed.endswith(".foo")
    assert bar.observed.endswith(".bar")
    assert foo.observed != bar.observed


if __name__ == "__main__":
    for name in sorted(n for n in dir() if n.startswith("test_")):
        globals()[name]()
        print("ok:", name)
