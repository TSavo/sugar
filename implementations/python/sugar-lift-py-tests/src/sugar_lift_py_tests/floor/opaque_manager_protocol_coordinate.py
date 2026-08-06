"""Open protocol coordinates for a manager whose body sugar cannot see.

An off-population ``with`` manager -- ``pytest.raises(...)``,
``warnings.catch_warnings()`` -- is CITED, never materialized.  Sugar
authenticates WHICH callee stands at the ``with`` head and authenticates that
it does not know what that callee's ``__enter__`` and ``__exit__`` do.  Those
are two different claims and this module carries the second one.

Python's ``with`` law is the manager's own semantics is not.  Independent
of any manager, the language guarantees:

    enter is attempted; the body runs only if enter completed; exit runs over
    every outgoing body edge.

Everything the MANAGER decides stays open:

- does ``__enter__`` complete, or halt?
- what does ``__enter__`` project?
- does ``__exit__`` suppress an exceptional body edge?
- does ``__exit__`` itself halt?

None of those has lift-time evidence, and inventing one would fabricate the
very fact the off-population refusal exists to protect.  So each is modelled
the way this tree already models every runtime-selected outcome: an
authenticated per-occurrence coordinate plus the complementary guard pair
``g`` / ``not g``.  This is deliberately the SAME mechanism as
``floor/store_outcome_coordinate.py`` and ``floor/branch_result_coordinate.py``,
not a second one.

**No biconditional is emitted, and that is the point.**  Tying a coordinate to
a lift-time formula would be exactly the invented enter/exit semantics the
ruling forbids.  The coordinates stay open; both faces survive; every claim
that depends on the manager's behaviour reaches the emitted FOL as an
undischarged obligation instead of being decided here by silence.

Absence, unknown and known do not share a spelling.  A manager with no
resolution at all is a construction panic (absence).  A manager whose contract
IS derived carries ``ContextManagerContractRefV1`` and real enter/exit
testimony (known).  A cited-opaque manager carries THESE coordinates
(unknown) -- a positive term, minted per occurrence, never a default and never
a sentinel.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.floor.floor_value import FloorValue


def opaque_manager_occurrence_address(site, *, slot: str) -> str:
    """The authenticated address of THIS manager occurrence's protocol slot.

    Two textually identical ``with pytest.raises(ValueError):`` sites mint two
    distinct coordinates, and one site evaluated once mints one.  ``slot``
    separates the enter question from the exit question at the same occurrence:
    they are independent unknowns and must never share a symbol.
    """
    return f"opaque-manager:{slot}:{site.filename}:{site.line}:{site.col}"


@dataclass(frozen=True)
class OpaqueManagerProtocolCoordinate(FloorValue):
    """An open per-occurrence coordinate over a cited, unmaterialized manager.

    ``symbol`` names WHICH question is open (enter completion, enter result,
    exit result).  ``manager`` is the manager's own authenticated term, so the
    coordinate is authenticated by the callee it actually names -- a coordinate
    over ``pytest.raises(ValueError)`` is not the same symbol as one over
    ``warnings.catch_warnings()``.
    """

    occurrence: str
    symbol: str
    manager: object
    site: object = field(default=None, compare=False)
    symbol_kind: str = field(default="coordinate", init=False)

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            self.symbol,
            [str_const(self.occurrence), self.manager],
        )

    def truth(self, site):
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import py_truthy
        from sugar_lift_py_tests.outcome import Complete

        return Complete(PredicateValue(py_truthy(self.to_term(owner=str(site))), site))


def _coordinate(manager_term, site, *, slot: str, symbol: str):
    return OpaqueManagerProtocolCoordinate(
        opaque_manager_occurrence_address(site, slot=slot),
        symbol,
        manager_term,
        site,
    )


def opaque_enter_completed_coordinate(manager_term, site):
    """``true`` exactly when this occurrence's ``__enter__`` completed."""
    return _coordinate(
        manager_term, site, slot="enter", symbol="python:cm_enter_completed"
    )


def opaque_enter_result_coordinate(manager_term, site):
    """What ``__enter__`` projected here.  An opaque function symbol, not a value.

    This is what an ``as`` target binds.  It is not a claim that the manager
    returns itself, nor that it returns anything in particular -- it is the
    same position ``SymbolicValue`` and ``py.getattr`` already occupy.
    """
    return _coordinate(
        manager_term, site, slot="enter-result", symbol="python:cm_enter_result"
    )


def opaque_exit_completed_coordinate(manager_term, site):
    """``true`` exactly when this occurrence's ``__exit__`` completed.

    Separate from suppression on purpose: an ``__exit__`` that RAISES and an
    ``__exit__`` that returns falsey are different outcomes, and collapsing
    them would claim a cited manager cannot fail while closing.
    """
    return _coordinate(
        manager_term, site, slot="exit", symbol="python:cm_exit_completed"
    )


def opaque_exit_result_coordinate(manager_term, site):
    """What ``__exit__`` returned.  Its TRUTHINESS decides suppression.

    Handed to ``ExitSet.and_exit_truthiness`` exactly as a source-derived
    exit's real return value is.  Because this coordinate is undecidable, that
    router keeps BOTH faces -- suppressed under its truth, the body's original
    effect restored under its falsity.  That is where the opacity propagates.
    """
    return _coordinate(
        manager_term, site, slot="exit-result", symbol="python:cm_exit_result"
    )


def opaque_completed_guard(coordinate):
    """``g`` -- the guard formula for an open completion coordinate."""
    from sugar_lift_py_tests.sugar.if_sugar import predicate_formula

    return predicate_formula(coordinate, coordinate.site)


def opaque_halted_guard(coordinate):
    """``not g`` -- the complementary face.

    ``ExitSet._is_negation`` recognises the pair, so the two arms partition
    exactly and normalization can merge or kill them the same way it does for a
    branch result or a store outcome.
    """
    from sugar_lift_py_tests.ir import not_

    return not_(opaque_completed_guard(coordinate))
