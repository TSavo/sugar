"""Twins: an ``is`` nothing decides owes; it is never a free equality the
solver picks (#7757, step 6).

The prover asks whether a claim CAN be true: a raw ``sat`` is
``discharged`` (``consistency_verdict``).  So an ``identity`` atom over two
terms the prover does not interpret is a choice the solver makes, and a lie
reads ``sat`` by choosing them equal.  #8983 closed it for effect slots
(``effect_coordinate.slot_identity``).  The same free choice stood wherever
else ``is`` was stated over terms nothing relates:

- ``FloorValue.is_identical``'s plain emit over two other terms (``a is b``
  over two formals, two calls' results): now ``object_identity.term_identity``;
- ``object_identity``'s undecided branch (``python:object_at(<key>,
  left/right)``: one display evaluated twice, an arrived value, equal ground
  values);
- ``==`` over a slot, which testifies to no value, so the dispatch test
  handed back the bare ``py.eq``.

Each owes the undecided member at its site by the one rule
(``object_identity.undecided_identity`` -> ``owing_undecided_slot``; ``==``
by the undecided dispatch, ``ExitSet.two_faced``).  Decided identities stay
decided: one term compared with itself (``a is a``), a language singleton
(``z is None``), two class coordinates, two constructions (``[] is []``).

A lying claim is never ``sat``; a truthful one is never ``unsat``.  Each half
goes through ``run_source_through_real_solver``: real ``sugar mint`` then
real ``sugar prove``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    prove_verdict,
    run_source_through_real_solver,
)

# ``name: (source, line of the test function's def, truthful, lying)``.
_SHAPES = {
    # Two fresh lists: Python says ``a is b`` is False.  The callee's
    # identity of two formals is two terms nothing relates.
    "formals-distinct-objects": (
        "def same(a, b):\n"
        "    return a is b\n"
        "\n"
        "\n"
        "def test_identity():\n"
        "    x = []\n"
        "    y = []\n"
        "    assert {claim}\n",
        5,
        "not same(x, y)",
        "same(x, y)",
    ),
    # One display evaluated by two iterations: two lists, so ``prev is cur``
    # is False (``object_identity``'s undecided branch).
    "one-display-twice": (
        "def test_identity():\n"
        "    prev = None\n"
        "    for i in (1, 2):\n"
        "        cur = []\n"
        "        if i == 2:\n"
        "            assert {claim}\n"
        "        prev = cur\n",
        1,
        "prev is not cur",
        "prev is cur",
    ),
    # Two items' ``e``: two ``ValueError`` objects, which compare by
    # identity, so ``errs[0] == errs[1]`` is False.
    "two-items-except-as-equality": (
        "def test_identity():\n"
        "    errs = []\n"
        "    for i in [1, 2]:\n"
        "        e = None\n"
        "        try:\n"
        "            raise ValueError(i)\n"
        "        except ValueError as e:\n"
        "            errs.append(e)\n"
        "    assert {claim}\n",
        1,
        "errs[0] != errs[1]",
        "errs[0] == errs[1]",
    ),
}


@pytest.mark.parametrize("half", ["truthful", "lying"])
@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_an_undecided_identity_never_reads_a_lie_sat(
    tmp_path: Path, shape: str, half: str
) -> None:
    source, test_line, truthful, lying = _SHAPES[shape]
    claim = truthful if half == "truthful" else lying
    result = run_source_through_real_solver(
        tmp_path / shape / half, source.format(claim=claim)
    )
    verdict = claim_verdict(result.prove_doc, claims_from_line=test_line)
    whole = prove_verdict(result.prove_doc)
    if half == "lying":
        assert verdict != "sat", result.prove_doc
        assert whole != "sat", result.prove_doc
    else:
        assert verdict != "unsat", result.prove_doc
        assert whole != "unsat", result.prove_doc


_ITSELF = (
    "def itself(a):\n"
    "    if a is a:\n"
    "        return 1\n"
    "    return 2\n"
    "\n"
    "\n"
    "def test_identity():\n"
    "    x = []\n"
    "    assert {claim}\n"
)


@pytest.mark.parametrize("half", ["truthful", "lying"])
def test_a_formal_is_itself(tmp_path: Path, half: str) -> None:
    """``a is a`` is one term compared with itself: decided, owing nothing,
    so the truthful claim reads ``sat`` and the lie never does.

    The identity selects the int ``itself`` returns, read by ``==`` as the
    early-return twins read ``x is None`` (``test_early_return_guard_is_the_
    test``).  Were ``a is a`` owed, ``itself``'s own proof would owe it inside
    its definition and the truthful claim would read ``open`` (#8985).  The
    bare ``assert itself(x)`` this twin first stated took ``bool()`` of the
    call's result, a second question: prove settles that truth only where a
    joined post states the result's builtin type, and ``return a is a``
    states ``out = identity(a, a)``, a predicate no builtin type is stated
    for, so it read ``open`` whatever ``is`` decided."""
    claim = "itself(x) == 1" if half == "truthful" else "itself(x) == 2"
    result = run_source_through_real_solver(
        tmp_path / "itself" / half, _ITSELF.format(claim=claim)
    )
    verdict = claim_verdict(result.prove_doc, claims_from_line=7)
    if half == "truthful":
        assert verdict == "sat", result.prove_doc
    else:
        assert verdict != "sat", result.prove_doc


# -- what each identity owes ---------------------------------------------------

_SITE = "blake3-512:test-identity-site"


def _owes(outcome) -> bool:
    from sugar_lift_py_tests.unanswered_calls import UnansweredCallV1

    return any(isinstance(item, UnansweredCallV1) for item in outcome.owed_items())


def _formal(name: str):
    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.ir import make_var

    return SymbolicValue(make_var(name))


def _class_read(name: str):
    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.ir import ctor, str_const

    return SymbolicValue(ctor("python:type", [str_const(name)]))


def test_two_formals_identity_owes_never_a_free_choice() -> None:
    outcome = _formal("a").is_identical(_formal("b"), _SITE)
    assert _owes(outcome)
    assert outcome.completed_value().formula.name == "identity"
    negated = _formal("a").is_identical(_formal("b"), _SITE)
    assert _owes(negated.and_then(lambda predicate: predicate.negate()))


def test_a_formal_compared_with_itself_owes_nothing() -> None:
    outcome = _formal("a").is_identical(_formal("a"), _SITE)
    assert not _owes(outcome)
    left, right = outcome.completed_value().formula.args
    assert left == right


def test_a_formal_against_a_singleton_owes_nothing() -> None:
    from sugar_lift_py_tests.floor.none_value import NoneValue
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
        TrueBoolLiteralSugar,
    )

    assert not _owes(_formal("a").is_identical(NoneValue(), _SITE))
    assert not _owes(NoneValue().is_identical(_formal("a"), _SITE))
    assert not _owes(_formal("a").is_identical(TrueBoolLiteralSugar(site=_SITE), _SITE))


def test_two_class_coordinates_are_decided() -> None:
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
        TrueBoolLiteralSugar,
    )

    same = _class_read("int").is_identical(_class_read("int"), _SITE)
    other = _class_read("int").is_identical(_class_read("str"), _SITE)
    assert type(same.completed_value()) is TrueBoolLiteralSugar
    assert type(other.completed_value()) is FalseBoolLiteralSugar
    assert not _owes(same) and not _owes(other)


def test_a_class_read_and_a_formal_owe() -> None:
    assert _owes(_formal("t").is_identical(_class_read("int"), _SITE))


def test_equal_ground_values_identity_owes() -> None:
    # ``1000 is 1000``: interning is the implementation's choice, so the
    # comparison's own atom stands, and it owes.
    from sugar_lift_py_tests.floor import TermValue

    outcome = TermValue(1000).is_identical(TermValue(1000), _SITE)
    assert _owes(outcome)
    left, right = outcome.completed_value().formula.args
    assert left.name == right.name == "python:object_at"


def test_two_ground_values_are_two_objects_and_owe_nothing() -> None:
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )

    outcome = TermValue(1).is_identical(TermValue(2), _SITE)
    assert type(outcome.completed_value()) is FalseBoolLiteralSugar
    assert not _owes(outcome)
