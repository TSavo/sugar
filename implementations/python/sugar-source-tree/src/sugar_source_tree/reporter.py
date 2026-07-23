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
    """The roll call every AST node carries. Construction of the node is the
    REGISTRATION (``register`` -- the node shows up on the roll); desugaring is
    the DISCHARGE, which answers with exactly one of ``present_fact`` /
    ``present_inert`` (showed up) or ``report_gap`` (SugarNotWritten -- the loud
    absent). The reporter witnesses; it decides nothing. Because the node holds
    this, ``node.sugar()`` reads it off ``self`` and hands it to the sugar it
    builds -- no interface is threaded through construction; it is carried."""

    def register(self, node: "Node") -> None: ...
    def present_fact(self, node: "Node") -> None: ...
    def present_construction(self, node: "Node", value: object) -> None: ...
    def present_inert(self, node: "Node") -> None: ...
    def report_gap(self, node: "Node", panic: "SugarNotWritten") -> None: ...


class NullReporter:
    """Answers nowhere. Explicitly carried where no report is being built."""

    __slots__ = ()

    def register(self, node: "Node") -> None:
        return None

    def present_fact(self, node: "Node") -> None:
        return None

    def present_construction(self, node: "Node", value: object) -> None:
        return None

    def present_inert(self, node: "Node") -> None:
        return None

    def report_gap(self, node: "Node", panic: "SugarNotWritten") -> None:
        return None


class CollectingReporter:
    """Accumulates the roll: every registered node, and each node's discharge.

    ``registered`` is the roster (every node constructed while this reporter was
    carried). ``gaps`` is the loud-absent discharge. ``present`` maps a node to
    its present answer. The minority is ``registered`` minus ``present`` --
    ``len(gaps)`` is the loud part of R; a registered node with no discharge at
    all is the silent part, which the required interface makes unrepresentable.
    """

    __slots__ = ("gaps", "registered", "present")

    def __init__(self) -> None:
        self.gaps: List[Tuple["Node", "SugarNotWritten"]] = []
        self.registered: List["Node"] = []
        self.present: List["Node"] = []

    def register(self, node: "Node") -> None:
        # The lazy tree re-materializes a node on every access, so register
        # fires many times per logical node; the report dedupes by CID (the
        # stable identity). Here we only collect the reference.
        self.registered.append(node)

    def present_fact(self, node: "Node") -> None:
        self.present.append(node)

    def present_construction(self, node: "Node", value: object) -> None:
        return None

    def present_inert(self, node: "Node") -> None:
        self.present.append(node)

    def report_gap(self, node: "Node", panic: "SugarNotWritten") -> None:
        self.gaps.append((node, panic))


# One shared do-nothing reporter: nodes default to it, so construction off
# the audit path allocates nothing and every node still answers .reporter.
NULL_REPORTER = NullReporter()
