"""The guard-stable Floor law, exercised from Python source rather than by hand.

`test_guarded_floor_value_law.py` pins the law over floor values built
directly in the test. That proves the law; it cannot prove the corpus reaches
it. The 25 `owner=guarded` rows in the pinned pandas ledger are source sites,
and every one of the six categories they name is reproducible from ordinary
Python: a bare expression statement under an `if` rides its value under the
branch guard.

Three faces.

TRUTHFUL: each category constructs. At `78714a798` every function in
`GUARDED_CATEGORIES` raised the ledger's exact panic
(`owner=guarded ... requested=ride under a guard`); each now completes.

REACHED: the value categories are actually dispatched through `guarded` (the
ledger's sixth, a `class` statement, is a binding under the one statement
rule, not a bare value; it is held to TRUTHFUL alone). Without
this face the truthful one passes vacuously — a change that stops routing these
values under the guard at all would leave every construction green while the
law it is supposed to exercise goes untested. That is the shape of a control
that asserts something weaker than it reads.

CONSERVED: the guard is not dropped. Guard-stable means *this category's
meaning* is unchanged by the guard, never that `guarded` became a no-op. An
obligation under the same source shape must still weaken to an implication.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path

import pytest

from sugar_lift_py_tests.floor.inv_value import InvValue
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction

CORPUS = """\
def bare_string(flag):
    if flag:
        "a string statement"
    return 1


def bare_true(flag):
    if flag:
        True
    return 2


def bare_false(flag):
    if flag:
        False
    return 3


def bare_comprehension(flag, xs):
    if flag:
        [x for x in xs]
    return 4


def bare_symbolic(flag, series):
    if flag:
        series
    return 5


def guarded_class_definition(flag):
    if flag:
        class Inner:
            pass
        keep = Inner
    return 6


def guarded_obligation(flag, claim):
    if flag:
        assert claim
    return 7
"""

# Each function names the Floor category its guarded entry rides as: the
# value categories the ledger records.
GUARDED_CATEGORIES = {
    "bare_string": "StringValue",
    "bare_true": "TrueBoolLiteralSugar",
    "bare_false": "FalseBoolLiteralSugar",
    "bare_comprehension": "ComprehensionValue",
    "bare_symbolic": "SymbolicValue",
}

# A ``class`` statement under the guard is no bare value: it binds its name
# under its statement's key, as every body's ``class`` statement does
# (``_body_statement_sugar``, #7757), and ``keep = Inner`` reads that key on
# the arm that ran it.  It must construct; it is not asked to ride the guard
# as a bare value's category.
GUARDED_CONSTRUCTIONS = (*GUARDED_CATEGORIES, "guarded_class_definition")


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "guarded_categories.py").write_text(CORPUS, encoding="utf-8")
    return root


def _functions(root: Path):
    source_file = open_source_file_for_construction(
        root / "guarded_categories.py", root=root
    )
    return {function.name: function for function in source_file.functions()}


def _own_proof(function):
    """The function's outcome as its own proof states it: ``if flag:`` on a
    formal is the undecided truth's two faces."""
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    return function_universe_outcome(function)


def _completed_universes(outcome) -> list:
    """The value of every completed arm of ``outcome``."""
    from sugar_lift_py_tests.outcome import Completed

    return [exit_.value for exit_ in outcome.exits if isinstance(exit_, Completed)]


@pytest.fixture
def guarded_dispatch(monkeypatch):
    """Record the concrete category riding through every `guarded` arm.

    Patches each Floor class that defines `guarded`, so the recording sees the
    concrete arm that runs rather than a base-class wrapper the subclasses
    shadow.
    """
    import sugar_lift_py_tests.floor as floor_package

    ridden: list[str] = []
    patched: set[type] = set()
    for module_info in pkgutil.iter_modules(floor_package.__path__):
        module = importlib.import_module(
            f"sugar_lift_py_tests.floor.{module_info.name}"
        )
        for value in vars(module).values():
            if not inspect.isclass(value) or value in patched:
                continue
            arm = value.__dict__.get("guarded")
            if arm is None:
                continue
            patched.add(value)

            def record(original):
                def guarded(self, formula):
                    ridden.append(type(self).__name__)
                    return original(self, formula)

                return guarded

            monkeypatch.setattr(value, "guarded", record(arm))
    assert patched, "no Floor class defines `guarded` -- nothing was instrumented"
    return ridden


@pytest.mark.parametrize("name", sorted(GUARDED_CONSTRUCTIONS))
def test_guarded_category_constructs_from_source(corpus: Path, name: str) -> None:
    """TRUTHFUL: the ledger's guarded categories complete instead of panicking.

    ``bool(flag)`` on an unanswered formal may raise, so the completion is
    an arm beside the truth's halt, never the one unconditional value."""
    outcome = _own_proof(_functions(corpus)[name])
    assert _completed_universes(outcome), f"{name} did not construct: {outcome!r}"


def test_every_category_actually_rides_under_the_guard(
    corpus: Path, guarded_dispatch: list[str]
) -> None:
    """REACHED: each construction really dispatches the category it names.

    Without this the truthful face is satisfied by source that never reaches
    `guarded` at all.
    """
    functions = _functions(corpus)
    for name, category in sorted(GUARDED_CATEGORIES.items()):
        before = len(guarded_dispatch)
        _own_proof(functions[name])
        rode = guarded_dispatch[before:]
        assert category in rode, (
            f"{name} constructed without riding a {category} under its guard; "
            f"categories seen: {rode or 'none'}"
        )


def test_the_guard_is_not_dropped_by_the_stable_category(corpus: Path) -> None:
    """CONSERVED: an obligation under the same shape still weakens.

    Guard-stable is a claim about a category's meaning, not a licence for
    `guarded` to return its input. `assert claim` under `if flag` must come
    back as an implication, never as the bare claim.
    """
    from sugar_lift_py_tests.ir import implies

    outcome = _own_proof(_functions(corpus)["guarded_obligation"])
    universes = _completed_universes(outcome)
    assert universes, outcome
    obligations = [
        statement
        for universe in universes
        for statement in universe.record.statements
        if isinstance(statement, InvValue)
    ]
    assert (
        len(obligations) == 1
    ), f"expected exactly one obligation, saw {len(obligations)}"
    formula = obligations[0].formula
    assert getattr(formula, "kind", None) == "implies", (
        f"the guarded obligation is `{formula}`, not an implication -- the "
        f"branch guard was dropped"
    )
    guard, claim = formula.operands
    # And it is the branch's own guard, reconstructed from the parts rather
    # than trusted from the shape: an implication over the wrong antecedent
    # would satisfy the kind check alone.
    assert formula == implies(guard, claim)
    assert guard != claim, "the obligation implies itself -- no guard was carried"


def test_every_halt_of_the_guarded_obligation_carries_its_record(corpus: Path) -> None:
    """RECORDED: no halt of ``if flag: assert claim``'s body leaves
    record-less.

    Neither truth waits on a caller (#9018): ``bool(flag)`` and
    ``bool(claim)`` on a parameter are the one truth rule's two faces
    (``_unanswered_truth``), each halt with no record of its own, recorded
    at the head of the statement that tests it (``halts_recorded`` for the
    ``if`` test, ``halts_at_statement_head`` for the ``assert``), so the
    ``if`` join reads a record on every suite halt.

    The assert's failure is no halt of the body's block: the assert states
    its test as a fact, and the function's own universe splits each
    completed arm on it (``halts_where_its_asserts_fail``, #8961), past the
    block, into the ``AssertionError`` its panic locus states and the arm
    that goes on.  That split leaves the function, never a statement, so no
    block reads a record off it; it is checked here by its site and guard.
    """
    from sugar_lift_py_tests.outcome import Halted
    from sugar_source_tree.nodes import Assert

    outcome = _own_proof(_functions(corpus)["guarded_obligation"])
    halts = [exit_ for exit_ in outcome.exits if isinstance(exit_, Halted)]
    assert halts, outcome

    def _raised_at_the_assert(halt) -> bool:
        raised = getattr(halt.effect, "raised_value", None)
        return halt.effect.exception_name == "AssertionError" and isinstance(
            getattr(getattr(raised, "site", None), "node", None), Assert
        )

    failures = [halt for halt in halts if _raised_at_the_assert(halt)]
    assert len(failures) == 1, halts
    (failure,) = failures
    assert failure.effect.producer_node_owner == "ground_assertion_error", failure
    assert "py.truthy" in str(failure.guard), failure
    body_halts = [halt for halt in halts if halt is not failure]
    # Both truths' halts: ``flag``'s at the ``if`` test, ``claim``'s at the
    # ``assert``.
    assert len(body_halts) >= 2, halts
    recordless = [halt for halt in body_halts if halt.state is None]
    assert not recordless, f"halts with no record: {recordless!r}"
