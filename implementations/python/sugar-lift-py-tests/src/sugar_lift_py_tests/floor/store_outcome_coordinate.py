"""The store-occurrence outcome coordinate: effect-dimension phi for a store.

Python assignment to an attribute or a subscript is NOT transactional and NOT
infallible.  ``o.x = p`` can halt at runtime (``__setattr__``/descriptor/
``__setitem__`` dispatch belongs to the runtime), and when a LATER store halts
the EARLIER targets remain assigned.  So a store has exactly two outcomes:

    Store(receiver, selector, value)
        success -> Completed(updated temporal state)
        failure -> Halted(store effect, prefix temporal state)

Which one happens is RUNTIME-SELECTED.  There is no lift-time evidence naming a
particular exception type, and inventing one would fabricate a fact.  So the
outcome is modelled the way this tree already models every runtime-selected
binary outcome: an authenticated per-occurrence coordinate plus the
complementary guard pair ``g`` / ``not g``.

This is deliberately the SAME mechanism as
``floor/branch_result_coordinate.py``'s ``BranchResultCoordinate`` (used by
``IfSugar`` for a runtime-selected branch), not a second one.  The difference is
only what authenticates the coordinate:

- a branch result is authenticated by the sealed source fragment of its TEST,
  and tied to the observed condition by a biconditional inv;
- a store outcome has no observable condition to tie to, so it is authenticated
  by the store OCCURRENCE: the witness address of the store's own runtime
  effect, together with the store's own operation term -- which retains all
  three authenticated coordinates (receiver, selector, value).  Two distinct
  stores therefore mint two distinct, independent coordinates, and the same
  store evaluated once mints one.

No biconditional is emitted, and that is the point: an authentication tying the
coordinate to a lift-time formula would be exactly the invented exception type
the ruling forbids.  The coordinate stays open; both faces survive.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.floor.floor_value import FloorValue

def store_faces(effect):
    """The two faces of one store occurrence, built where the store is.

    Every store-family producer (attribute and subscript stores, attribute
    and subscript deletes) answers exactly this: ``Halted(not g)`` with the
    store's own effect, and ``Completed(g)`` whose value is the red testimony
    that the runtime answered the store (``RuntimeEffectTestimony``).  It is
    the ONE spelling of the store law: no linear outcome carries a second
    meaning that "continues under g and halts under not g" (#7825, H2).

    The halted arm has no state of its own: nothing is reached inside an
    expression before its store halts, so the block reducer gives it the
    prefix it already established.
    """
    from sugar_lift_py_tests.floor.runtime_effect_testimony import (
        RuntimeEffectTestimony,
    )
    from sugar_lift_py_tests.outcome.exit_set import (
        Completed,
        ExitSet,
        Halted,
        complement_guard,
    )

    halted = store_halted_guard(effect)
    return ExitSet(
        (
            Halted(halted, effect, None),
            Completed(complement_guard(halted), RuntimeEffectTestimony(effect)),
        )
    ).normalize()


def store_occurrence_address(effect) -> str:
    """The authenticated address of THIS store occurrence.

    Read straight off the effect's own ``RuntimeEffectWitness`` site, which is a
    genuine fragment minted by enumeration through the one SourceOracle (see
    ``effect/runtime_effect.py``'s ``RuntimeEffectSite`` protocol).  filename /
    line / col is the contract both fragment currencies answer, so this needs no
    fallback arm and cannot be reconstructed from blame prose.
    """
    site = effect.witness.site
    return f"store-outcome:{site.filename}:{site.line}:{site.col}"


@dataclass(frozen=True)
class StoreOutcomeCoordinate(FloorValue):
    """``true`` exactly when the store at this occurrence completed."""

    occurrence: str
    operation: object
    site: object = field(default=None, compare=False)
    symbol_kind: str = field(default="coordinate", init=False)

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        # The occurrence address distinguishes two textually identical stores;
        # the operation term retains receiver, selector and value, so the
        # coordinate is authenticated by the store it actually names.
        return ctor(
            "python:store_completed",
            [str_const(self.occurrence), self.operation],
        )

    def truth(self, site):
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import py_truthy
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(
            PredicateValue(py_truthy(self.to_term(owner=str(site))), site)
        )


def store_outcome_coordinate(effect) -> StoreOutcomeCoordinate:
    return StoreOutcomeCoordinate(
        store_occurrence_address(effect),
        effect.witness.operation,
        effect.witness.site,
    )


def store_completed_guard(effect):
    """``g`` -- the store at this occurrence completed."""
    from sugar_lift_py_tests.sugar.if_sugar import predicate_formula

    coordinate = store_outcome_coordinate(effect)
    return predicate_formula(coordinate, coordinate.site)


def store_halted_guard(effect):
    """``not g`` -- the complementary face.  ``ExitSet._is_negation`` recognises
    the pair, so the two arms partition exactly and normalization can merge or
    kill them the same way it does for a branch result."""
    from sugar_lift_py_tests.ir import not_

    return not_(store_completed_guard(effect))
