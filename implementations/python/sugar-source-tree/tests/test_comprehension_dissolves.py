"""A comprehension runs as a ``for`` does (#7757 new 6, #8957).

No rewrite dissolves a comprehension into a display any more. The reduction
runs it by the loop's one mechanism:

- where it holds the members (``iterator_operation.in_hand_members``: a
  container in hand, or a completed ``range(...)`` over ground ints, within
  ``LOOP_UNROLL_BUDGET``), each member runs through the loop's one item
  runner (``ComprehensionSugar._run_in_hand``), and a decided list, set or
  dict states its display;
- anywhere else it runs as the loop's recurrence: ``iter`` once, ``next`` per
  item, one symbolic item (``python:loop.item``), and it completes with its
  own coordinate, ``<kind>(<occurrence>, <evaluation key>)``, whose read owes
  the undecided member. No member binder (a lambda) is ever in the term
  (``ComprehensionSugar._own_coordinate``); every halt of the item is an arm.

Each file is opened through the one construction door
(``open_source_file_for_construction``) under a workspace root, as the lift
opens it: a ground exit (the in-hand iteration's ``StopIteration``) cites a
workspace-relative locus.
"""

import json
import tempfile
from pathlib import Path

import pytest

from sugar_lift_py_tests.ir import (
    ctor,
    encode_jcs,
    make_var,
    num,
    str_const,
    term_to_value,
)
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.outcome import Completed, ExitSet
from sugar_lift_py_tests.proofir.formulas import _free_vars_in_ir_term

from native_carrier_testimony import (
    atoms_named,
    completed_function_value,
    undecided_outcome,
    undetermined_owners,
)


def _fn(src):
    root = Path(tempfile.mkdtemp(prefix="comprehension-"))
    path = root / "subject.py"
    path.write_text(src, encoding="utf-8")
    return next(open_source_file_for_construction(path, root=root).functions())


def _out(src):
    return completed_function_value(_fn(src)).post().args[1]


def _outcome(src):
    outcome = _fn(src).sugar().desugar()
    assert isinstance(outcome, ExitSet), outcome
    return outcome


def _completed_terms(outcome):
    """What each completed arm returns, in order (at least one)."""
    terms = tuple(
        exit_.value.post().args[1]
        for exit_ in outcome.normalize().exits
        if isinstance(exit_, Completed)
    )
    assert terms, outcome
    return terms


def _is_own_coordinate(term, kind):
    """``<kind>(<occurrence>, <evaluation key>)``: the comprehension's own
    coordinate, never a display and never a member binder."""
    return (
        term.name == kind
        and len(term.args) == 2
        and term.args[0].name == "python:source-occurrence"
        and term.args[1].name == "python:occurrence"
    )


def _iterated_formals(outcome):
    """The formal each stated ``iter`` runs over."""
    return {
        atom.args[0].args[0].args[0].name
        for atom in atoms_named(outcome, "python:iter_op.completes")
    }


# -- members in hand: the item runner decides the display ------------------


def test_filtered_listcomp_keeps_ground_true_elements():
    term = _out("def A():\n    return [x for x in [1, 2, 3, 4] if x > 2]\n")
    assert term.name == "array"
    assert [arg.value for arg in term.args] == [3, 4]


def test_dictcomp_over_concrete_range_dissolves():
    term = _out("def A():\n    return {x: x + 10 for x in range(2)}\n")
    assert term.name == "python:dict"
    assert [(item.args[0].value, item.args[1].value) for item in term.args] == [
        (0, 10),
        (1, 11),
    ]


def test_filtered_dictcomp_keeps_only_ground_true_entries():
    term = _out(
        "def A():\n"
        "    return {item: item + 10 for item in [0, 1, 2, 3] if item % 2 == 0}\n"
    )
    assert term.name == "python:dict"
    assert [(item.args[0].value, item.args[1].value) for item in term.args] == [
        (0, 10),
        (2, 12),
    ]


def test_setcomp_over_concrete_range_dissolves():
    term = _out("def A():\n    return {x + 1 for x in range(3)}\n")
    assert term.name == "python:set"
    assert [arg.value for arg in term.args] == [1, 2, 3]


def test_filtered_setcomp_keeps_only_ground_true_members():
    term = _out("def A():\n" "    return {item for item in [0, 1, 2, 3] if item > 1}\n")
    assert term.name == "python:set"
    assert [arg.value for arg in term.args] == [2, 3]


def test_setcomp_preserves_duplicate_elimination():
    term = _out("def A():\n    return {x % 2 for x in range(4)}\n")
    assert [arg.value for arg in term.args] == [0, 1]


def test_dictcomp_preserves_last_value_for_duplicate_key():
    term = _out("def A():\n    return {0: x for x in range(3)}\n")
    assert len(term.args) == 1
    assert (term.args[0].args[0].value, term.args[0].args[1].value) == (0, 2)


def test_existing_concrete_displays_keep_exact_terms():
    filtered = _out("def A():\n    return [x for x in [1, 2, 3] if x > 1]\n")
    destructured = _out("def A():\n    return [a + b for a, b in [(1, 2), (3, 4)]]\n")
    assert filtered == ctor("array", [num(2), num(3)])
    assert destructured == ctor("array", [num(3), num(7)])


def test_a_false_condition_stops_the_member_before_its_next_condition():
    """Python evaluates a member's conditions in order and stops at the first
    false one (``ComprehensionSugar._sifted``): ``0 > 0`` is false, so
    ``x > limit`` never runs, no undecided ordering is stated, and the list
    is decided empty."""
    term = _out("def A(limit):\n" "    return [x for x in [0] if x > 0 if x > limit]\n")
    assert term == ctor("array", [])


def test_nested_comprehension_reads_the_outer_capture():
    """The inner comprehension reads ``values`` where it runs, under each
    outer member: ``[[1]]``. Nothing inlines the capture at rewrite."""
    term = _out(
        "def A():\n"
        "    values = [1]\n"
        "    return [[y for y in values] for x in [1]]\n"
    )
    assert term == ctor("array", [ctor("array", [num(1)])])


def test_walrus_comprehension_reads_the_outer_capture():
    term = _out(
        "def A():\n" "    value = 7\n" "    return [(captured := value) for x in [1]]\n"
    )
    assert term == ctor("array", [num(7)])


def test_concrete_generator_is_not_pulled_where_it_is_made():
    """A generator expression runs when it is consumed: made and returned,
    its members' calls are not stated where it is made (``_generator``), and
    its term is its own coordinate, never a display."""
    term = _out("def A():\n    return (f(x) for x in [1, 2])\n")
    assert _is_own_coordinate(term, "py.generatorexp")


def test_shadowed_consumer_does_not_materialize_generator():
    """``list`` rebound to a formal is not the builtin: calling it never
    builds a list display."""
    outcome = _outcome(
        "def A(materialize):\n"
        "    list = materialize\n"
        "    return list(x for x in [0, 1])\n"
    )
    assert all(term.name != "array" for term in _completed_terms(outcome))


# -- members not in hand: the loop's recurrence -----------------------------


def test_undecidable_filtered_listcomp_retains_guard_without_guessing_verdict():
    """An undecided filter over a formal waits on no caller: ``x > limit`` is
    the undecided ordering's two faces, never a guessed verdict (#7757, audit
    row NEW-1). Which members it keeps is not decided, so the comprehension
    runs as its recurrence: the ordering's operand is the recurrence's one
    symbolic item (``python:loop.item``)."""
    outcome = undecided_outcome(
        _fn("def A(limit):\n    return [x for x in [1, 2] if x > limit]\n")
    )
    assert "UndecidedCompare:Gt" in undetermined_owners(outcome)
    compares = {
        (operation.args[0].value, operation.args[1].name, operation.args[2].name)
        for atom in atoms_named(outcome, "python:compare.completes")
        for operation in atom.args
    }
    assert compares == {("Gt", "python:loop.item", "limit")}


@pytest.mark.parametrize(
    ("source", "kind"),
    [
        ("{item for item in [0, 1, 2, 3] if keep(item)}", "py.setcomp"),
        ("{item: item + 10 for item in [0, 1, 2, 3] if keep(item)}", "py.dictcomp"),
    ],
)
def test_filtered_set_and_dict_do_not_fabricate_symbolic_guard_verdict(source, kind):
    """``keep(item)`` decides no member: no completed arm states a display
    built from a guessed verdict; each completes with the comprehension's own
    coordinate, and the call's halt is kept."""
    outcome = _outcome(f"def A(keep):\n    return {source}\n")
    assert all(_is_own_coordinate(term, kind) for term in _completed_terms(outcome))
    assert outcome.halts(), outcome


@pytest.mark.parametrize(
    ("source", "kind", "pulled_here"),
    [
        ("[f(x) for x in xs]", "py.listcomp", True),
        ("{f(x) for x in xs}", "py.setcomp", True),
        ("{x: f(x) for x in xs}", "py.dictcomp", True),
        ("(f(x) for x in xs)", "py.generatorexp", False),
    ],
)
def test_simple_symbolic_comprehension_builds_coordinate(source, kind, pulled_here):
    """Over a formal the comprehension is its recurrence: ``iter(xs)`` is
    stated, it completes with its own coordinate, and that read owes the
    undecided member. An eager comprehension's item halts (``f``'s call) are
    its arms; a generator returned unconsumed states none of them."""
    outcome = _outcome(f"def A(xs):\n    return {source}\n")
    assert all(_is_own_coordinate(term, kind) for term in _completed_terms(outcome))
    assert _iterated_formals(outcome) == {"xs"}
    assert outcome.owed_items(), outcome
    assert ("UnknownCallee:f" in undetermined_owners(outcome)) is pulled_here


def test_nested_symbolic_generators_state_both_iterations():
    """Each generator's ``iter`` is stated, the inner one inside the outer
    item; the comprehension completes with the outer kind's coordinate."""
    outcome = _outcome("def A(xs, ys):\n    return [x + y for x in xs for y in ys]\n")
    assert all(
        _is_own_coordinate(term, "py.listcomp") for term in _completed_terms(outcome)
    )
    assert _iterated_formals(outcome) == {"xs", "ys"}


@pytest.mark.parametrize(
    "source",
    [
        "def A(xs):\n    x = 999\n    return [f(x) for x in xs]\n",
        "def A(x):\n    return [f(x) for x in x]\n",
    ],
)
def test_bound_target_masks_outer_same_spelling(source):
    """The element reads the member the target binds, never the outer
    binding of the same spelling: every ``f`` call is over the recurrence's
    symbolic item."""
    outcome = _outcome(source)
    calls = atoms_named(outcome, "python:unknown_callee_call.completes")
    assert calls, outcome
    for atom in calls:
        call = atom.args[0].args[0]
        assert call.name == "call:f"
        assert call.args[0].name == "python:loop.item"


def test_list_and_generator_keep_distinct_eager_and_lazy_coordinates():
    eager = _completed_terms(_outcome("def A(xs):\n    return [f(x) for x in xs]\n"))
    lazy = _completed_terms(_outcome("def A(xs):\n    return (f(x) for x in xs)\n"))
    assert all(_is_own_coordinate(term, "py.listcomp") for term in eager)
    assert all(_is_own_coordinate(term, "py.generatorexp") for term in lazy)
    assert not set(eager) & set(lazy)


def test_over_budget_concrete_comprehension_runs_as_its_recurrence():
    """``range(129)`` holds more members than ``LOOP_UNROLL_BUDGET``: the
    comprehension runs as its recurrence and completes with its own
    coordinate, never a display."""
    outcome = _outcome("def A():\n    return [f(x) for x in range(129)]\n")
    assert all(
        _is_own_coordinate(term, "py.listcomp") for term in _completed_terms(outcome)
    )


def test_shadowed_range_is_not_unrolled_but_builds_symbolic_coordinate():
    """A formal named ``range`` is not the builtin: its call's result is not
    in hand, and the comprehension completes with its own coordinate."""
    outcome = _outcome("def A(range):\n    return [x for x in range(3)]\n")
    assert all(
        _is_own_coordinate(term, "py.listcomp") for term in _completed_terms(outcome)
    )


# -- construction --------------------------------------------------------------


def test_old_bound_transform_ctor_is_nonbinding_lying_twin():
    lying = ctor(
        "py.bound_transform",
        [str_const("x"), ctor("call:f", [make_var("x")])],
    )
    wire = json.loads(encode_jcs(term_to_value(lying)))

    assert wire["kind"] == "ctor"
    assert _free_vars_in_ir_term(lying) == frozenset({"x"})


@pytest.mark.parametrize(
    "source",
    [
        "[(y := x) for x in [1]]",
        "[x for x in [1] if (y := x)]",
        "((y := x) for x in [1])",
    ],
)
def test_a_walrus_comprehension_constructs(source):
    # A walrus in an element or a condition writes its key per member (a
    # generator's when it is consumed): it no longer stays loud (#7938, #7757).
    _fn(f"def A():\n    return {source}\n").sugar()
