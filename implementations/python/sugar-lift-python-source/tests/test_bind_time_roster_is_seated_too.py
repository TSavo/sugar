"""RED: seating must reach the BIND-TIME roster, not only the live walk.

Full-corpus recensus run ``31076183814`` at ``cbdd870fe1ed`` measured all eight
shards clean (90 panics / 88 completed / 0 instrument-failures each) and compose
still refused, with three instrument failures that were one message::

    BACKEND DEFECT [ConstructionTestimonyReporterV1.retain_registered_node_from]
      blame:    pandas/io/parsers/readers.py:2116:0
      observed: producer reporter owns no registration table
                (producer=NullReporter, node_reporter=NullReporter)

WHICH DOOR. Instrumenting ``Call._project_constructed_value_for_testimony`` over
the sixty enrolled seats leading to that one showed the producer and the consumer
share ONE ``SourceUnit`` object (``same_unit_object: true``) while carrying
DIFFERENT reporters: consumer ``ConstructionTestimonyReporterV1``, producer
``NullReporter``. So this is not a second tree, not a second seat spelling, and
not a foreign roll -- it is two VIEWS of one tree, one of them stale.

THE MECHANISM. ``Node.__getattr__`` memoizes child slots in
``ConstructionCache.fields`` under a key that includes ``self.reporter``. So
re-seating a parent does not move its children; it makes the next read mint
FRESH child shells on the new reporter. ``_seat_roll_call_reporter`` walks
``source_file.nodes()`` (``root.walk()``), which is exactly that read: it seats
the root, then descends into newly minted shells and seats those. The shells the
walk actually needed to reach -- the ones materialized at
``Backend.materialize_module`` time and handed to
``SourceUnit.bind_typed_module`` as ``function_nodes`` /
``module_direct_bindings`` -- are never visited. They keep the first opener's
``NULL_REPORTER`` forever.

That bind-time roster is not inert. ``SourceUnit`` resolves a call's owning
definition out of ``self.function_nodes``, and that FunctionDef becomes
``SourceVisibleCallFrameV1.owner`` -- which is precisely the producer
``_project_constructed_value_for_testimony`` hands to
``retain_registered_node_from``. A node born on ``NULL_REPORTER`` owns no
registration table, so retention refuses. Correctly: the refusal is the
instrument and it is not what needs changing.

WHY #7382 AND #7383 MISSED IT. #7382 seated the two bare enumerate opens and
added ``_seat_roll_call_reporter`` for the residency-hit leak; #7383 routed the
``auditFrontier`` facts leaf through the construction door. Both fixed WHICH
reporter is passed to the door. Neither could fix WHICH NODES the seating walk
reaches, and the roster the frame owner is read from is not on that walk.

ORDER DEPENDENCE, explained by the same mechanism. Measured alone, the census
door is the first opener: the bind-time roster is minted under the real reporter
and there is nothing stale to reach. Only when an earlier seat has already made
the file resident under ``NULL_REPORTER`` does the roster go stale -- which is
why this seat is clean in isolation, why it resolved itself as a countable panic
in run ``31061976549``, and why #7385 letting numpy construct further brought it
back.

These teeth use FIRST-PARTY files: the defect is in the seating walk, not in
pandas, so it needs no corpus and runs in milliseconds.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _resident_bare_then_seated(target: Path, root: Path):
    """Open ``target`` bare (resident, NULL_REPORTER), then through the door.

    Returns ``(source_file, collector)``. SAME SEAT SPELLING for both opens or
    residency simply misses and the teeth prove nothing: residency is keyed by
    (content CID, source seat).
    """
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
    from sugar_lift_python_source.source_oracle import workspace_path_source
    from sugar_source_tree.reporter import CollectingReporter, NullReporter
    from sugar_source_tree.tree import SourceFile

    first = SourceFile(workspace_path_source(str(target), root=str(root)))
    # Force the bind-time roster to exist and be read at least once, exactly as
    # a dependency resolution would.
    assert list(first.functions()), "no functions materialized on the bare open"
    assert isinstance(first.reporter, NullReporter)

    collector = CollectingReporter()
    seated = open_source_file_for_construction(
        target, root=root, reporter=collector, populate_derived=False
    )
    assert seated.unit is first.unit, (
        "the two opens did not share one resident unit; the seat spellings "
        "differ and this measurement is about something else"
    )
    return seated, collector


@pytest.fixture(scope="module")
def seated_first_party():
    """A first-party module with NESTED definitions, deliberately.

    ``module_direct_bindings`` only holds module-level statements, so a flat
    file is seated by that roster alone and the ``function_nodes`` guard cannot
    die on its own.  ``lift_rpc`` has definitions nested inside functions and
    classes, which live in ``function_nodes`` and nowhere else -- that is what
    makes the two levers independently reachable (measured: dropping the
    function-roster loop leaves 8 stale nodes here and 0 in a flat file).
    """
    import sugar_lift_py_tests.lift_rpc as lift_rpc

    target = Path(lift_rpc.__file__).resolve()
    return _resident_bare_then_seated(target, target.parent)


def test_the_bind_time_function_roster_is_seated(seated_first_party) -> None:
    """GUARD (the defect itself): ``unit.function_nodes`` must move.

    This is the roster ``SourceUnit`` reads a call's owning definition out of,
    and that definition becomes ``SourceVisibleCallFrameV1.owner`` -- the exact
    producer handed to ``retain_registered_node_from``. If it keeps the first
    opener's channel, every retention through it reads as ABSENT.
    """
    seated, collector = seated_first_party
    stale = [
        node
        for node in seated.unit.function_nodes
        if getattr(node, "reporter", None) is not collector
    ]
    assert not stale, (
        f"{len(stale)} bind-time function node(s) still carry the first "
        f"opener's reporter (first={type(stale[0].reporter).__name__} on "
        f"{stale[0].name!r}); the frame owner read out of this roster owns no "
        "registration table, so retention refuses it as absent"
    )


def test_the_bind_time_module_bindings_are_seated(seated_first_party) -> None:
    """GUARD: ``module_direct_bindings`` is the same bind-time roster.

    Separate from ``function_nodes`` deliberately: they are two attributes
    written by ``bind_typed_module`` from the same materialization, and a fix
    that reaches one and not the other leaves half the leak open.
    """
    seated, collector = seated_first_party
    stale = [
        statement
        for statements in seated.unit.module_direct_bindings.values()
        for statement in statements
        if getattr(statement, "reporter", None) is not collector
    ]
    assert not stale, (
        f"{len(stale)} bind-time module binding statement(s) still carry the "
        f"first opener's reporter (first={type(stale[0].reporter).__name__})"
    )


def test_the_seated_roster_is_actually_registered(seated_first_party) -> None:
    """GUARD: rebinding is not seating.

    ``object.__setattr__(node, "reporter", ...)`` alone moves the label and
    registers nothing, so ``retain_registered_node_from`` would then take the
    FOREIGN arm ("producer owns a roster; this node is not in it") instead of
    the ABSENT one -- a renamed refusal, not a repair. Both arms stay closed
    only if the roster is registered on the channel it now names.
    """
    seated, collector = seated_first_party
    registered = {id(node) for node in collector.registered}
    missing = [
        node for node in seated.unit.function_nodes if id(node) not in registered
    ]
    assert not missing, (
        f"{len(missing)} bind-time function node(s) were relabelled onto this "
        "reporter without being registered on it; retention would refuse them "
        "as foreign rather than absent -- the same hole, renamed"
    )


def test_a_second_file_is_seated_the_same_way() -> None:
    """GUARD: not a property of one file.

    A fix that special-cases the file under test is answered by the tooth above.
    This repeats the whole measurement on an unrelated first-party module, so
    the seating walk has to be general.
    """
    target = Path(__file__).resolve()
    seated, collector = _resident_bare_then_seated(target, target.parent)
    stale = [
        node
        for node in seated.unit.function_nodes
        if getattr(node, "reporter", None) is not collector
    ]
    assert not stale, (
        f"{len(stale)} bind-time function node(s) unseated on a second file; "
        "the seating walk is not general"
    )
