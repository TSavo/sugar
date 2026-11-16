"""`is` / `is not` identity comparisons, and the None / float literals they need.

`is`/`is not` stand on the is_identical floor (`is not` negated); `in`/`not in`
(membership) are not owned yet and stay loud. None -> NoneValue, a float -> a
Real-sorted TermValue (int -> Int, float -> Real, no Number sort).
"""

import tempfile
from pathlib import Path

from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.outcome import Completed

from native_carrier_testimony import undecided_function_value


def _fn(src):
    # The one construction door, under a workspace: an ``assert`` halts at a
    # ground ``AssertionError`` exit whose locus is workspace-relative.
    root = Path(tempfile.mkdtemp())
    path = root / "m.py"
    path.write_text(src, encoding="utf-8")
    return next(open_source_file_for_construction(path, root=root).functions())


def _inv(src):
    """The fact of the one completed arm.  ``is`` decides without a dunder,
    so nothing but the ``assert`` itself can halt: it raises
    ``AssertionError`` under the fact's complement (#7757: a halt is never
    dropped), and the body completes under the fact."""
    outcome = _fn(src).sugar().desugar().normalize()
    completed = [exit_ for exit_ in outcome.exits if isinstance(exit_, Completed)]
    assert len(completed) == 1, outcome.exits
    assert [halt.effect.exception_name for halt in outcome.halts()] == [
        "AssertionError"
    ], outcome.exits
    return completed[0].value.invs()[0]


def test_is_is_identity():
    inv = _inv("def A(z):\n    assert z is None\n    return z\n")
    assert inv.name == "identity"
    assert inv.args[1].name == "None"


def test_is_not_is_identity_negated():
    inv = _inv("def A(z):\n    assert z is not None\n    return z\n")
    assert inv.kind == "not" and inv.operands[0].name == "identity"


def test_float_literal_is_real_sorted():
    post = _fn("def A():\n    return 2.5\n").sugar().desugar().completed_value().post()
    assert type(post.args[1]).__name__ == "_ConstReal"


def test_membership_lifts_for_a_symbolic_container():
    """Formal membership waits on no caller: ``x in xs`` is the undecided
    membership's two faces, ``py.in(x, xs)`` completing only under its own
    completes atom (#7757, audit row NEW-1)."""
    inv = undecided_function_value(
        _fn("def A(x, xs):\n    assert x in xs\n    return x\n"),
        owner="UndecidedCompare:In",
    ).invs()[0]
    # Keyed per evaluation (#7757 NEW-1): the truth of
    # ``python:compare_result("In", x, xs, <key>)``.
    assert inv.name == "python:truth_result"
    compared = inv.args[0]
    assert compared.name == "python:compare_result"
    assert compared.args[0].value == "In"
    item, container = compared.args[1:-1]
    assert item.name == "x"
    assert container.name == "xs"


if __name__ == "__main__":
    test_is_is_identity()
    test_is_not_is_identity_negated()
    test_float_literal_is_real_sorted()
    test_membership_lifts_for_a_symbolic_container()
    print("ok: is/is not identity, None + float literals, membership loud")
