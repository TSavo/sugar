"""Member access on an OPAQUE object is a symbolic read, not a gap.

`OpaqueObjectStateV1` is an authenticated call-result identity with no field
testimony: statically we know only WHICH call produced it, never its fields --
those come into existence at runtime, observed by the witness. So `opaque.attr`
and `opaque[key]` must NOT raise SugarNotWritten (the old withhold); they
construct the honest EUF coordinate `py.getattr(recv, "attr")` /
`py.subscript(recv, key)`, carrying the opaque call term and nothing invented.

A free-function call `g(x)` is the deterministic opaque receiver (no vendor,
no numpy): its result has no field testimony, exactly like `np.asarray(...)`.
"""

import os
import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.ir import (
    atomic as _atomic,
    ctor as _ctor,
    make_var,
    num,
    str_const,
    eq as _eq,
)


def _post_of(src):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "m.py")
    open(p, "w").write(src)
    fn = list(SourceFile(path_source(p)).functions())[0]
    return fn.sugar().desugar(None).value.post()


def test_opaque_attribute_is_getattr_not_gap():
    # `g(x).foo` -- attribute on an opaque call result -- projects the honest
    # symbolic read, NOT SugarNotWritten and NOT a fabricated field value.
    post = _post_of("def f(x):\n    return g(x).foo\n")
    expected = _eq(
        make_var("out"),
        _ctor("py.getattr", [_ctor("call:g", [make_var("x")]), str_const("foo")]),
    )
    assert post == expected, f"post was {post!r}"


def test_opaque_subscript_is_subscript_not_gap():
    # `g(x)[0]` -- subscript on an opaque call result -- projects py.subscript.
    post = _post_of("def f(x):\n    return g(x)[0]\n")
    expected = _eq(
        make_var("out"),
        _ctor("py.subscript", [_ctor("call:g", [make_var("x")]), num(0)]),
    )
    assert post == expected, f"post was {post!r}"


def test_opaque_member_access_no_longer_raises():
    # The discrimination against the OLD behavior: the guard used to raise
    # SugarNotWritten on any opaque receiver. Construction must now complete.
    from sugar_source_tree.panic import SugarNotWritten

    try:
        _post_of("def f(x):\n    return g(x).foo\n")
    except SugarNotWritten as e:  # pragma: no cover - the regression tripwire
        raise AssertionError(f"opaque member access wrongly withheld: {e}")


def test_opaque_attribute_congruence():
    # Same attribute on the SAME opaque call is the SAME term (equal-in-equal-out
    # one level up). Two `g(x).foo` reads produce identical coordinates.
    a = _post_of("def f(x):\n    return g(x).foo\n")
    b = _post_of("def f(x):\n    return g(x).foo\n")
    assert a == b


def test_opaque_attribute_name_is_carried_verbatim():
    # The attribute name is a static identifier carried onto the coordinate,
    # never desugared: `.bar` yields "bar", distinct from `.foo`.
    post = _post_of("def f(x):\n    return g(x).bar\n")
    expected = _eq(
        make_var("out"),
        _ctor("py.getattr", [_ctor("call:g", [make_var("x")]), str_const("bar")]),
    )
    assert post == expected, f"post was {post!r}"


if __name__ == "__main__":
    for name in sorted(n for n in dir() if n.startswith("test_")):
        globals()[name]()
        print("ok:", name)
