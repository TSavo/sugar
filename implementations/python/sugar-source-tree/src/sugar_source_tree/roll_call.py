"""The minority report: a view over the ONE roll-call interface.

There is a single roll-call interface -- ``reporter.AuditReporter`` -- carried by
every AST node and threaded through construction. This module does NOT define a
second one; it reads the ``CollectingReporter`` that construction fills:

- ``register`` (in the node's constructor) enrolls the node -> ``registered`` is
  the roster (who SHOULD show up);
- ``present_fact`` / ``present_inert`` (the construction discharge) -> ``present`` is
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

from dataclasses import dataclass, field
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
    # roll name -> (the roll list read, how many of its answers are indexed,
    # the index). The view's own bookkeeping: not part of its identity.
    _indexed: dict = field(default_factory=dict, compare=False, repr=False)

    def _by_coordinate(self, roll: str) -> dict[tuple, RosterEntry]:
        """The named roll (``registered`` or ``present``), keyed by coordinate.

        The lazy tree registers a logical source node many times. Equal source
        text may share a CID at distinct loci, so the roll-call identity keeps
        the authenticated source coordinate alongside that content identity.

        A roll is an append-only log: the reporter only ever appends. Each
        answer on it is read once. A later question reads only what was
        appended since the last one; every reader of ``roster``, ``present``
        and ``minority`` used to re-derive the whole roll, entry by entry. A
        roll that was replaced or shortened is not the log that was indexed,
        and is read again from its first answer.

        One logical node answers through many shells, and every shell used to
        have its entry derived (locus projected, text sealed and hashed) only
        to be dropped as a repeat. The coordinate is a function of the node's
        fragment and kind: a fragment is one span of one oracle-pinned text
        under one filename, so the file, the locus projected from the span
        and the CID hashed from the text over it are all its own. A shell
        whose fragment and kind were already read on this roll is the same
        answer, and derives nothing.
        """
        nodes = getattr(self.reporter, roll)
        source, consumed, out, read = self._indexed.get(roll, (None, 0, {}, set()))
        if source is not nodes or len(nodes) < consumed:
            consumed, out, read = 0, {}, set()
        # ``len`` is re-read each step: an answer appended while this question
        # is being answered belongs to this question, as it always did.
        while consumed < len(nodes):
            node = nodes[consumed]
            consumed += 1
            answer = (node.fragment, node.kind)
            if answer in read:
                continue
            read.add(answer)
            e = roster_entry_for(node)
            key = (e.file, e.start_line, e.start_col, e.kind, e.cid)
            out.setdefault(key, e)
        self._indexed[roll] = (nodes, consumed, out, read)
        return out

    @property
    def roster(self) -> tuple[RosterEntry, ...]:
        return tuple(self._by_coordinate("registered").values())

    @property
    def present(self) -> tuple[RosterEntry, ...]:
        present = self._by_coordinate("present")
        return tuple(
            e for key, e in self._by_coordinate("registered").items() if key in present
        )

    @property
    def minority(self) -> tuple[RosterEntry, ...]:
        """registered \\ present -- roster CIDs that never discharged a present
        answer. The absent never report themselves; the roster computes them by
        difference (deduped on the CID, the one stable identity)."""
        present = self._by_coordinate("present")
        return tuple(
            e
            for key, e in self._by_coordinate("registered").items()
            if key not in present
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
    """Run the discharge over the roster: construct every accounting root
    (``node.sugar()``, step 5), which builds its whole subtree. Nothing here
    reduces a function body. Each node that constructs answers PRESENT through
    the template; each unwritten node reports ABSENT and stops its subtree. The
    reporter -- the one interface, threaded through construction -- now holds
    both sides, so the minority is the true diff of built-vs-refused."""
    from .panic import SugarNotWritten

    for _ in source_file.nodes():  # materialize -> register the whole roster
        pass
    # Attempt every accounting root so each records its OWN answer: the module
    # (top-level), then each function. A written root builds its subtree
    # present; an unwritten one reports absent -- by name.
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
