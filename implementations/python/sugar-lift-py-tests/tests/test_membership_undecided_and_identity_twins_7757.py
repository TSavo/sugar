"""Twins: membership over a decided container keeps its halt, and a class or
function is a member like any object (#7757 H10, H11).

H10.  ``membership`` answered a decided list/tuple/set/dict display holding
an undecided member (``1 in [a]``, ``k in (a, b)``, ``1 in {a}``, a
``match`` mapping key over ``{a: 1}``) with a bare ``python.<kind>.contains``
predicate: one completed face.  The compare sugar added the halt back only
when the needle's or the container's own type was undecided, and a
``match`` mapping key never reached that post-pass.  Python runs
``1 == a``, which reflects to ``type(a).__eq__`` (and ``hash`` first for a
set or dict): user code that may raise.  Now the undecided arm is the
floor's one undecided membership (``FloorValue.undecided_contains``):
two-faced, the halt kept, owed.  A list or tuple compares in order, so it
still matches at a decided first member; a set or dict probes by hash, so a
needle whose hash is not decided, or any undecided member, is undecided.

H11.  ``member_equal`` has no value equality for a class, a function or a
bound method, and every ``*.contains`` turned that into a construction
panic: ``type(x) in (int, float)``, ``cls in (A, B)``, ``f in handlers``
refused.  Now ``==`` there is identity where Python answers it so
(``object_identity.equality_by_identity``: a class whose metaclass is
decided to be ``type``), else undecided.  Never a panic.

A lying claim is never ``sat``; a truthful one is never ``unsat``.  Each
half goes through ``run_source_through_real_solver``: real ``sugar mint``
then real ``sugar prove``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from frame_fresh import fresh
from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    prove_verdict,
    run_source_through_real_solver,
)

# A member whose ``__eq__`` raises and whose hash collides with ``1``.
_BOOM = (
    "class Boom:\n"
    "    def __hash__(self):\n"
    "        return 1\n"
    "\n"
    "    def __eq__(self, other):\n"
    '        raise ValueError("no eq")\n'
    "\n"
    "\n"
)

_RAISES_TEST = (
    "def test_f():\n"
    "    try:\n"
    "        f(Boom())\n"
    "        ok = True\n"
    "    except ValueError:\n"
    "        ok = False\n"
    "    assert {claim}\n"
)

# ``name: (source, truthful claim, lying claim)``.  Braces are doubled: the
# source is a ``str.format`` template.
_SHAPES = {
    # H10: a formal inside a list display.
    "list-display-holding-a-formal-keeps-its-halt": (
        _BOOM + "def f(a):\n    return 1 in [a]\n\n\n" + _RAISES_TEST,
        "not ok",
        "ok",
    ),
    # H10: a formal inside a tuple display.
    "tuple-display-holding-a-formal-keeps-its-halt": (
        _BOOM + "def f(a):\n    return 1 in (a, 2)\n\n\n" + _RAISES_TEST,
        "not ok",
        "ok",
    ),
    # H10: a set probes by hash; ``Boom``'s hash collides with ``1``'s.
    "set-display-holding-a-formal-keeps-its-halt": (
        _BOOM + "def f(a):\n    return 1 in {{a}}\n\n\n" + _RAISES_TEST,
        "not ok",
        "ok",
    ),
    # H10: a ``match`` mapping key test over a dict holding a formal key.
    "match-mapping-key-over-a-formal-key-keeps-its-halt": (
        _BOOM
        + "def f(a):\n"
        "    match {{a: 1}}:\n"
        "        case {{1: _}}:\n"
        "            return True\n"
        "    return False\n"
        "\n"
        "\n" + _RAISES_TEST,
        "not ok",
        "ok",
    ),
    # H10: the value face of the same test.
    "list-display-holding-a-formal-value": (
        "def f(a):\n"
        "    return 1 in [a]\n"
        "\n"
        "\n"
        "def test_f():\n"
        "    assert {claim}\n",
        "f(1) == True",
        "f(2) == True",
    ),
    # H11: ``type(x)`` against builtin classes.
    "type-of-a-formal-in-a-tuple-of-builtin-classes": (
        "def f(x):\n"
        "    return type(x) in (int, float)\n"
        "\n"
        "\n"
        "def test_f():\n"
        "    assert {claim}\n",
        "f(1) == True",
        'f("a") == True',
    ),
    # H11: a source class against source classes.
    "source-class-in-a-tuple-of-source-classes": (
        "class C:\n"
        "    pass\n"
        "\n"
        "\n"
        "class D:\n"
        "    pass\n"
        "\n"
        "\n"
        "def f():\n"
        "    return (C in (C, D), D in (C,))\n"
        "\n"
        "\n"
        "def test_f():\n"
        "    assert {claim}\n",
        "f() == (True, False)",
        "f() == (False, True)",
    ),
    # H11: a function against functions.
    "function-in-a-list-of-functions": (
        "def g():\n"
        "    return 1\n"
        "\n"
        "\n"
        "def h():\n"
        "    return 2\n"
        "\n"
        "\n"
        "def f():\n"
        "    return h in [g, h]\n"
        "\n"
        "\n"
        "def test_f():\n"
        "    assert {claim}\n",
        "f() == True",
        "f() == False",
    ),
}


def _claims_line(source: str) -> int:
    """The line of the test function's ``def``: it follows the helpers."""
    for number, line in enumerate(source.splitlines(), start=1):
        if line.startswith("def test_"):
            return number
    raise AssertionError("the source states no test function")


@pytest.mark.parametrize("half", ["truthful", "lying"])
@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_membership_never_admits_a_lie_nor_refutes_a_truth(
    tmp_path: Path, shape: str, half: str
) -> None:
    source, truthful, lying = _SHAPES[shape]
    text = source.format(claim=truthful if half == "truthful" else lying)
    result = run_source_through_real_solver(tmp_path / shape / half, text)
    verdict = claim_verdict(result.prove_doc, claims_from_line=_claims_line(text))
    whole = prove_verdict(result.prove_doc)
    if half == "lying":
        assert verdict != "sat", result.prove_doc
        assert whole != "sat", result.prove_doc
    else:
        assert verdict != "unsat", result.prove_doc
        assert whole != "unsat", result.prove_doc


def assert_undecided_membership(outcome) -> None:
    """The floor's one undecided membership: the keyed ``py.in`` truth
    completes only under ``python:compare.completes``, and an undetermined
    halt (owner ``UndecidedCompare:In``) stands under the complement, owed
    either way.  Never a bare predicate, never a construction panic."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted

    assert isinstance(outcome, ExitSet)
    (completed,) = [face for face in outcome.exits if isinstance(face, Completed)]
    (halted,) = [face for face in outcome.exits if isinstance(face, Halted)]
    assert completed.guard.name == "python:compare.completes"
    assert completed.value.formula.name == "python:truth_result"
    assert completed.value.formula.args[0].name == "python:compare_result"
    assert completed.value.formula.args[0].args[0].value == "In"
    assert isinstance(halted.effect, UndeterminedRaiseEffect)
    assert halted.effect.producer_node_owner == "UndecidedCompare:In"
    for arm in outcome.exits:
        assert arm.owed, arm


def _symbolic(name="a"):
    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.ir import make_var

    return SymbolicValue(make_var(name))


def test_a_decided_first_member_matches_before_an_undecided_one() -> None:
    """``1 in [1, a]`` stops at the first member: ``1 is 1``."""
    from sugar_lift_py_tests.floor import ListValue, TermValue
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    outcome = fresh(ListValue, (TermValue(1), _symbolic())).contains(
        TermValue(1), "site"
    )
    assert isinstance(outcome.completed_value(), TrueBoolLiteralSugar)


def test_an_undecided_member_before_a_match_is_the_undecided_membership() -> None:
    """``1 in [a, 1]`` runs ``1 == a`` first."""
    from sugar_lift_py_tests.floor import ListValue, TermValue

    assert_undecided_membership(
        fresh(ListValue, (_symbolic(), TermValue(1))).contains(TermValue(1), "site")
    )


@pytest.mark.parametrize("kind", ["tuple", "set", "dict"])
def test_an_undecided_member_of_any_display_is_the_undecided_membership(kind) -> None:
    from sugar_lift_py_tests.floor import DictValue, SetValue, TermValue, TupleValue

    member = _symbolic()
    container = {
        "tuple": lambda: TupleValue((member, TermValue(2))),
        "set": lambda: fresh(SetValue, (TermValue(1), member)),
        "dict": lambda: fresh(DictValue, ((member, TermValue(1)),)),
    }[kind]()
    assert_undecided_membership(container.contains(TermValue(1), "site"))


def test_a_needle_whose_hash_is_undecided_in_an_empty_set_keeps_its_halt() -> None:
    """``x in set()`` hashes ``x`` first: ``type(x).__hash__`` may raise."""
    from sugar_lift_py_tests.floor import SetValue

    assert_undecided_membership(fresh(SetValue, ()).contains(_symbolic("x"), "site"))


def test_decided_members_still_decide() -> None:
    from sugar_lift_py_tests.floor import DictValue, SetValue, TermValue
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    numbers = fresh(SetValue, (TermValue(1), TermValue(2)))
    assert isinstance(
        numbers.contains(TermValue(2), "site").completed_value(), TrueBoolLiteralSugar
    )
    assert isinstance(
        numbers.contains(TermValue(3), "site").completed_value(), FalseBoolLiteralSugar
    )
    keys = fresh(DictValue, ((TermValue(1), TermValue(10)),))
    assert isinstance(
        keys.contains(TermValue(9), "site").completed_value(), FalseBoolLiteralSugar
    )
