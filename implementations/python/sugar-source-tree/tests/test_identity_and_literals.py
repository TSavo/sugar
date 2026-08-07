"""`is` / `is not` identity comparisons, and the None / float literals they need.

`is`/`is not` stand on the is_identical floor (`is not` negated); `in`/`not in`
(membership) are not owned yet and stay loud. None -> NoneValue, a float -> a
Real-sorted TermValue (int -> Int, float -> Real, no Number sort).
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.tree import SourceFile

from native_carrier_testimony import completed_function_value, native_carrier_for


def _fn(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return next(SourceFile(path_source(path), construction_context=TreeConstructionContextV1.for_test_without_workspace()).functions())


def _inv(src):
    return completed_function_value(_fn(src)).invs()[0]


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


def test_membership_lifts_for_a_symbolic_container():
    """Deleted expectation: formal membership immediately projected py.in."""
    carrier = native_carrier_for(
        _fn("def A(x, xs):\n    assert x in xs\n    return x\n"),
        operator="contains",
    )
    container, item = carrier.operands
    assert container.to_term(owner="membership carrier tooth").name == "xs"
    assert item.to_term(owner="membership carrier tooth").name == "x"


if __name__ == "__main__":
    test_is_is_identity()
    test_is_not_is_identity_negated()
    test_float_literal_is_real_sorted()
    test_membership_lifts_for_a_symbolic_container()
    print("ok: is/is not identity, None + float literals, membership loud")
