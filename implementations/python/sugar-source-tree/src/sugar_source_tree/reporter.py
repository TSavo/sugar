"""The audit reporter: a node's channel for testifying its own gaps.

Every node is constructed WITH a reporter (``materialize`` threads it; a
node hands its own reporter to each child it resolves). When a node cannot
produce its sugar -- the base ``Node.sugar()`` throw, the loud MISSING --
it first reports that gap through this channel. The reporter is where the
corpus-wide census (R = count of unwritten sugars) re-homes now that the
factory's audit walk is gone: coverage is the class hierarchy, and the
frontier is whatever the reporter collected while the tree was walked.

Two arms, both silent about policy:

- ``NullReporter`` -- the default. Reports nowhere. Normal enumeration
  carries this: a gap is reported into the void and then thrown, loud.
- ``CollectingReporter`` -- an audit walk holds one and reads ``.gaps``
  afterward. Collecting a gap does NOT suppress the throw; the caller
  that wants to survive past a gap catches ``SugarNotWritten`` itself.

The reporter never decides whether to panic. It only witnesses. The floor
(R>0 => red) lives in the count it holds, not in any choice it makes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Protocol, Tuple, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover
    from .nodes import Node
    from .panic import SugarNotWritten


@runtime_checkable
class AuditReporter(Protocol):
    """You may tell me a node had no sugar. I decide nothing."""

    def report_gap(self, node: "Node", panic: "SugarNotWritten") -> None: ...


class NullReporter:
    """Reports nowhere. The default a node carries when no one is auditing."""

    __slots__ = ()

    def report_gap(self, node: "Node", panic: "SugarNotWritten") -> None:
        return None


class CollectingReporter:
    """Accumulates every reported gap in walk order. An audit walk holds one.

    ``gaps`` is the frontier: the (node, panic) pair for each unwritten
    sugar the walk reached. ``len(gaps)`` is R.
    """

    __slots__ = ("gaps",)

    def __init__(self) -> None:
        self.gaps: List[Tuple["Node", "SugarNotWritten"]] = []

    def report_gap(self, node: "Node", panic: "SugarNotWritten") -> None:
        self.gaps.append((node, panic))


# One shared do-nothing reporter: nodes default to it, so construction off
# the audit path allocates nothing and every node still answers .reporter.
NULL_REPORTER = NullReporter()
