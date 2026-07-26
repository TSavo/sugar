"""#6309 — spread sequencing keeps each element's ExitSet as a FACTOR.

The defect this pins: ``SpreadCollectionSugar._collect`` chained ``and_then``
once per spread element, and ``ExitSet.sequence`` appends every exit of
``step(value)`` under every completed exit of the prefix.  With ``k`` elements
of ``m`` arms each that is ``m ** k`` materialized arms — the population, not
the per-merge cost, is what timed out ``pandas/core/generic.py``.

These laws are deliberately REPRESENTATION-INDEPENDENT.  They do not pin the
arm tuple, its order, or a byte fingerprint of it, because #6309 is licensed to
change exactly that.  What may not change is the DENOTATION: which outcomes are
reachable under which truth assignment to the guard atoms, and with which
resolved value.  ``_denotation`` below is the legacy-expansion oracle: it
expands both the old materialized arms and the new factored arms down to
concrete per-assignment outcomes and compares those.
"""

from __future__ import annotations

import itertools

import pytest

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.ir import (
    _Atomic,
    _Connective,
    _ConstStr,
    _Ctor,
    _Var,
    and_,
    atomic,
    ctor,
    make_var,
    not_,
)
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.outcome.exit_set import (
    Completed,
    ExitSet,
    Halted,
    outcome_to_exitset,
    true_guard,
)
from sugar_lift_py_tests.sugar.spread_sugar import (
    SpreadCallSugar,
    SpreadCollectionSugar,
    SpreadDictSugar,
)

# --- the corpus shape: k elements, each with its own completed partition -----


def _atom(name: str):
    return atomic(name, [make_var("state")])


class _TwoFacedElement:
    """One spread element whose value depends on a guard, and which can halt.

    Three arms, pairwise contradictory: halted under ``h``, and two completed
    faces under ``not h and g`` / ``not h and not g``.  This is the shape a
    branch join or a guarded binding hands to a spread operand, and it is the
    shape whose Cartesian product exploded.
    """

    def __init__(self, index: int) -> None:
        self.index = index
        self.guard = _atom(f"g{index}")
        self.halt_guard = _atom(f"h{index}")
        self.effect = RaiseEffect(exception_name=f"E{index}")

    def desugar(self, ctx=None):
        del ctx
        live = not_(self.halt_guard)
        return ExitSet(
            (
                Halted(self.halt_guard, self.effect, None),
                Completed(
                    and_([live, self.guard]),
                    SymbolicValue(ctor(f"true{self.index}", [])),
                ),
                Completed(
                    and_([live, not_(self.guard)]),
                    SymbolicValue(ctor(f"false{self.index}", [])),
                ),
            )
        )


class _SingleFacedElement:
    """One spread element with exactly one completed arm and no halt."""

    def __init__(self, index: int) -> None:
        self.index = index

    def desugar(self, ctx=None):
        del ctx
        return Complete(SymbolicValue(ctor(f"only{self.index}", [])))


def _collection_sugar(elements):
    """``[*a, *b, ...]``."""
    return SpreadCollectionSugar(
        kind="list",
        elements=tuple((None, element) for element in elements),
        site="spread-site",
    )


def _dict_sugar(elements):
    """``{**a, **b, ...}`` — every entry is a None-key spread of one operand."""
    return SpreadDictSugar(
        entries=tuple((None, element) for element in elements),
        site="spread-site",
    )


def _call_sugar(elements):
    """``f(*a, *b, ...)`` — every argument is a starred operand."""
    return SpreadCallSugar(
        callee_name="f",
        callee=None,
        arguments=tuple(("star", None, element) for element in elements),
        site="spread-site",
    )


# All three spread sugars route through the SAME ``_collect``, so all three
# carried the same m ** k defect and all three are pinned here. Naming them
# individually is the point: ``spread_sugar.py`` had NO tests at all — no file
# under tests/ mentioned spread — which is how a Cartesian expansion lived in it
# unnoticed until a 1,421-file corpus walked into it.
_SUGARS = {
    "collection": _collection_sugar,
    "dict": _dict_sugar,
    "call": _call_sugar,
}
_KINDS = tuple(_SUGARS)

# The term each ``finish`` builds, and how many leading term arguments are NOT
# operand positions, so the occurrence law can say "one position per operand"
# without restating the production spelling.
_TERM_SHAPE = {
    "collection": ("python:list", 0),
    "dict": ("python:dict", 0),
    "call": ("python:call", 1),  # callee coordinate first, then one per operand
}


def _spread(elements, kind: str = "collection") -> ExitSet:
    return outcome_to_exitset(_SUGARS[kind](elements).desugar())


# --- the legacy-expansion oracle: denotation, not representation ------------


def _atoms(formula, seen: set) -> set:
    if isinstance(formula, _Atomic):
        seen.add(formula)
    elif isinstance(formula, _Connective):
        for operand in formula.operands:
            _atoms(operand, seen)
    return seen


def _guard_atoms(exit_set: ExitSet) -> tuple:
    seen: set = set()
    for exit_ in exit_set.exits:
        _atoms(exit_.guard, seen)
    return tuple(sorted(seen, key=lambda a: a.name))


def _holds(formula, assignment: dict) -> bool:
    if isinstance(formula, _Atomic):
        return assignment[formula]
    if isinstance(formula, _Connective):
        operands = formula.operands
        if formula.kind == "and":
            return all(_holds(operand, assignment) for operand in operands)
        if formula.kind == "or":
            return any(_holds(operand, assignment) for operand in operands)
        if formula.kind == "not":
            return not _holds(operands[0], assignment)
        if formula.kind == "implies":
            return (not _holds(operands[0], assignment)) or _holds(
                operands[1], assignment
            )
    raise AssertionError(f"oracle cannot evaluate {formula!r}")


def _formula_from_term(term):
    """Read back a ``formula_term``-reified guard so a value can be resolved."""
    assert isinstance(term, _Ctor) and term.name.startswith("formula:"), term
    tag = term.name[len("formula:") :]
    if tag in ("and", "or", "not", "implies"):
        return _Connective(tag, tuple(_formula_from_term(a) for a in term.args))
    return _Atomic(tag, tuple(term.args))


def _resolve_term(term, assignment: dict):
    """Drive every ``py.conditional`` in a term down to the selected face."""
    if isinstance(term, _Ctor):
        if term.name == "py.conditional" and len(term.args) == 3:
            guard, when_true, when_false = term.args
            chosen = (
                when_true
                if _holds(_formula_from_term(guard), assignment)
                else when_false
            )
            return _resolve_term(chosen, assignment)
        return ("ctor", term.name, tuple(_resolve_term(a, assignment) for a in term.args))
    if isinstance(term, _Var):
        return ("var", term.name)
    if isinstance(term, _ConstStr):
        return ("str", term.value)
    return ("leaf", repr(term))


def _denotation(exit_set: ExitSet, atoms: tuple) -> dict:
    """Map every truth assignment to the SET of outcomes reachable under it.

    Representation-independent by construction: guards are evaluated, values are
    resolved through their conditionals, and the result is a frozenset of
    ``("completed", resolved-term)`` / ``("halted", effect, state)`` pairs.  Two
    ExitSets with the same denotation mean the same thing however they are
    stored.
    """
    table = {}
    for bits in itertools.product((False, True), repeat=len(atoms)):
        assignment = dict(zip(atoms, bits))
        reachable = set()
        for exit_ in exit_set.exits:
            if not _holds(exit_.guard, assignment):
                continue
            if isinstance(exit_, Completed):
                term = exit_.value.to_term(owner="oracle")
                reachable.add(("completed", _resolve_term(term, assignment)))
            else:
                reachable.add(("halted", exit_.effect, exit_.state))
        table[bits] = frozenset(reachable)
    return table


def _legacy_collect(sugars, ctx, done, finish):
    """The materialized Cartesian ``_collect`` this PR replaces, kept as oracle.

    This is the pre-#6309 body verbatim.  It is the reference denotation, and it
    is the thing that grows as ``m ** k``; it is retained ONLY so the laws below
    can prove the factored representation denotes the same outcomes on bounded
    examples.  It is never on the production path.
    """
    if not sugars:
        return finish(done)
    head, *tail = sugars
    return head.desugar(ctx).and_then(
        lambda value: _legacy_collect(tuple(tail), ctx, (*done, value), finish)
    )


def _legacy_spread(elements, kind: str = "collection") -> ExitSet:
    # Re-use each sugar's production ``finish`` by driving the real desugar body
    # with the legacy collector substituted in. That keeps the oracle honest
    # about the ONE thing under test — how operands are sequenced — rather than
    # re-spelling three ``finish`` bodies in the test.
    import sugar_lift_py_tests.sugar.spread_sugar as spread_module

    sugar = _SUGARS[kind](elements)
    production = spread_module._collect
    spread_module._collect = _legacy_collect
    try:
        return outcome_to_exitset(sugar.desugar())
    finally:
        spread_module._collect = production


# --- laws -------------------------------------------------------------------

# Arities are capped so the PRE-fix state REPORTS RED instead of hanging: the
# materialized product is 3 ** arity, and at arity 8 that is 6561 arms — slow
# but finite, so the growth curve is readable in both states. Raising this cap
# does not make the law stronger; it only converts a red into a wall clock.
_ARITIES = (1, 2, 4, 6, 8)
_GROWTH_ARITIES = (2, 4, 8)


def _assert_at_most_linear(curve: dict, what: str) -> None:
    """The growth law: multiplying arity by n may not multiply cost by more.

    Stated as a bound, not an equality, because sub-linear is a better answer
    than linear and must not read as a failure — the fix makes ``normalize``
    calls flat, for instance. ``1.5`` is slack for constant terms at small
    arity, and the pre-fix curve exceeds it by orders of magnitude (m ** k
    against k), so the tolerance is not what decides the verdict.
    """
    arities = sorted(curve)
    low, high = arities[0], arities[-1]
    arity_ratio = high / low
    cost_ratio = curve[high] / curve[low]
    assert cost_ratio <= 1.5 * arity_ratio, (
        f"{what} grew {cost_ratio:.1f}x while spread arity grew "
        f"{arity_ratio:.1f}x — the factors are being distributed into their "
        f"product, not composed. curve={curve}"
    )


def _arm_population(exit_set: ExitSet) -> int:
    return len(exit_set.exits)


def _stored_nodes(exit_set: ExitSet) -> int:
    """Distinct retained nodes across every arm's guard and value.

    Counted as a DAG, by object identity, because that is what is actually
    stored: formulas and terms are interned, so element i's prefix guard is
    ``and_([prefix_{i-1}, g_i])`` — two pointers, with the prefix SHARED, not
    copied. Expanding those shared nodes into a tree would report O(k**2) for a
    representation that retains O(k) objects, which would be measuring the
    traversal rather than the storage.
    """
    seen: set[int] = set()

    def visit(node) -> None:
        if id(node) in seen:
            return
        seen.add(id(node))
        if isinstance(node, _Connective):
            for operand in node.operands:
                visit(operand)
        elif isinstance(node, _Ctor):
            for arg in node.args:
                visit(arg)

    for exit_ in exit_set.exits:
        visit(exit_.guard)
        if isinstance(exit_, Completed):
            visit(exit_.value.to_term(owner="size"))
    return len(seen)


@pytest.mark.parametrize("kind", _KINDS)
def test_arm_population_grows_linearly_with_spread_arity(kind: str) -> None:
    """The population law: k factors of 3 arms may not cost 3**k arms."""
    populations = {}
    for arity in _ARITIES:
        elements = [_TwoFacedElement(i) for i in range(arity)]
        populations[arity] = _arm_population(_spread(elements, kind))

    # One completed face plus one halted arm per element: strictly linear.
    assert populations == {arity: arity + 1 for arity in _ARITIES}, populations


@pytest.mark.parametrize("kind", _KINDS)
def test_stored_representation_grows_linearly_with_spread_arity(kind: str) -> None:
    """The storage law: the factored value may not hide an exponential either."""
    sizes = {
        arity: _stored_nodes(
            _spread([_TwoFacedElement(i) for i in range(arity)], kind)
        )
        for arity in _GROWTH_ARITIES
    }
    _assert_at_most_linear(sizes, f"{kind}: retained DAG nodes")


@pytest.mark.parametrize("kind", _KINDS)
def test_work_grows_linearly_with_spread_arity(kind: str) -> None:
    """The work law: normalize calls, not just retained arms, stay linear."""
    import sugar_lift_py_tests.outcome.exit_set as exit_set_module

    counts = {}
    original = exit_set_module.ExitSet.normalize
    for arity in _GROWTH_ARITIES:
        calls = [0]

        def counting(self, _calls=calls):
            _calls[0] += 1
            return original(self)

        exit_set_module.ExitSet.normalize = counting
        try:
            _spread([_TwoFacedElement(i) for i in range(arity)], kind)
        finally:
            exit_set_module.ExitSet.normalize = original
        counts[arity] = calls[0]

    _assert_at_most_linear(counts, f"{kind}: ExitSet.normalize calls")


@pytest.mark.parametrize("kind", _KINDS)
def test_factored_spread_denotes_the_same_outcomes_as_legacy_expansion(
    kind: str,
) -> None:
    """Bounded extensional equivalence against the legacy-expansion oracle."""
    for arity in (1, 2, 3):
        elements = [_TwoFacedElement(i) for i in range(arity)]
        factored = _spread(elements, kind)
        legacy = _legacy_spread(elements, kind)
        atoms = tuple(
            sorted(
                set(_guard_atoms(factored)) | set(_guard_atoms(legacy)),
                key=lambda a: a.name,
            )
        )
        assert _denotation(factored, atoms) == _denotation(legacy, atoms), (kind, arity)


@pytest.mark.parametrize("kind", _KINDS)
def test_neither_outcome_face_disappears(kind: str) -> None:
    """Completed AND halted both survive factoring, for every element."""
    elements = [_TwoFacedElement(i) for i in range(4)]
    exits = _spread(elements, kind)
    assert any(isinstance(e, Completed) for e in exits.exits)
    halted_effects = {e.effect for e in exits.exits if isinstance(e, Halted)}
    assert halted_effects == {element.effect for element in elements}


@pytest.mark.parametrize("kind", _KINDS)
def test_single_arm_elements_keep_the_unfactored_shape(kind: str) -> None:
    """No conditional is invented where the element had one completed face."""
    exits = _spread([_SingleFacedElement(i) for i in range(3)], kind)
    assert len(exits.exits) == 1
    exit_ = exits.exits[0]
    assert isinstance(exit_, Completed)
    assert exit_.guard == true_guard()
    term = exit_.value.to_term(owner="single")
    assert "py.conditional" not in repr(term)


@pytest.mark.parametrize("kind", _KINDS)
def test_distinct_occurrences_stay_distinct_when_content_matches(kind: str) -> None:
    """Two elements with identical content are two positions, not one."""
    twin = _TwoFacedElement(0)
    exits = _spread([twin, twin], kind)
    completed = [e for e in exits.exits if isinstance(e, Completed)]
    assert completed
    name, leading = _TERM_SHAPE[kind]
    # Representation-independent: however many arms carry the completed face,
    # every one of them must show TWO operand positions. Content equality is not
    # occurrence identity — merging the twins would silently drop an element.
    for arm in completed:
        term = arm.value.to_term(owner="occurrence")
        assert isinstance(term, _Ctor) and term.name == name, term
        assert len(term.args) - leading == 2, term
