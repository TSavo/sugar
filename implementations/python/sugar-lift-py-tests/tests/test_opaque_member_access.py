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


def _refusal(src):
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    directory = tempfile.mkdtemp()
    path = os.path.join(directory, "m.py")
    with open(path, "w", encoding="utf-8") as source_file:
        source_file.write(src)
    function = next(SourceFile(path_source(path)).functions())
    try:
        function.sugar().desugar(None)
    except ConstructionPanic as panic:
        return panic.info
    raise AssertionError("opaque member operation invented a completed coordinate")


def test_opaque_attribute_is_named_undecided():
    info = _refusal("def f(x):\n    return g(x).foo\n")

    assert info.owner == "CallSiteValue.attribute"
    assert info.observed.endswith("CallSiteValue.foo")
    assert "source-authenticated attribute success or exceptional exit" in (
        info.requested
    )


def test_opaque_subscript_is_named_undecided():
    info = _refusal("def f(x):\n    return g(x)[0]\n")

    assert info.owner == "CallSiteValue.subscript"
    assert "undecided receiver runtime type" in info.observed


def test_opaque_attribute_uses_the_typed_construction_refusal():
    info = _refusal("def f(x):\n    return g(x).foo\n")

    assert info.gap_locus.value == "Construction"
    assert "AttributeError" not in info.observed
    assert "AttributeError" not in info.requested


def test_opaque_attribute_refusal_is_reproducible():
    first = _refusal("def f(x):\n    return g(x).foo\n")
    second = _refusal("def f(x):\n    return g(x).foo\n")

    assert (first.owner, first.observed, first.requested) == (
        second.owner,
        second.observed,
        second.requested,
    )


def test_opaque_attribute_name_is_carried_verbatim():
    foo = _refusal("def f(x):\n    return g(x).foo\n")
    bar = _refusal("def f(x):\n    return g(x).bar\n")

    assert foo.observed.endswith(".foo")
    assert bar.observed.endswith(".bar")
    assert foo.observed != bar.observed


if __name__ == "__main__":
    for name in sorted(n for n in dir() if n.startswith("test_")):
        globals()[name]()
        print("ok:", name)
