"""Twins: the last four bare-``py.in`` floors answer by the one undecided
membership, and the compare post-pass that patched a halt onto them is gone
(#7757 H10 follow-up).

#9100 made ``floor.membership`` answer an undecided member with the floor's
one undecided membership (``FloorValue.undecided_contains``: two faces, the
halt kept, owed), but four floors still answered a bare ``py.in`` predicate
that ``comparison_op_sugar``'s membership post-pass patched a halt onto -- a
second way:

- ``StringValue.contains`` over a needle whose type is not decided
  (``x in "abc"``: ``str.__contains__`` raises ``TypeError`` for a
  non-``str``);
- ``ComprehensionValue.contains``, in hand or not (``x in [y for y in xs]``:
  a member's ``__eq__`` may raise);
- ``MutableGlobalValue.contains`` for a dict (``k in D`` where another
  function stored a key whose ``__eq__`` raises on a hash collision);
- ``GuardedValue``'s rejoin of those bare arms (``k in (a if c else b)``),
  which panicked outright where an arm was already two-faced.

Each now answers ``undecided_contains`` itself, or its decided True/False,
and the post-pass is deleted.  A lying claim is never ``sat``; a truthful
one is never ``unsat``.  Each half goes through
``run_source_through_real_solver``: real ``sugar mint`` then real
``sugar prove``.
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


def _raises(call: str, exception: str, *, before: str = "") -> str:
    """A test that records whether ``call`` raised ``exception``."""
    return (
        "def test_f():\n"
        + before
        + "    try:\n"
        + f"        {call}\n"
        + "        ok = True\n"
        + f"    except {exception}:\n"
        + "        ok = False\n"
        + "    assert {claim}\n"
    )


_VALUE_TEST = "def test_f():\n    assert {claim}\n"

# ``name: (source, truthful claim, lying claim)``.  Braces are doubled: the
# source is a ``str.format`` template.
_SHAPES = {
    # StringValue: a formal needle in a string raises TypeError for a non-str.
    "formal-needle-in-a-string-keeps-its-type-error": (
        "def f(x):\n"
        '    s = "abc"\n'
        "    return x in s\n"
        "\n"
        "\n" + _raises("f(1)", "TypeError"),
        "not ok",
        "ok",
    ),
    "formal-needle-in-a-string-value": (
        "def f(x):\n"
        '    s = "abc"\n'
        "    return x in s\n"
        "\n"
        "\n" + _VALUE_TEST,
        'f("b") == True',
        'f("z") == True',
    ),
    # MutableGlobalValue: another function stored a colliding key.
    "key-in-a-module-global-dict-another-function-changed": (
        _BOOM + "D = {{}}\n"
        "\n"
        "\n"
        "def put(k):\n"
        "    D[k] = 1\n"
        "\n"
        "\n"
        "def f(k):\n"
        "    return k in D\n"
        "\n"
        "\n" + _raises("f(1)", "ValueError", before="    put(Boom())\n"),
        "not ok",
        "ok",
    ),
    # GuardedValue: each arm is a formal container.
    "key-in-a-conditional-of-two-formals-keeps-its-halt": (
        _BOOM + "def f(k, a, b, c):\n"
        "    return k in (a if c else b)\n"
        "\n"
        "\n" + _raises("f(1, [Boom()], [2], True)", "ValueError"),
        "not ok",
        "ok",
    ),
    "key-in-a-conditional-of-two-formals-value": (
        "def f(k, a, b, c):\n"
        "    return k in (a if c else b)\n"
        "\n"
        "\n" + _VALUE_TEST,
        "f(2, [1], [2], False) == True",
        "f(2, [1], [2], True) == True",
    ),
    # ComprehensionValue: members not in hand.
    "needle-in-a-list-comprehension-over-a-formal-keeps-its-halt": (
        _BOOM + "def f(x, xs):\n"
        "    return x in [y for y in xs]\n"
        "\n"
        "\n" + _raises("f(1, [Boom()])", "ValueError"),
        "not ok",
        "ok",
    ),
    # ComprehensionValue: a generator in hand, an undecided member first.
    "needle-in-a-generator-in-hand-holding-a-formal-keeps-its-halt": (
        _BOOM + "def f(a):\n"
        "    return 1 in (y for y in [a, 1])\n"
        "\n"
        "\n" + _raises("f(Boom())", "ValueError"),
        "not ok",
        "ok",
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


# ---------------------------------------------------------------------------
# Floor units: the four floors' own answers
# ---------------------------------------------------------------------------


def _assert_undecided_membership(outcome) -> None:
    """The floor's one undecided membership: the keyed ``py.in`` truth
    completes only under ``python:compare.completes``, and an undetermined
    halt (owner ``UndecidedCompare:In``) stands under the complement, owed
    either way.  Never a bare predicate."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted

    assert isinstance(outcome, ExitSet)
    assert outcome.completed_value() is None
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


def test_a_formal_needle_in_a_string_is_the_undecided_membership() -> None:
    from sugar_lift_py_tests.floor import StringValue

    _assert_undecided_membership(StringValue("abc").contains(_symbolic("x"), "site"))


def test_a_comprehension_not_in_hand_is_the_undecided_membership() -> None:
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.floor.comprehension_value import ComprehensionValue
    from sugar_lift_py_tests.ir import ctor, make_var

    for kind in ("py.listcomp", "py.setcomp", "py.generatorexp"):
        comprehension = ComprehensionValue(ctor(kind, [make_var("xs")]))
        _assert_undecided_membership(comprehension.contains(TermValue(1), "site"))


def test_a_generator_in_hand_compares_in_order() -> None:
    """``1 in (y for y in [1, a])`` stops at the first member; ``1 in (y for
    y in [a, 1])`` runs ``a == 1`` first.  Before, any decided match won
    whatever came first, dropping the earlier member's halt."""
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.floor.comprehension_value import ComprehensionValue
    from sugar_lift_py_tests.ir import ctor, make_var
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    term = ctor("py.generatorexp", [make_var("own")])
    first = ComprehensionValue(term, finite_elements=(TermValue(1), _symbolic()))
    assert isinstance(
        first.contains(TermValue(1), "site").completed_value(), TrueBoolLiteralSugar
    )
    later = ComprehensionValue(term, finite_elements=(_symbolic(), TermValue(1)))
    _assert_undecided_membership(later.contains(TermValue(1), "site"))


def test_a_comprehension_decided_whole_is_its_display_membership() -> None:
    from sugar_lift_py_tests.floor import ListValue, TermValue
    from sugar_lift_py_tests.floor.comprehension_value import ComprehensionValue
    from sugar_lift_py_tests.ir import ctor, make_var
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    members = (TermValue(1), TermValue(2))
    comprehension = ComprehensionValue(
        ctor("py.listcomp", [make_var("own")]),
        finite_elements=members,
        display=fresh(ListValue, members),
    )
    assert isinstance(
        comprehension.contains(TermValue(2), "site").completed_value(),
        TrueBoolLiteralSugar,
    )
    assert isinstance(
        comprehension.contains(TermValue(3), "site").completed_value(),
        FalseBoolLiteralSugar,
    )


def _halts_and_completions(outcome):
    from sugar_lift_py_tests.outcome import Completed, Halted

    halts = [face for face in outcome.exits if isinstance(face, Halted)]
    completions = [face for face in outcome.exits if isinstance(face, Completed)]
    return halts, completions


def _names_in(formula) -> set:
    """Every variable and atom name ``formula`` mentions, through its
    connectives' operands and its atoms' and constructors' arguments."""
    names = set()
    pending = [formula]
    while pending:
        node = pending.pop()
        name = getattr(node, "name", None)
        if isinstance(name, str):
            names.add(name)
        pending.extend(getattr(node, "operands", ()) or ())
        pending.extend(getattr(node, "args", ()) or ())
    return names


def _assert_both_arms_halt(halts) -> None:
    """Both arms' halts are kept, each under its own polarity of ``chosen``.

    The two arms' undecided memberships halt at one site with one producer,
    so they are one destination, and the one sibling join
    (``ExitSet.union`` -> ``normalize``) merges them into one exit whose
    guard is the disjunction of the two arms' guards.  Whether that is one
    exit or two, the halted face has to name each arm's comparison: a halt
    is never dropped (#7757)."""
    assert halts, halts
    assert {halt.effect.producer_node_owner for halt in halts} == {
        "UndecidedCompare:In"
    }
    mentioned = set()
    for halt in halts:
        mentioned |= _names_in(halt.guard)
    assert {"a", "b", "chosen", "python:compare.completes"} <= mentioned, halts


def test_a_guarded_container_of_two_formals_keeps_both_arms_halts() -> None:
    """``1 in (a if c else b)``: each arm is the undecided membership, kept
    under its own polarity.  Before, the rejoin demanded one value per arm
    and panicked."""
    from sugar_lift_py_tests.floor import GuardedValue, TermValue
    from sugar_lift_py_tests.ir import atomic

    guarded = GuardedValue(atomic("chosen", []), _symbolic("a"), _symbolic("b"))
    halts, completions = _halts_and_completions(guarded.contains(TermValue(1), "site"))
    _assert_both_arms_halt(halts)
    assert len(completions) == 2, completions


def test_a_guarded_needle_of_two_formals_in_a_string_keeps_both_arms_halts() -> None:
    """``(a if c else b) in "abc"``: the needle's arms rejoin by the same
    rule."""
    from sugar_lift_py_tests.floor import GuardedValue, StringValue
    from sugar_lift_py_tests.ir import atomic

    needle = GuardedValue(atomic("chosen", []), _symbolic("a"), _symbolic("b"))
    halts, completions = _halts_and_completions(
        StringValue("abc").contains(needle, "site")
    )
    _assert_both_arms_halt(halts)
    assert len(completions) == 2, completions


def test_a_guarded_container_of_decided_arms_still_rejoins_to_the_guard() -> None:
    from sugar_lift_py_tests.floor import GuardedValue, ListValue, TermValue
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue
    from sugar_lift_py_tests.ir import atomic

    guard = atomic("chosen", [])
    guarded = GuardedValue(
        guard, fresh(ListValue, (TermValue(2),)), fresh(ListValue, (TermValue(3),))
    )
    value = guarded.contains(TermValue(2), "site").completed_value()
    assert isinstance(value, PredicateValue)
    assert value.formula == guard
