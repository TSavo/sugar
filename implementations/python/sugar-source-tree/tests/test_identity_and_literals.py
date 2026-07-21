"""`is` / `is not` identity comparisons, and the None / float literals they need.

`is`/`is not` stand on the is_identical floor (`is not` negated); `in`/`not in`
(membership) are not owned yet and stay loud. None -> NoneValue, a float -> a
Real-sorted TermValue (int -> Int, float -> Real, no Number sort).
"""

import tempfile

import pytest

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _fn(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return next(SourceFile(path_source(path)).functions())


def _inv(src):
    return _fn(src).sugar().desugar().value.invs()[0]


def test_is_is_identity():
    inv = _inv("def A(z):\n    assert z is None\n    return z\n")
    assert inv.name == "identity"
    assert inv.args[1].name == "None"


def test_is_not_is_identity_negated():
    inv = _inv("def A(z):\n    assert z is not None\n    return z\n")
    assert inv.kind == "not" and inv.operands[0].name == "identity"


def test_float_literal_is_real_sorted():
    post = _fn("def A():\n    return 2.5\n").sugar().desugar().value.post()
    assert type(post.args[1]).__name__ == "_ConstReal"


def test_membership_stays_loud():
    with pytest.raises(SugarNotWritten):
        _fn("def A(z):\n    assert z in [1, 2]\n    return z\n").sugar()


if __name__ == "__main__":
    test_is_is_identity()
    test_is_not_is_identity_negated()
    test_float_literal_is_real_sorted()
    test_membership_stays_loud()
    print("ok: is/is not identity, None + float literals, membership loud")
