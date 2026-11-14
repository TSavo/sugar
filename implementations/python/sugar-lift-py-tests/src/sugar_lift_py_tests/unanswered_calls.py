"""The calls a reduction leaves unanswered: each one becomes an ``undecided`` member.

Step 8 (PR B on #7766): a Python call whose callee nothing here resolved is
recorded once, as an ``undecided`` member with ``reason: unanswered``. Its
``symbol`` is the target symbol the one import table (#7837) holds at the
callee's own coordinate when the callee is import-bound, else ``None`` (Q5: a
call with no symbol is still a member). Its ``site`` is the call's
``SourceFragmentCoordinateV1``.

A call is left unanswered where the lifter does not have its callee: the
two-faced call of ``UnknownCalleeCallV1.faces`` (#7585), which is also the
call to an authenticated callee cited off the enrolled population. Every
other operation whose raise is not decided here (an undecided operand's
dunder, an opaque attribute or subscript, a formal-selected manager step, a
native operation its caller left without an actual) is the same two-faced
outcome and owes the same member. "Not decided here" is stated one way: the
one constructor, ``ExitSet.two_faced``, puts one ``UnansweredCallV1`` on the
``owed`` slot of BOTH its arms (#7825, H4; #7757 item 13), since the
operation is incurred whether it then completes or raises. ``owed`` rides every
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
    """The owed item for one unanswered operation at ``site``: the one mint.

    ``site`` is the operation's source fragment, or the
    ``SourceFragmentCoordinateV1`` already minted for it. Anything else (no
    site, a synthetic slot id, prose blame) names no fragment, so the item is
    siteless: it is carried like any other and refused by name where it
    would become a member (``tree_enumerate.unanswered_call_rows``).
    """
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )

    if isinstance(site, SourceFragmentCoordinateV1):
        return UnansweredCallV1(symbol, site)
    if hasattr(site, "line_col_span") and hasattr(site, "source_cid"):
        from sugar_lift_py_tests.caller_parameter_contract import source_coordinate

        return UnansweredCallV1(symbol, source_coordinate(site))
    return UnansweredCallV1(symbol, None)


def owed_calls(outcome) -> tuple[UnansweredCallV1, ...]:
    """Every unanswered call a reduction's final outcome owes, in arm order.

    Read off the arms' ``owed`` slot. A deferred native operation
    (``NativeOperationExitCarrierV1``) has no arms of its own until a caller
    discharges it, but the arms ``ExitSet.sequence`` composed beside it and
    the stopping faces of its short circuits were reduced: their items are
    read there, and a later carrier waiting beside it is read the same way.
    """
    from sugar_lift_py_tests.outcome.exit_set import ExitSet

    owed = ExitSet(_reduced_arms(outcome)).owed_items()
    return tuple(item for item in owed if isinstance(item, UnansweredCallV1))


def _reduced_arms(outcome) -> tuple:
    """Every reduced arm of ``outcome``, in arm order, for ``owed_calls``.

    The arms of an ``ExitSet``; for a deferred carrier, the stopping faces of
    its short circuits, then for each ``sequence`` composition enrolled on it
    (``composed_beside``) the arms already resolved, the prefix arm its exits
    go beneath, and each later waiting prefix arm followed by the reduced
    arms of its carrier. Their debts are joined by the one reader,
    ``ExitSet.owed_items``.
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
    for beside in outcome.composed_beside():
        arms.extend(beside.resolved)
        arms.append(beside.prefix)
        for _position, prefix_exit, carrier in beside.rest:
            arms.append(prefix_exit)
            if carrier is not outcome:
                arms.extend(_reduced_arms(carrier))
    return tuple(arms)
