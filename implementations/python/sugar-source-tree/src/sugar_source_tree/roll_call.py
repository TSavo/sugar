"""The minority report: a view over the ONE roll-call interface.

There is a single roll-call interface -- ``reporter.AuditReporter`` -- carried by
every AST node and threaded through construction. This module does NOT define a
second one; it reads the ``CollectingReporter`` that construction fills:

- ``register`` (in the node's constructor) enrolls the node -> ``registered`` is
  the roster (who SHOULD show up);
- ``present_fact`` / ``present_inert`` (the desugar discharge) -> ``present`` is
  who DID show up;
- ``report_gap`` (SugarNotWritten) -> ``gaps`` is the loud absent.

The **minority is ``registered`` minus ``present``**. ``R`` is its size; ``R ==
0`` iff there is no minority. A registered node that never discharged and never
gapped is the silent part -- unrepresentable, because the constructor requires
the interface and desugar is never a fallback: every constructed node discharges
present or reports absent.

The report never consults construction internals -- only the collected roll --
so it is testable from a ``CollectingReporter`` you fill by hand, no lift.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class RosterEntry:
    """One accountable node, content-addressed. Identity is the CID."""

    cid: str
    kind: str
    name: str
    file: str
    start_line: int
    start_col: int

    def __hash__(self) -> int:
        return hash(self.cid)


def roster_entry_for(node) -> RosterEntry:
    """A roster entry for one node -- its CID, kind, name, and locus, from the
    node's oracle-pinned fragment. Constructs nothing new."""
    lc = node.line_col_span()
    return RosterEntry(
        cid=node.fragment.seal().cid,
        kind=node.kind,
        name=getattr(node, "name", None) or node.kind,
        file=node.unit.filename,
        start_line=lc.start_line,
        start_col=lc.start_col,
    )


@dataclass(frozen=True)
class MinorityReport:
    """A view over the roll a ``CollectingReporter`` collected. The minority is
    ``registered`` minus ``present`` -- nothing here consults construction, only
    the collected roll."""

    reporter: object  # a reporter.CollectingReporter

    @property
    def roster(self) -> tuple[RosterEntry, ...]:
        return tuple(roster_entry_for(n) for n in self.reporter.registered)

    @property
    def present(self) -> tuple[RosterEntry, ...]:
        return tuple(
            roster_entry_for(n)
            for n in self.reporter.registered
            if id(n) in self.reporter.present
        )

    @property
    def minority(self) -> tuple[RosterEntry, ...]:
        """registered \\ present -- registered nodes that never discharged a
        present answer. The absent never report themselves; the roster (the
        registered set) computes them by difference."""
        return tuple(
            roster_entry_for(n)
            for n in self.reporter.registered
            if id(n) not in self.reporter.present
        )

    @property
    def R(self) -> int:
        return len(self.minority)

    @property
    def is_clean(self) -> bool:
        """R == 0: no minority -- every registered node showed up."""
        return self.R == 0


def minority_report(source_file) -> MinorityReport:
    """The report for a file, over its construction reporter. The file must have
    been constructed with a ``CollectingReporter``; materializing the whole tree
    registers every node (the roster). Before any desugar the minority is the
    whole roster -- the honest 'accounted for nothing yet.'"""
    for _ in source_file.nodes():  # materialize the tree -> register every node
        pass
    return MinorityReport(reporter=source_file.reporter)


def total_R(reports: Iterable[MinorityReport]) -> int:
    """R across many files: the size of the whole minority. R == 0 iff there is
    no minority anywhere."""
    return sum(report.R for report in reports)
