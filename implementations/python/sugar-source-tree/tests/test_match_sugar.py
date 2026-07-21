"""`match` -- the value-pattern subset: sequential, first-case-wins guards.

case i runs when the subject matches P_i AND no earlier case matched, so its
body facts ride under `match_i AND NOT match_<i`. Captures, pattern guards,
and structural patterns stay loud.
"""

import tempfile

import pytest

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile

_MATCH = (
    "def A(z):\n"
    "    match z:\n"
    "        case 1:\n"
    "            assert z == 10\n"
    "        case 2:\n"
    "            assert z == 20\n"
    "        case _:\n"
    "            assert z == 30\n"
    "    return z\n"
)


def _fn(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return next(SourceFile(path_source(path)).functions())


def _invs(src):
    return _fn(src).sugar().desugar().value.invs()


def test_first_case_guarded_by_its_match():
    invs = _invs(_MATCH)
    first = invs[0]
    assert first.kind == "implies"
    assert first.operands[0].name == "py.eq"  # z == 1
    assert first.operands[1].name == "py.eq"  # consequent z == 10
    assert first.operands[1].args[1].value == 10  # body fact z == 10


def test_later_case_excludes_earlier():
    invs = _invs(_MATCH)
    second = invs[1]  # case 2: (not(z==1) and (z==2)) -> z == 20
    assert second.operands[0].kind == "and"
    assert second.operands[0].operands[0].kind == "not"  # not (z == 1)


def test_wildcard_guarded_by_all_negations():
    invs = _invs(_MATCH)
    wild = invs[2]  # case _: (not(z==1) and not(z==2)) -> z == 30
    ante = wild.operands[0]
    assert ante.kind == "and"
    assert all(op.kind == "not" for op in ante.operands)


def test_capture_binds_the_subject():
    # case x: binds x = subject (the temporal half, via substitute). So a
    # `case 1: return 10; case x: return x` capture arm is `not(z==1) -> out==z`.
    post = _fn(
        "def A(z):\n    match z:\n        case 1:\n            return 10\n"
        "        case x:\n            return x\n"
    ).sugar().desugar().value.post()
    capture_arm = post.operands[1]  # the `case x:` implication
    assert capture_arm.operands[0].operands[0].kind == "not"  # guarded by not(z==1)
    assert capture_arm.operands[1].args[1].name == "z"  # out == z (x = subject)


def test_structural_pattern_stays_loud():
    with pytest.raises(SugarNotWritten):
        _fn("def A(z):\n    match z:\n        case [a, b]:\n            return a\n").sugar()


def test_pattern_guard_stays_loud():
    with pytest.raises(SugarNotWritten):
        _fn("def A(z):\n    match z:\n        case 1 if z > 0:\n            return z\n").sugar()


def test_singleton_pattern_none_and_bool():
    invs = _invs(
        "def A(z):\n    match z:\n        case None:\n            assert z == 0\n"
        "        case True:\n            assert z == 1\n"
        "        case _:\n            assert z == 2\n    return z\n"
    )
    assert invs[0].operands[0].name == "py.eq"  # z == None
    assert invs[0].operands[0].args[1].name == "None"
    assert invs[1].operands[0].kind == "and"  # excluded by not(z==None), then z==True


def test_or_pattern_disjoins_alternatives():
    invs = _invs(
        "def A(z):\n    match z:\n        case 1 | 2 | 3:\n            assert z == 100\n"
        "        case _:\n            assert z == 200\n    return z\n"
    )
    ante = invs[0].operands[0]
    assert ante.kind == "or" and len(ante.operands) == 3
    assert all(op.name == "py.eq" for op in ante.operands)


if __name__ == "__main__":
    test_first_case_guarded_by_its_match()
    test_later_case_excludes_earlier()
    test_wildcard_guarded_by_all_negations()
    test_capture_binds_the_subject()
    test_structural_pattern_stays_loud()
    test_pattern_guard_stays_loud()
    test_singleton_pattern_none_and_bool()
    test_or_pattern_disjoins_alternatives()
    print("ok: match value patterns -- sequential guarded split; the rest loud")
