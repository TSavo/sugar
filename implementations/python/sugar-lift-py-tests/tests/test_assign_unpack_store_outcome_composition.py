"""Unpack store-outcome composition laws -- owned by the Assign-family branch.

Ownership boundary (T's ruling):

    store ExitSet branch   owns generic store success/halt composition
                           owns sequential assignment spelling

    this branch (#6239)    owns tuple/multi-target construction
                           owns unpack sequencing through that composition

The generic algebra -- ``python:store_completed(occurrence, operation)``,
``FollowStep.halt_guard``, ``Halted(g, effect, prefix_state)`` paired with
``Completed(not g, state_with_testimony)`` -- is the store branch's work and is
proven there by the SEQUENTIAL twins. What is proven HERE is that the
tuple/multi-target ``Assign`` construction this branch owns actually flows
through that composition: a store leaf inside an unpack is not a different kind
of store, so ``x, o.y = p, q`` and ``o.x, o.y = p, q`` must produce exactly the
same arm structure as the sequential spelling.

These are RED until BOTH halves land: this branch constructs the unpack, the
store branch supplies the exit algebra. Red here is the law failing, not a
missing construction -- the unpack currently reduces to ONE unconditional
``Complete``, i.e. it states that an attribute/subscript store is infallible.

GATE CONDITIONS FOR WHOEVER TURNS THESE GREEN -- all four are red at the SAME
line today (``_exits`` raises before any body runs), so none of the per-twin
structure below has ever executed. Green is not enough; check each:

  1. Both ``_discrimination`` twins currently die inside ``_exits`` and never
     reach their ``pytest.raises`` block, so right now they are duplicates of
     the two law twins, not independent evidence. When ``_exits`` returns an
     ``ExitSet``, confirm each one actually ENTERS its ``pytest.raises`` body
     and that the body's assertion genuinely fails. A
     ``pytest.raises(AssertionError)`` wrapper is the classic shape that goes
     green while asking nothing.

  2. ``test_unpack_two_stores_..._discrimination`` only requires
     ``_store_entries(first.state) != 1``, which 0 AND 2 both satisfy. The law
     twin's ``== []`` carries the real claim. Do not count that discrimination
     as independent evidence for the empty-prefix law.

  3. The law twins have never run past their first assertion either. Re-measure
     every line, do not assume the arm counts and polarities are right merely
     because the file stops failing.

# TODO(post-store-merge): the helper block below (``_exits``, ``_walk``,
# ``_terms``, ``_subterms``, ``_store_coordinates``, ``_selectors``,
# ``_polarity``, ``_arms``, ``_store_entries``) is copied verbatim from
# ``tests/test_store_outcome_composition.py``. It could not be imported when
# this file was written because ``feat/store-exitset-composition`` was not yet
# on main. Once the store foundation merges, DELETE this block and import the
# helpers from ``test_store_outcome_composition`` instead -- one definition,
# one owner. While doing that, switch ``_exits`` off
# ``NamedTemporaryFile(delete=False, dir="/tmp")``: it leaks a .py per call and
# bypasses pytest's ``tmp_path``, which every other twin in this package uses.
"""

from __future__ import annotations

import tempfile

import pytest

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.effect import AttributeStoreRuntimeEffect
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted
from sugar_source_tree.tree import SourceFile

# --------------------------------------------------------------------------
# TODO(post-store-merge): dedupe -- import from test_store_outcome_composition.
# --------------------------------------------------------------------------


def _exits(src, name):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    for fn in SourceFile(path_source(path)).functions():
        if fn.name != name:
            continue
        outcome = fn.sugar().desugar(None)
        assert isinstance(outcome, ExitSet), (
            "a body containing a store must reduce to guarded exits, not one "
            f"unconditional outcome; got {type(outcome).__name__}"
        )
        return outcome
    raise AssertionError(f"no function {name}")


def _walk(formula):
    yield formula
    for operand in getattr(formula, "operands", ()) or ():
        yield from _walk(operand)


def _terms(formula):
    for node in _walk(formula):
        for arg in getattr(node, "args", ()) or ():
            yield from _subterms(arg)


def _subterms(term):
    yield term
    for arg in getattr(term, "args", ()) or ():
        yield from _subterms(arg)


def _store_coordinates(formula):
    """Every distinct store-occurrence coordinate cited by a guard."""
    found = []
    for term in _terms(formula):
        if getattr(term, "name", None) == "python:store_completed":
            if term not in found:
                found.append(term)
    return tuple(found)


def _selectors(formula):
    """The selector (attr name) of each store coordinate cited by a guard."""
    out = []
    for coordinate in _store_coordinates(formula):
        operation = coordinate.args[1]
        out.append(operation.args[1].value)
    return tuple(out)


def _polarity(formula, selector):
    """True when the guard asserts the named store COMPLETED, False when it
    asserts the complement, None when the guard does not mention it."""
    for node in _walk(formula):
        if getattr(node, "kind", None) != "not":
            continue
        (inner,) = node.operands
        if selector in _selectors(inner):
            return False
    if selector in _selectors(formula):
        return True
    return None


def _arms(exits):
    halted = [e for e in exits.exits if isinstance(e, Halted)]
    completed = [e for e in exits.exits if isinstance(e, Completed)]
    return halted, completed


def _store_entries(state):
    return [
        entry
        for entry in getattr(state, "entries", ())
        if isinstance(entry, Incomplete)
        and isinstance(entry.effect, AttributeStoreRuntimeEffect)
    ]


UNPACK_MIXED = """def target(o, p, q):
    x, o.y = p, q
    return x
"""

UNPACK_BOTH = """def target(o, p, q):
    o.x, o.y = p, q
    return p
"""


# --------------------------------------------------------------------------
# Unpack spelling:  x, o.y = p, q   and   o.x, o.y = p, q
#
# THE SAME LAWS as the sequential spelling. These are the same store family; a
# store target inside a tuple-unpack assignment is not a different kind of
# store.
#
# They are stated as the real laws rather than pinned to the current behaviour
# on purpose: a test that must be DELETED when the bug is fixed is a test of the
# bug.
# --------------------------------------------------------------------------


def test_unpack_mixed_name_and_store_preserves_both_outcomes():
    """``x, o.y = p, q``

    success arm: ``x == p``, the store on ``o.y`` completed, continuation runs.
    halt arm:    ``x == p`` STILL -- the name target was already bound -- the
                 store halted, and there is NO continuation.
    """
    halted, completed = _arms(_exits(UNPACK_MIXED, "target"))

    assert len(completed) == 1
    assert _polarity(completed[0].guard, "y") is True
    assert "p" in str(completed[0].value.post())

    (arm,) = halted
    assert _polarity(arm.guard, "y") is False
    assert "p" in str(arm.state.post() if hasattr(arm.state, "post") else arm.state), (
        "the name target bound before the store must survive the store's halt"
    )


def test_unpack_mixed_name_and_store_preserves_both_outcomes_discrimination():
    """The bite: a single unconditional arm would mean the store cannot fail."""
    halted, completed = _arms(_exits(UNPACK_MIXED, "target"))

    with pytest.raises(AssertionError):
        assert len(halted) == 0 and len(completed) == 1, "store is infallible"


def test_unpack_two_stores_preserve_both_outcomes_per_store():
    """``o.x, o.y = p, q`` -- the same three arms as the sequential spelling:
    first success + second success, first success + second halt, and first halt
    with NO second-store occurrence."""
    halted, completed = _arms(_exits(UNPACK_BOTH, "target"))

    assert len(completed) == 1
    assert len(halted) == 2

    first = next(h for h in halted if _polarity(h.guard, "x") is False)
    assert _polarity(first.guard, "y") is None
    assert _store_entries(first.state) == []

    second = next(h for h in halted if _polarity(h.guard, "y") is False)
    assert _polarity(second.guard, "x") is True
    assert len(_store_entries(second.state)) == 1


def test_unpack_two_stores_preserve_both_outcomes_per_store_discrimination():
    """The bite: the first-halt arm must not carry the second store."""
    halted, _ = _arms(_exits(UNPACK_BOTH, "target"))
    first = next(h for h in halted if _polarity(h.guard, "x") is False)

    with pytest.raises(AssertionError):
        assert len(_store_entries(first.state)) == 1, "second target ran anyway"
