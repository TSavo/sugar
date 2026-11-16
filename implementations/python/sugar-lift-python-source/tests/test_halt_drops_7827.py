"""#7827: suspected dropped faces from the halt-spellings map, each with a twin.

Tests only; no lifter change. Each suspected site from #7827 is either
confirmed by a smallest program and pinned ``xfail(strict=True)``, with the
reason naming the site and the face lost, or struck with evidence that the
source cannot reach it.

The truthful half of each twin is the same program without the operation the
site mishandles, and it keeps every face. The lying half exercises the site.
Where the solver cannot tell the halves apart, because a claim over an
unbound formal stays ``open`` (#7766), the twin is also pinned at the
reduction level, where the lost face is visible.

Confirmed, and no longer pinned expected-red once the linear result form was
deleted (#7825):

1. ``floor/guarded_value.py`` ``GuardedValue._map``: a linear halt on the
   true arm returned at once, and the false arm was never evaluated. ``x = []
   if c else [2]; return x[0]`` must keep a completed face under ``not c``
   that holds a ``ReturnValue``; Python returns ``2`` there.

Confirmed and fixed by H2 of #7825 (the store family answers its two faces
at the producer, ``store_faces``):

4. ``generator_construction.py`` attribute-store step: a generator manager
   whose body stores ``o.x = 1`` before ``yield`` reaches its yield on the
   store's completed face.
6. ``o.x += 1`` (through ``ExitSet.and_then`` in ``AugAssignSugar``) keeps
   the face where getattr, add and setattr all complete.

Struck (each test below records why): ``sugar/for_universal_sugar.py``
(since deleted),
``sugar/exit_set_routing.py`` ``exitset_to_outcome`` (since deleted, #7826),
``sugar/match_sugar.py``'s linear-halt converters (since deleted, #7825),
and of item 6: the with-manager bridge and the linear halt's ``and_then``
(both since deleted, #7825) and ``caller_parameter_contract.py``'s
``undischarged`` arm.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    WitnessPipelineError,
    run_source_through_real_solver,
)


def _tree(source: str):
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_source_tree.tree import SourceFile

    return SourceFile(
        (source, "test_witness.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )


def _function(source: str, name: str = "test_f"):
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome
    from sugar_source_tree import nodes

    (function,) = tuple(
        node
        for node in _tree(source).nodes()
        if isinstance(node, nodes.FunctionDef) and node.name == name
    )
    return function_universe_outcome(function)


def _faces(outcome) -> tuple[int, tuple[str, ...]]:
    """(completed faces, the effect type of each halted face)."""
    from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted

    assert isinstance(outcome, ExitSet), outcome
    value = outcome.completed_value()
    if value is not None:
        assert value.follow_rest().continues, outcome
        return 1, ()
    return (
        sum(isinstance(face, Completed) for face in outcome.exits),
        tuple(
            type(face.effect).__name__
            for face in outcome.exits
            if isinstance(face, Halted)
        ),
    )


def _verdict(tmp_path: Path, source: str) -> str:
    try:
        return run_source_through_real_solver(tmp_path, source).verdict
    except WitnessPipelineError as exc:
        if "no assertion rows" in str(exc):
            return "no assertion rows"
        raise


# ---------------------------------------------------------------------------
# 1. floor/guarded_value.py GuardedValue._map: confirmed.
# ---------------------------------------------------------------------------

_GUARDED = (
    "def test_f(xs):\n    c = xs is None\n    x = {arm} if c else [2]\n    {tail}"
)
_GUARDED_ASSERT = "y = x[0]\n    assert c or y == 2\n"
_GUARDED_RETURN = "return x[0]\n"


@pytest.mark.parametrize("arm", ["[1]", "[]"], ids=["truthful", "lying"])
def test_guarded_value_twin_through_the_solver_is_open_on_both_halves(
    arm: str, tmp_path: Path
) -> None:
    """The solver cannot tell the halves apart: the claim is over an unbound
    formal and stays open (#7766). The drop is pinned at the reduction level."""
    source = _GUARDED.format(arm=arm, tail=_GUARDED_ASSERT)

    assert _verdict(tmp_path, source) == "open"


def _completed_returns(outcome) -> list:
    from sugar_lift_py_tests.floor.return_value import ReturnValue
    from sugar_lift_py_tests.outcome import Completed, ExitSet

    assert isinstance(outcome, ExitSet), outcome
    records = [face.value for face in outcome.exits if isinstance(face, Completed)]
    return [
        statement
        for record in records
        for statement in getattr(getattr(record, "record", record), "statements", ())
        if isinstance(statement, ReturnValue)
    ]


def test_guarded_value_truthful_half_returns_on_its_completed_face() -> None:
    outcome = _function(_GUARDED.format(arm="[1]", tail=_GUARDED_RETURN))

    assert len(_completed_returns(outcome)) == 1


def test_guarded_value_lying_half_returns_the_false_arm_on_its_completed_face() -> None:
    outcome = _function(_GUARDED.format(arm="[]", tail=_GUARDED_RETURN))

    assert len(_completed_returns(outcome)) == 1


# ---------------------------------------------------------------------------
# 2. sugar/for_universal_sugar.py: struck, then deleted (inventory item 38).
#    No source node constructed ForUniversalSugar. A source `for` goes through
#    the loop recurrence, which keeps the body's halt beside the completion.
#    The recurrence follows the completed face of the iterable's `iter`: over
#    a formal that is an undecided operation, two-faced and owed.
# ---------------------------------------------------------------------------

_FOR = "def test_f(xs):\n    for x in xs:\n        {body}\n    assert 1 == 1\n"


def test_for_universal_sugar_is_never_reached_from_source() -> None:
    """The second reducer of a ``for`` loop is gone; a source loop still
    reduces, through the one loop recurrence."""
    import importlib.util

    assert (
        importlib.util.find_spec("sugar_lift_py_tests.sugar.for_universal_sugar")
        is None
    )

    _function(_FOR.format(body="raise ValueError"))
    _function(_FOR.format(body="y = 1"))


@pytest.mark.parametrize(
    ("body", "faces"),
    [
        ("y = 1", (1, ("UndeterminedRaiseEffect", "UndeterminedRaiseEffect"))),
        (
            "raise ValueError",
            (1, ("RaiseEffect", "UndeterminedRaiseEffect", "UndeterminedRaiseEffect")),
        ),
    ],
    ids=["truthful", "lying"],
)
def test_a_source_loop_keeps_its_body_halt_beside_the_completion(
    body: str, faces, tmp_path: Path
) -> None:
    """``xs`` is a formal: nothing here decides its ``iter``, so iterating it
    is an undecided operation like every other, and so is each ``next`` of
    the iterator ``iter`` completed with (#8844: an iterator whose
    ``__next__`` is not decided here may raise on any step). Each completes
    on one face and raises something undetermined on the other, and each
    owes its operation as an ``undecided`` member at the loop. So neither
    half is ``sat``: a source that owes a member never is. The halves differ
    at the reduction: the lying body's ``raise`` is a halted face of its own
    beside the completion and beside the undetermined halts of ``iter`` and
    ``next``."""
    source = _FOR.format(body=body)

    outcome = _function(source)
    completed, halts = _faces(outcome)
    assert (completed, tuple(sorted(halts))) == faces
    # ``iter`` and ``next`` over the formal are owed at the loop (line 2),
    # and nothing else is (an item is one per symbol and site, so the two
    # undecided reads at one site may be one item).
    assert {item.site.start_line for item in outcome.owed_items()} == {2}
    assert _verdict(tmp_path, source) == "open"


@pytest.mark.parametrize("iterable", ["(1, 2)", "[1, 2]"], ids=["tuple", "list"])
def test_a_loop_over_a_decided_iterable_owes_no_iter(iterable: str) -> None:
    """A literal tuple or list made in the frame is decided: its ``iter``
    completes, on one face, owing nothing. Only an iterable the reduction
    has not decided is two-faced."""
    outcome = _function(
        f"def test_f():\n    for x in {iterable}:\n        y = 1\n    assert 1 == 1\n"
    )

    assert not outcome.halts()
    assert not outcome.owed_items()


# ---------------------------------------------------------------------------
# 3. sugar/exit_set_routing.py exitset_to_outcome: deleted (#7826). The try
#    family hands back its own faces; no converter projects them onto a
#    linear record, so none can drop an untyped completed arm.
# ---------------------------------------------------------------------------


def test_the_linear_projection_of_a_boundary_is_gone() -> None:
    import sugar_lift_py_tests.sugar.exit_set_routing as routing

    assert not hasattr(routing, "exitset_to_outcome")
    assert not hasattr(routing, "promote_raise_halts")


# ---------------------------------------------------------------------------
# 4. generator_construction.py attribute-store step: confirmed. Reachable
#    only through an installed generator manager, so this twin is at the
#    reduction level; the one-file solver harness cannot install a package.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 5. sugar/match_sugar.py linear-halt converters: struck, then deleted
#    (#7825). A guarded case is built now; a guard whose truth is not one
#    decided value where the match is reduced (a formal's, a call result's)
#    takes its truth through the one truth rule: each completed truth face
#    selects the case under its own guard and the truth's halt is kept
#    (#7757 NEW-5; before, it was refused by name, ``MatchSugar.guard``). A
#    halting subject is handed back as its own arms.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "guard", ["c", "c.ready()"], ids=["formal", "call-result"]
)
def test_a_case_guard_whose_truth_is_undecided_keeps_its_halt(guard: str) -> None:
    """``case 5 if c`` (a formal) or ``case 5 if c.ready()`` (a call result): the
    guard's ``bool`` may run ``__bool__`` / ``__len__``, so its truth is the
    one truth rule's two faces.  The case is selected on the completed face
    and the truth's undetermined halt (``MatchSugar.truth``) is kept, owed;
    never a halt-less completion (a direct ``.truth`` used to drop it for a
    call result) and no longer a refusal."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome import Completed, Halted

    outcome = _function(
        f"def test_f(c):\n    match 5:\n        case 5 if {guard}:\n"
        "            a = 1\n    return 3\n"
    )
    truth_halts = [
        face
        for face in outcome.exits
        if isinstance(face, Halted)
        and isinstance(face.effect, UndeterminedRaiseEffect)
        and face.effect.producer_node_owner == "MatchSugar.truth"
    ]
    assert truth_halts, outcome
    assert all(face.owed for face in truth_halts)
    assert any(isinstance(face, Completed) for face in outcome.exits), outcome


# ``x`` holds a call result (not a parameter) whose ``__bool__`` raises.  The
# call completes (``make``'s contract, joined at prove, states it), so the
# only raise left in ``choose`` is the guard's ``bool(x)``.  A direct
# ``.truth`` used to complete it with a halt-less ``py.truthy``: ``choose``
# then stated "returns 1 or 2" with no panic locus, and the lie
# ``choose() != 3`` could read ``sat``.  Python raises ``ValueError`` there.
_GUARD_OVER_A_RAISING_TRUTH = (
    "import pytest\n"
    "\n"
    "\n"
    "class Boom:\n"
    "    def __bool__(self):\n"
    "        raise ValueError('boom')\n"
    "\n"
    "\n"
    "def make():\n"
    "    return Boom()\n"
    "\n"
    "\n"
    "def choose():\n"
    "    x = make()\n"
    "    match 1:\n"
    "        case 1 if x:\n"
    "            return 1\n"
    "        case _:\n"
    "            return 2\n"
    "\n"
    "\n"
    "def test_choose():\n"
    "{claim}"
)


@pytest.mark.parametrize(
    ("claim", "half"),
    [
        (
            "    with pytest.raises(ValueError):\n        choose()\n",
            "truthful",
        ),
        ("    assert choose() != 3\n", "lying"),
    ],
    ids=["truthful", "lying"],
)
def test_a_match_guards_truth_halt_twin(claim: str, half: str, tmp_path: Path) -> None:
    """#7757 NEW-5 twin: the lie reads ``sat`` only if the guard's truth
    halt were dropped; the truth never reads ``unsat``."""
    verdict = _verdict(tmp_path, _GUARD_OVER_A_RAISING_TRUTH.format(claim=claim))
    if half == "lying":
        assert verdict != "sat"
    else:
        assert verdict != "unsat"


@pytest.mark.parametrize(
    ("arm", "faces"),
    [("[1]", (2, ())), ("[]", (1, ("RaiseEffect",)))],
    ids=["truthful", "lying"],
)
def test_a_guarded_halting_subject_keeps_both_faces_without_the_converters(
    arm: str, faces
) -> None:
    """The subject ``x[0]`` is read on each arm of ``x``, one under ``c`` and
    one under ``not c``, and each arm selects its own case.

    Truthful (``[1] if c else [2]``): both arms complete, and they are two
    completions, not one. Under ``c`` the subject is 1 and no case runs; under
    ``not c`` it is 2 and ``case 2`` binds ``a``. The two leave different
    records, so they are two completed faces and no halt, as Python has two
    paths that both return 3. Lying (``[] if c else [2]``): the arm under
    ``c`` halts at ``x[0]`` with ``IndexError`` and the arm under ``not c``
    completes: one completion beside the halt, neither dropped."""
    outcome = _function(
        f"def test_f(xs):\n    c = xs is None\n    x = {arm} if c else [2]\n"
        "    match x[0]:\n        case 2:\n            a = 1\n    return 3\n"
    )

    assert _faces(outcome) == faces


# ---------------------------------------------------------------------------
# 6. The store family read as a plain halt.
#    Confirmed at outcome/exit_set.py's linear-to-arms bridge (since deleted,
#    #7825), reached by `o.x += 1` (ExitSet.and_then in AugAssignSugar).
#    Struck: the with-manager bridge (since deleted; its ten callers passed a
#    with-manager, __enter__ or __exit__ expression outcome, never a store);
#    the linear halt's and_then (since deleted; no expression step runs after
#    a store: a chained target store is sequenced by the block reducer,
#    pinned below);
#    caller_parameter_contract.py's undischarged arm (the native projector is
#    not called from source reduction; a formal store's call reduces the
#    callee with its actuals bound).
# ---------------------------------------------------------------------------

_STORE = "import mod\n\n\ndef test_f():\n    o = mod.make()\n    {line}\n    {tail}"


def test_augassign_truthful_half_keeps_a_completed_face(tmp_path: Path) -> None:
    source = _STORE.format(line="y = o.x + 1", tail="assert 1 == 1\n")

    assert _faces(_function(source))[0] == 1
    assert _verdict(tmp_path, source) == "open"


def test_augassign_lying_half_keeps_a_completed_face(tmp_path: Path) -> None:
    source = _STORE.format(line="o.x += 1", tail="assert 1 == 1\n")

    assert _faces(_function(source))[0] == 1
    assert _verdict(tmp_path, source) == "open"


def test_a_chained_target_store_keeps_its_completed_face() -> None:
    """Struck for the linear halt's and_then: the store before the next target is
    sequenced by the block reducer, which keeps both of its faces."""
    outcome = _function(_STORE.format(line="o.x = a = 1", tail="return a\n"))
    completed, halts = _faces(outcome)

    assert completed == 1
    # The store's halted face is the one undetermined raise its producer
    # names (the one undecided attribute mutation, #7757 NEW-4).
    assert "UndeterminedRaiseEffect" in halts
    assert any(
        getattr(face.effect, "producer_node_owner", None) == "UndecidedSetattr"
        for face in outcome.halts()
    )
