"""The calls a reduction leaves unanswered: each one becomes an ``undecided`` member.

Step 8 (PR B on #7766): a Python call whose callee nothing here resolved is
recorded once, as an ``undecided`` member with ``reason: unanswered``. Its
``symbol`` is the target symbol the one import table (#7837) holds at the
callee's own coordinate when the callee is import-bound, else ``None`` (Q5: a
call with no symbol is still a member). Its ``site`` is the call's
``SourceFragmentCoordinateV1``.

A call is left unanswered where the lifter does not have its callee: the
two-faced call of ``UnknownCalleeCallV1.faces`` (#7585) and of
``OffPopulationSourceCallV1.faces`` (an authenticated callee cited off the
enrolled population). "Not bridged" is stated one way: each puts one
``UnansweredCallV1`` on the ``owed`` slot of BOTH its arms (#7825, H4), since
the call is incurred whether it then completes or raises. ``owed`` rides every
arm rebuild by union (``ExitSet.sequence`` for a composition, ``ExitSet.union``
/ ``normalize`` for a merge), so the item reaches
the reduction's final arms on every path that reached the call. The full scan
that mint packages reads it there (``owed_calls``); nothing is recorded on the
side, a seek reads nothing, and a reduction read back from a memo carries its
items in its outcome. The member records the call and nothing about what
answers it, so it is the same staged or unstaged (row 0a.4).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UnansweredCallV1:
    """One call nothing here answers, owed by the arms that passed through it.

    ``site`` is the call's ``SourceFragmentCoordinateV1``, or ``None`` when the
    call reached the lifter with no fragment. A siteless item is carried like
    any other and refused by name only where it would become a member
    (``tree_enumerate.unanswered_call_rows``): a call the proof must owe has
    to have a site.
    """

    symbol: str | None
    site: object | None


def unanswered_call(symbol: str | None, site) -> UnansweredCallV1:
    """The owed item for one unanswered call at ``site`` (a source fragment)."""
    if site is None:
        return UnansweredCallV1(symbol, None)
    from sugar_lift_py_tests.caller_parameter_contract import source_coordinate

    return UnansweredCallV1(symbol, source_coordinate(site))


def owed_calls(outcome) -> tuple[UnansweredCallV1, ...]:
    """Every unanswered call a reduction's final outcome owes, in arm order.

    Read off the arms' ``owed`` slot. A deferred native operation
    (``NativeOperationExitCarrierV1``) has no arms of its own until a caller
    discharges it, but the arms of its composed prefix and the stopping faces
    of its short circuits were reduced: their items are read there, and a
    deferred carrier beneath the prefix is read the same way. A linear
    ``Complete`` / ``Incomplete`` owes nothing (it has no owed slot, which is
    why ``ExitSet.collapse`` keeps an owing arm an arm).
    """
    from sugar_lift_py_tests.outcome.exit_set import ExitSet

    owed = ExitSet(_reduced_arms(outcome)).owed_items()
    return tuple(item for item in owed if isinstance(item, UnansweredCallV1))


def _reduced_arms(outcome) -> tuple:
    """Every reduced arm of ``outcome``, in arm order, for ``owed_calls``.

    The arms of an ``ExitSet``; for a deferred carrier, the stopping faces of
    its short circuits, then the arms of its composed prefix, each deferred
    prefix arm followed by the reduced arms of the carrier beneath it. Their
    debts are joined by the one reader, ``ExitSet.owed_items``.
    """
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.outcome.exit_set import ExitSet

    if isinstance(outcome, ExitSet):
        return outcome.exits
    if not isinstance(outcome, NativeOperationExitCarrierV1):
        return ()
    arms = [
        arm for _g, stopped, _c, _s in outcome.short_circuits for arm in stopped.exits
    ]
    if outcome.prefix_composition is not None:
        resolved, deferred = outcome.prefix_composition[:2]
        arms.extend(resolved)
        for prefix_exit, carrier in deferred:
            arms.append(prefix_exit)
            if carrier is not outcome:
                arms.extend(_reduced_arms(carrier))
    return tuple(arms)
