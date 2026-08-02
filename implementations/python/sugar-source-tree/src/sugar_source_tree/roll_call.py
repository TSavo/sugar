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

    def _by_coordinate(self, nodes) -> dict[tuple, RosterEntry]:
        # The lazy tree registers a logical source node many times. Equal source
        # text may share a CID at distinct loci, so the roll-call identity keeps
        # the authenticated source coordinate alongside that content identity.
        out: dict[tuple, RosterEntry] = {}
        for n in nodes:
            e = roster_entry_for(n)
            key = (e.file, e.start_line, e.start_col, e.kind, e.cid)
            out.setdefault(key, e)
        return out

    @property
    def roster(self) -> tuple[RosterEntry, ...]:
        return tuple(self._by_coordinate(self.reporter.registered).values())

    @property
    def present(self) -> tuple[RosterEntry, ...]:
        present = set(self._by_coordinate(self.reporter.present))
        return tuple(
            e
            for e in self.roster
            if (e.file, e.start_line, e.start_col, e.kind, e.cid) in present
        )

    @property
    def minority(self) -> tuple[RosterEntry, ...]:
        """registered \\ present -- roster CIDs that never discharged a present
        answer. The absent never report themselves; the roster computes them by
        difference (deduped on the CID, the one stable identity)."""
        present = set(self._by_coordinate(self.reporter.present))
        return tuple(
            e
            for e in self.roster
            if (e.file, e.start_line, e.start_col, e.kind, e.cid) not in present
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


def discharge(source_file) -> MinorityReport:
    """Run the discharge over the roster: desugar every function (which recurses
    through its whole subtree). Each node that constructs answers PRESENT through
    the template; each unwritten node reports ABSENT and stops its subtree. The
    reporter -- the one interface, threaded through construction -- now holds both
    sides, so the minority is the true diff of desugared-vs-not."""
    from .panic import SugarNotWritten

    for _ in source_file.nodes():  # materialize -> register the whole roster
        pass
    # Attempt every accounting root so each records its OWN answer: the module
    # (top-level), then each function. A written root discharges its subtree
    # present; an unwritten one (e.g. Module.sugar, still on the frontier)
    # reports absent -- honestly, by attempt, red until written.
    for root_node in (source_file.root, *source_file.functions()):
        try:
            root_node.sugar()
        except SugarNotWritten:
            pass  # the gap is on the roll; the report reads it
        except RecursionError:
            # Honest residual (H-class): construction graph too deep / cyclic
            # for this root. Convert to a named C3 refusal so the file is not
            # erased as backend-defect "maximum recursion depth exceeded".
            lc = root_node.line_col_span()
            gap = SugarNotWritten(
                owner="roll_call.discharge",
                blame=root_node.fragment,
                observed=(
                    f"RecursionError while constructing {root_node.kind} at "
                    f"{source_file.unit.filename}:{lc.start_line}:{lc.start_col}"
                ),
                requested=(
                    "bounded construction depth or a written cycle break for "
                    "this root's sugar graph"
                ),
                fix=(
                    "name the recursive edge (substitute/sugar loop) and bound "
                    "or split it; refuse specifically as ConstructionRecursionGap "
                    "— do not let RecursionError abort the roll as backend-defect"
                ),
            )
            # Board family discriminator (same field WithConstructionGap uses).
            gap.kind = "ConstructionRecursionGap"
            source_file.reporter.report_gap(root_node, gap)
            continue
    return MinorityReport(reporter=source_file.reporter)


def total_R(reports: Iterable[MinorityReport]) -> int:
    """R across many files: the size of the whole minority. R == 0 iff there is
    no minority anywhere."""
    return sum(report.R for report in reports)
