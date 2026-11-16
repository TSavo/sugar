"""Twins: every value type answers an undecided ``==`` / ``!=`` / ordering
itself, and the compare post-passes that patched a halt onto a bare
``py.eq`` / ordering predicate are gone (#7757).

Before, ``FloorValue.equals`` (and ``OpaqueOpCallsite.equals``) answered a
bare ``py.eq`` and ``comparison_op_sugar``'s equality post-pass decided
afterwards, from the outer operands, whether to patch the undecided
dispatch's halt onto it -- a second way.  It looked only at whether each
operand's *type* was decided, so a comprehension compared to a list, a list
holding a formal compared to a list, or a guarded value (which testifies to
no value) kept the bare predicate with no halt: Python runs a member's (or
the selected arm's) ``__eq__``, which may raise, and the claim that it
raised was refuted.  The ordering post-pass panicked on any completed
predicate, including a guarded value's honest rejoin.

Now the floor answers once (``equality_atom.answered_equality``): the
stated equality, completed, only where neither operand's ``==`` runs code
the lift did not read (``equality_runs_no_source``); else the one keyed
two-faced ``python:compare_result``.  A guarded operand distributes the
comparison over its arms and keeps an arm's two faces under its polarity.
``!=`` is that answer, its completed truth negated.

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

# A value whose ``__eq__`` raises.
_BOOM = (
    "class Boom:\n"
    "    def __eq__(self, other):\n"
    '        raise ValueError("no eq")\n'
    "\n"
    "\n"
)


def _raises(call: str, exception: str) -> str:
    """A test that records whether ``call`` raised ``exception``."""
    return (
        "def test_f():\n"
        "    try:\n"
        f"        {call}\n"
        "        ok = True\n"
        f"    except {exception}:\n"
        "        ok = False\n"
        "    assert {claim}\n"
    )


_VALUE_TEST = "def test_f():\n    assert {claim}\n"

# ``name: (source, truthful claim, lying claim)``.  Braces are doubled: the
# source is a ``str.format`` template.
_SHAPES = {
    # A formal compared to a guarded value: the arm's ``==`` runs.
    "formal-equals-a-guarded-value-keeps-its-halt": (
        _BOOM + "def f(x, a, c):\n"
        "    return x == (a if c else 1)\n"
        "\n"
        "\n" + _raises("f(Boom(), 2, True)", "ValueError"),
        "not ok",
        "ok",
    ),
    "formal-equals-a-guarded-value-value": (
        "def f(x, c):\n"
        "    return x == (1 if c else 2)\n"
        "\n"
        "\n" + _VALUE_TEST,
        "f(1, True) == True",
        "f(1, False) == True",
    ),
    # A guarded value compared to a formal: each arm's own ``==``.
    "guarded-value-equals-a-formal-keeps-its-halt": (
        _BOOM + "def f(k, a, c):\n"
        "    return (a if c else 2) == k\n"
        "\n"
        "\n" + _raises("f(1, Boom(), True)", "ValueError"),
        "not ok",
        "ok",
    ),
    # A comprehension compared to a list: the members' ``__eq__`` runs.
    "comprehension-equals-a-list-keeps-its-halt": (
        _BOOM + "def f(xs):\n"
        "    return [y for y in xs] == [1]\n"
        "\n"
        "\n" + _raises("f([Boom()])", "ValueError"),
        "not ok",
        "ok",
    ),
    "comprehension-equals-a-list-value": (
        "def f(xs):\n"
        "    return [y for y in xs] == [1]\n"
        "\n"
        "\n" + _VALUE_TEST,
        "f([1]) == True",
        "f([2]) == True",
    ),
    # A list holding a formal compared to a list.
    "list-holding-a-formal-equals-a-list-keeps-its-halt": (
        _BOOM + "def f(a):\n"
        "    return [a] == [1]\n"
        "\n"
        "\n" + _raises("f(Boom())", "ValueError"),
        "not ok",
        "ok",
    ),
    # ``!=`` stands on the equals floor: ``__ne__`` defaults to ``__eq__``.
    "formal-not-equal-keeps-its-halt": (
        _BOOM + "def f(x):\n"
        "    return x != 1\n"
        "\n"
        "\n" + _raises("f(Boom())", "ValueError"),
        "not ok",
        "ok",
    ),
    "formal-not-equal-value": (
        "def f(x):\n"
        "    return x != 1\n"
        "\n"
        "\n" + _VALUE_TEST,
        "f(2) == True",
        "f(1) == True",
    ),
    # A string ordered against a formal: ``str.__lt__`` refuses a non-str.
    "string-orders-a-formal-keeps-its-type-error": (
        "def f(x):\n"
        '    return "a" < x\n'
        "\n"
        "\n" + _raises("f(1)", "TypeError"),
        "not ok",
        "ok",
    ),
    "string-orders-a-formal-value": (
        "def f(x):\n"
        '    return "a" < x\n'
        "\n"
        "\n" + _VALUE_TEST,
        'f("b") == True',
        'f("0") == True',
    ),
    # A guarded value ordered: an arm over a formal keeps its two faces.
    "guarded-value-orders-keeps-its-halt": (
        "def f(a, c):\n"
        "    return (a if c else 1) < 2\n"
        "\n"
        "\n" + _raises('f("s", True)', "TypeError"),
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
def test_comparison_never_admits_a_lie_nor_refutes_a_truth(
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
# Floor units: each value type's own answer
# ---------------------------------------------------------------------------


def _symbolic(name="a"):
    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.ir import make_var

    return SymbolicValue(make_var(name))


def _assert_undecided(outcome, kind: str) -> None:
    """The one undecided comparison: the keyed truth of
    ``python:compare_result("<kind>", ...)`` completes only under
    ``python:compare.completes``; an undetermined halt (owner
    ``UndecidedCompare:<kind>``) stands under the complement, owed either
    way.  Never a bare predicate."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted

    assert isinstance(outcome, ExitSet)
    assert outcome.completed_value() is None
    (completed,) = [face for face in outcome.exits if isinstance(face, Completed)]
    (halted,) = [face for face in outcome.exits if isinstance(face, Halted)]
    assert completed.guard.name == "python:compare.completes"
    assert completed.value.formula.name == "python:truth_result"
    assert completed.value.formula.args[0].name == "python:compare_result"
    assert completed.value.formula.args[0].args[0].value == kind
    assert isinstance(halted.effect, UndeterminedRaiseEffect)
    assert halted.effect.exception_name is None
    assert halted.effect.producer_node_owner == f"UndecidedCompare:{kind}"
    for arm in outcome.exits:
        assert arm.owed, arm


def _halts_and_completions(outcome):
    from sugar_lift_py_tests.outcome import Completed, Halted

    halts = [face for face in outcome.exits if isinstance(face, Halted)]
    completions = [face for face in outcome.exits if isinstance(face, Completed)]
    return halts, completions


def test_a_formal_equals_a_literal_is_the_undecided_equality() -> None:
    from sugar_lift_py_tests.floor import TermValue

    _assert_undecided(_symbolic().equals(TermValue(1), "site", None), "Eq")
    _assert_undecided(TermValue(1).equals(_symbolic(), "site", None), "Eq")


def test_a_comprehension_equals_a_list_is_the_undecided_equality() -> None:
    """Both types are decided, but the members' ``__eq__`` runs: before,
    the post-pass kept the bare ``py.eq`` because both types were decided."""
    from sugar_lift_py_tests.floor import ListValue, TermValue
    from sugar_lift_py_tests.floor.comprehension_value import ComprehensionValue
    from sugar_lift_py_tests.ir import ctor, make_var

    comprehension = ComprehensionValue(ctor("py.listcomp", [make_var("xs")]))
    listed = fresh(ListValue, (TermValue(1),))
    _assert_undecided(comprehension.equals(listed, "site", None), "Eq")


def test_a_list_holding_a_formal_equals_a_list_is_the_undecided_equality() -> None:
    from sugar_lift_py_tests.floor import ListValue, TermValue

    held = fresh(ListValue, (_symbolic(),))
    listed = fresh(ListValue, (TermValue(1),))
    _assert_undecided(held.equals(listed, "site", None), "Eq")


def test_two_decided_scalars_complete_with_their_stated_equality() -> None:
    """``1 == "a"`` and ``"a" == "b"`` run only builtin ``__eq__``: the
    stated equality is the whole answer, with no halt."""
    from sugar_lift_py_tests.floor import StringValue, TermValue
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue

    for left, right in (
        (TermValue(1), StringValue("a")),
        (StringValue("a"), StringValue("b")),
    ):
        outcome = left.equals(right, "site", None)
        assert isinstance(outcome.completed_value(), PredicateValue), outcome
        assert not outcome.halts(), outcome


def test_two_lists_of_decided_scalars_complete_with_their_stated_equality() -> None:
    from sugar_lift_py_tests.floor import ListValue, StringValue
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue

    left = fresh(ListValue, (StringValue("a"),))
    right = fresh(ListValue, (StringValue("b"),))
    outcome = left.equals(right, "site", None)
    assert isinstance(outcome.completed_value(), PredicateValue), outcome
    assert not outcome.halts(), outcome


def test_a_guarded_value_of_a_formal_keeps_its_arm_halt() -> None:
    """``(a if c else 2) == 1``: the formal arm is the undecided equality,
    kept under its polarity beside the decided arm.  Before, the guarded
    value testified to no value, so the post-pass kept the rejoin bare."""
    from sugar_lift_py_tests.floor import GuardedValue, TermValue
    from sugar_lift_py_tests.ir import atomic

    guarded = GuardedValue(atomic("chosen", []), _symbolic(), TermValue(2))
    halts, completions = _halts_and_completions(
        guarded.equals(TermValue(1), "site", None)
    )
    assert [halt.effect.producer_node_owner for halt in halts] == [
        "UndecidedCompare:Eq"
    ]
    assert len(completions) == 2, completions


def test_a_literal_equals_a_guarded_value_distributes_over_its_arms() -> None:
    from sugar_lift_py_tests.floor import GuardedValue, TermValue
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue
    from sugar_lift_py_tests.ir import atomic

    guard = atomic("chosen", [])
    decided = TermValue(1).equals(
        GuardedValue(guard, TermValue(1), TermValue(2)), "site", None
    )
    value = decided.completed_value()
    assert isinstance(value, PredicateValue), decided
    assert value.formula == guard
    undecided = GuardedValue(guard, _symbolic(), TermValue(1))
    halts, completions = _halts_and_completions(
        TermValue(1).equals(undecided, "site", None)
    )
    assert [halt.effect.producer_node_owner for halt in halts] == [
        "UndecidedCompare:Eq"
    ]
    assert len(completions) == 2, completions


def test_a_guarded_value_ordered_keeps_its_arm_halt() -> None:
    """``(a if c else 1) < 2``: before, the formal arm's two faces reached the
    single-value rejoin and panicked."""
    from sugar_lift_py_tests.floor import GuardedValue, TermValue
    from sugar_lift_py_tests.ir import atomic

    guarded = GuardedValue(atomic("chosen", []), _symbolic(), TermValue(1))
    halts, completions = _halts_and_completions(
        guarded.less_than(TermValue(2), "site", None)
    )
    assert [halt.effect.producer_node_owner for halt in halts] == [
        "UndecidedCompare:Lt"
    ]
    assert len(completions) == 2, completions


def test_a_guarded_value_of_decided_arms_orders_by_its_guard() -> None:
    """``(1 if c else 3) < 2`` is ``c``: the honest rejoin the deleted
    ordering post-pass refused."""
    from sugar_lift_py_tests.floor import GuardedValue, TermValue
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue
    from sugar_lift_py_tests.ir import atomic

    guard = atomic("chosen", [])
    outcome = GuardedValue(guard, TermValue(1), TermValue(3)).less_than(
        TermValue(2), "site", None
    )
    value = outcome.completed_value()
    assert isinstance(value, PredicateValue), outcome
    assert value.formula == guard


def test_a_string_ordered_against_a_formal_is_the_undecided_ordering() -> None:
    from sugar_lift_py_tests.floor import StringValue

    _assert_undecided(StringValue("a").less_than(_symbolic(), "site", None), "Lt")


def test_no_compare_post_pass_remains() -> None:
    """The equality, ordering and membership post-passes, and what only they
    used, are deleted: the floor's answer is the whole meaning."""
    from sugar_lift_py_tests.sugar import comparison_op_sugar, equality_op_sugar

    for name in (
        "publish_undecided_membership_edges",
        "publish_undecided_equality_edges",
        "publish_undecided_ordering_edges",
        "_publish_undecided_dispatch_edges",
        "_bare_equality",
        "_class_object",
        "CompareLaw",
    ):
        assert not hasattr(comparison_op_sugar, name), name
    assert not hasattr(equality_op_sugar, "_equals_with_undecided_edges")
