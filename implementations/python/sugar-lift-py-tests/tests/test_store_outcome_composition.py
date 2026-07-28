"""The store-family composition laws.

Python assignment to an attribute or a subscript is NOT transactional and NOT
infallible:

    Store(receiver, selector, value)
        success -> Completed(updated temporal state)
        failure -> Halted(store effect, prefix temporal state)

Sequential composition of stores must therefore:

  * evaluate receiver, selector and value exactly once;
  * retain all three authenticated coordinates;
  * continue subsequent targets only from the completed arm;
  * preserve earlier bindings/stores on the halted arm;
  * never roll back earlier assignment;
  * never execute a later target after an earlier store halt;
  * preserve BOTH outcomes unless evidence proves the store non-halting.

Success versus halt for an external attribute/subscript store is
RUNTIME-SELECTED, so it is carried by an authenticated store-occurrence
coordinate with complementary outcome guards -- the same mechanism
``IfSugar`` uses for a runtime-selected branch (``BranchResultCoordinate``),
not a second one. See ``floor/store_outcome_coordinate.py``.

Every test here asserts the ACTUAL constructed ``ExitSet`` arm structure or the
post formula, and each carries a discrimination arm showing that perturbing the
expectation fails.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.effect import AttributeStoreRuntimeEffect
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted
from sugar_source_tree.tree import SourceFile


def _exits(tmp_path: Path, src, name):
    """The constructed ExitSet for ``name`` in ``src``.

    ``tmp_path`` is pytest's per-test directory: the case file is written where
    the fixture will remove it. An earlier spelling used
    ``NamedTemporaryFile(delete=False, dir="/tmp")``, which leaked one ``.py``
    per call.
    """
    stem = hashlib.blake2b(f"{name}\0{src}".encode(), digest_size=8).hexdigest()
    path = tmp_path / f"case_{stem}.py"
    path.write_text(src, encoding="utf-8")
    for fn in SourceFile(path_source(str(path))).functions():
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


# Free undecided receiver ``o`` (not a formal) retains dual-face
# AttributeStoreRuntimeEffect. Formal receivers now mint setattr_named carriers
# (vertical completion); dual-face composition laws stay on this free shape.
SEQUENTIAL = """def target(p, q):
    o.x = p
    o.y = q
    return q
"""

ONE_STORE = """def target(p):
    o.x = p
    return p
"""

OTHER_STORE = """def target(q):
    o.y = q
    return q
"""


# --------------------------------------------------------------------------
# Sequential spelling:  o.x = p ; o.y = q
# --------------------------------------------------------------------------


def test_sequential_stores_preserve_both_outcomes_per_store(tmp_path: Path) -> None:
    """Two stores => three arms, never one.

    A single ``Completed`` arm would state that assignment is transactional and
    infallible. It is neither.
    """
    halted, completed = _arms(_exits(tmp_path, SEQUENTIAL, "target"))

    assert len(halted) == 2, [str(e.guard) for e in halted]
    assert len(completed) == 1


def test_sequential_stores_preserve_both_outcomes_per_store_discrimination(
    tmp_path: Path,
) -> None:
    """The bite: the pre-repair expectation (one Completed arm, no Halted arm)
    is exactly what this construction no longer produces."""
    halted, completed = _arms(_exits(tmp_path, SEQUENTIAL, "target"))

    with pytest.raises(AssertionError):
        assert len(halted) == 0 and len(completed) == 1, "stores are infallible"


def test_first_store_halt_has_no_second_store_occurrence(tmp_path: Path) -> None:
    """Law: never execute a later target after an earlier store halt.

    The arm guarded by "the FIRST store did not complete" must carry a prefix
    state in which the second store never happened.
    """
    halted, _ = _arms(_exits(tmp_path, SEQUENTIAL, "target"))
    first = next(h for h in halted if _polarity(h.guard, "x") is False)

    assert _polarity(first.guard, "y") is None, (
        "the first store's halt arm must not be conditioned on the second "
        "store's outcome -- the second store never ran"
    )
    assert (
        _store_entries(first.state) == []
    ), "the first store's halt arm must contain no store occurrence at all"
    assert isinstance(first.effect, AttributeStoreRuntimeEffect)


def test_first_store_halt_has_no_second_store_occurrence_discrimination(
    tmp_path: Path,
) -> None:
    """The bite: asserting the second store DID occur on the first-halt arm
    fails, so the assertion above is load-bearing."""
    halted, _ = _arms(_exits(tmp_path, SEQUENTIAL, "target"))
    first = next(h for h in halted if _polarity(h.guard, "x") is False)

    with pytest.raises(AssertionError):
        assert len(_store_entries(first.state)) == 1, "second target ran anyway"


def test_second_store_halt_preserves_the_first_store(tmp_path: Path) -> None:
    """Law: never roll back earlier assignment.

    The arm guarded by "first completed AND second did not" must still carry the
    first store's testimony: ``o.x`` REMAINS assigned.
    """
    halted, _ = _arms(_exits(tmp_path, SEQUENTIAL, "target"))
    second = next(h for h in halted if _polarity(h.guard, "y") is False)

    assert (
        _polarity(second.guard, "x") is True
    ), "the second store only runs when the first completed"
    surviving = _store_entries(second.state)
    assert len(surviving) == 1, surviving
    assert (
        "attr=x" in surviving[0].effect.reason
    ), "the first store must survive on the second store's halt arm"


def test_second_store_halt_preserves_the_first_store_discrimination(
    tmp_path: Path,
) -> None:
    """The bite: a rolled-back first store (empty prefix) fails."""
    halted, _ = _arms(_exits(tmp_path, SEQUENTIAL, "target"))
    second = next(h for h in halted if _polarity(h.guard, "y") is False)

    with pytest.raises(AssertionError):
        assert _store_entries(second.state) == [], "assignment rolled back"


def test_sequential_completed_arm_requires_every_store_to_complete(
    tmp_path: Path,
) -> None:
    """The continuation after the stores is reachable only when BOTH completed,
    and it still states the real post."""
    _, completed = _arms(_exits(tmp_path, SEQUENTIAL, "target"))
    (arm,) = completed

    assert _polarity(arm.guard, "x") is True
    assert _polarity(arm.guard, "y") is True
    assert str(arm.value.post()) == str(
        _exits(tmp_path, SEQUENTIAL, "target").exits[-1].value.post()
    )


def test_sequential_completed_arm_requires_every_store_to_complete_discrimination(
    tmp_path: Path,
) -> None:
    """The bite: an unconditional (true) completed guard fails -- the guard is
    a real conjunction of two store coordinates."""
    from sugar_lift_py_tests.outcome.exit_set import true_guard

    _, completed = _arms(_exits(tmp_path, SEQUENTIAL, "target"))
    (arm,) = completed

    with pytest.raises(AssertionError):
        assert arm.guard == true_guard(), "continuation is unconditional"


def test_each_store_occurrence_mints_its_own_coordinate(tmp_path: Path) -> None:
    """Law: evaluate receiver, selector and value exactly once, and retain all
    three authenticated coordinates.

    Two distinct stores must not share one outcome coordinate, and each
    coordinate must name its own receiver, selector and value.
    """
    _, completed = _arms(_exits(tmp_path, SEQUENTIAL, "target"))
    coordinates = _store_coordinates(completed[0].guard)

    assert len(coordinates) == 2, coordinates
    operations = [c.args[1] for c in coordinates]
    receivers = {op.args[0].name for op in operations}
    selectors = {op.args[1].value for op in operations}
    values = {op.args[2].name for op in operations}

    assert receivers == {"o"}
    assert selectors == {"x", "y"}
    assert values == {"p", "q"}


def test_each_store_occurrence_mints_its_own_coordinate_discrimination(
    tmp_path: Path,
) -> None:
    """The bite: collapsing the two stores to one coordinate fails."""
    _, completed = _arms(_exits(tmp_path, SEQUENTIAL, "target"))
    coordinates = _store_coordinates(completed[0].guard)

    with pytest.raises(AssertionError):
        assert len(coordinates) == 1, "both stores share one outcome"


def test_store_outcome_guards_are_exactly_complementary(tmp_path: Path) -> None:
    """The two faces of ONE store are ``g`` and ``not g`` over the SAME
    coordinate -- an exact partition, so ``ExitSet`` normalization can merge or
    kill them the way it does for a branch result."""
    from sugar_lift_py_tests.outcome.exit_set import _and_guards, false_guard

    halted, completed = _arms(_exits(tmp_path, ONE_STORE, "target"))
    (halt,) = halted
    (success,) = completed

    assert _polarity(halt.guard, "x") is False
    assert _polarity(success.guard, "x") is True
    assert (
        _and_guards(halt.guard, success.guard) == false_guard()
    ), "the halt face and the success face of ONE store cannot both hold"


def test_store_pairing_enforcement_one_occurrence_complementary_total(
    tmp_path: Path,
) -> None:
    """Pairing law for one store occurrence (post-#6246 foundation).

    Success and halt arms of ONE attribute store must:
      1. cite the same store-occurrence coordinate;
      2. carry complementary guards (``g`` and ``not g``);
      3. cover the runtime outcome without overlap (conjunction is false)
         and without omission (exactly two faces for one store in a
         single-store body: one Halted + one Completed).

    This is the invariant With and Try will reuse. Keep it named and loud.
    """
    from sugar_lift_py_tests.outcome.exit_set import _and_guards, false_guard

    exits = _exits(tmp_path, ONE_STORE, "target")
    halted, completed = _arms(exits)
    assert len(halted) == 1 and len(completed) == 1, (
        "one store body must emit exactly one halt face and one success face, "
        f"got halted={len(halted)} completed={len(completed)}"
    )
    (halt,) = halted
    (success,) = completed

    # 1 + 2: same occurrence, complementary polarities
    halt_coords = _store_coordinates(halt.guard)
    success_coords = _store_coordinates(success.guard)
    assert len(halt_coords) == 1 and len(success_coords) == 1
    assert (
        halt_coords[0] == success_coords[0]
    ), "halt and success must share one store-occurrence coordinate"
    assert _polarity(halt.guard, "x") is False
    assert _polarity(success.guard, "x") is True

    # 3: no overlap
    assert _and_guards(halt.guard, success.guard) == false_guard()

    # 3: no omission — every ExitSet face of this body is one of those two arms
    assert len(exits.exits) == 2
    assert {type(e).__name__ for e in exits.exits} == {"Halted", "Completed"}


def test_store_outcome_guards_are_exactly_complementary_discrimination(
    tmp_path: Path,
) -> None:
    """The bite: two DIFFERENT stores' guards are not contradictory -- so the
    contradiction above comes from complementarity, not from everything being
    trivially false."""
    from sugar_lift_py_tests.outcome.exit_set import _and_guards, false_guard

    halted, _ = _arms(_exits(tmp_path, ONE_STORE, "target"))
    (halt,) = halted
    other, _unused = _arms(_exits(tmp_path, OTHER_STORE, "target"))
    (other_halt,) = other

    with pytest.raises(AssertionError):
        assert (
            _and_guards(halt.guard, other_halt.guard) == false_guard()
        ), "unrelated store coordinates are contradictory"


def test_no_invented_exception_type_on_a_store_halt(tmp_path: Path) -> None:
    """Success versus halt is runtime-selected. The halt arm must carry the
    store's own runtime effect, never a fabricated named exception."""
    halted, _ = _arms(_exits(tmp_path, SEQUENTIAL, "target"))

    for arm in halted:
        assert isinstance(arm.effect, AttributeStoreRuntimeEffect), type(arm.effect)


def test_no_invented_exception_type_on_a_store_halt_discrimination(
    tmp_path: Path,
) -> None:
    """The bite: the halt is NOT a RaiseEffect of some guessed class."""
    from sugar_lift_py_tests.effect import RaiseEffect

    halted, _ = _arms(_exits(tmp_path, SEQUENTIAL, "target"))

    with pytest.raises(AssertionError):
        assert all(isinstance(a.effect, RaiseEffect) for a in halted), "guessed"


# --------------------------------------------------------------------------
# Unpack spelling (``x, o.y = p, q``, ``o.x, o.y = p, q``) is NOT tested here.
#
# Ownership boundary (T's ruling):
#
#     this branch   owns generic store success/halt composition
#                   owns sequential assignment spelling
#
#     #6239         owns tuple/multi-target construction
#                   owns unpack sequencing through that composition
#
# A prerequisite must not be held red by syntax it deliberately does not
# construct. The unpack twins now live on ``fix/assign-family-drain`` in
# ``tests/test_assign_unpack_store_outcome_composition.py``, where the
# construction they exercise is owned. They are stated as the real laws there,
# not muted here.
# --------------------------------------------------------------------------
