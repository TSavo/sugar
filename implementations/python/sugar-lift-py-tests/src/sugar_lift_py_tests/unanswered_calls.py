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
arm rebuild by union (``ExitSet.and_then`` for a composition, ``ExitSet.union``
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

    Read off the arms' ``owed`` slot by the one reader,
    ``ExitSet.owed_items``. A function's reduction is always a set of arms;
    anything that is not is refused by name (``_require_exit_set``).
    """
    from sugar_lift_py_tests.outcome.exit_set import _require_exit_set

    exits = _require_exit_set(outcome, owner="unanswered_calls.owed_calls")
    owed = exits.owed_items()
    return tuple(item for item in owed if isinstance(item, UnansweredCallV1))
