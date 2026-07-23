"""A slice `lower:upper:step` is the py.slice coordinate; omitted bounds are None."""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile


def _sub(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return (
        next(SourceFile(path_source(path)).functions())
        .sugar()
        .desugar()
        .value.post()
        .args[1]
    )


def test_full_slice():
    sub = _sub("def A(xs):\n    return xs[1:2]\n")
    assert sub.name == "py.subscript"
    sl = sub.args[1]
    assert sl.name == "py.slice"
    assert sl.args[0].value == 1 and sl.args[1].value == 2


def test_omitted_bounds_are_none():
    sl = _sub("def A(xs):\n    return xs[::2]\n").args[1]
    assert sl.name == "py.slice"
    assert sl.args[0].name == "None" and sl.args[1].name == "None"
    assert sl.args[2].value == 2  # step


if __name__ == "__main__":
    test_full_slice()
    test_omitted_bounds_are_none()
    print("ok: slice -> py.slice coordinate")
