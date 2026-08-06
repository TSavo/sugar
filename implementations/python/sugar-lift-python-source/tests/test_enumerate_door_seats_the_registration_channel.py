"""RED: the census entrance must open its tree on a registering reporter.

Full-corpus recensus run ``31037550343`` produced eight measured shard partials
(103 panics / 76 completed / 0 instrument-failures each) and compose still
refused, naming ITSELF the missing seat::

    unmeasuredReasons: {"compose": "frontier attestation refused; ..."}
    instrumentFailures: 3

All three aggregate failures were one message::

    BACKEND DEFECT [ConstructionTestimonyReporterV1.retain_registered_node_from]
      blame:    pandas/io/parsers/readers.py:2116:0
      observed: foreign or absent producer node registration
                (producer=NullReporter, node_reporter=NullReporter)

WHICH FAULT IT WAS. ``Call._project_constructed_value_for_testimony`` calls
``retain(producer_definition, producer_definition.reporter)`` -- the producer is
the node's OWN reporter, by construction. A foreign producer is therefore
unreachable from that seat: the only way to arrive is for the node's reporter to
be one that owns no registration at all. It was ABSENCE, not foreignness. The
node was born on ``NULL_REPORTER`` because ``_handle_enumerate`` opened its tree
without a ``reporter=`` at the ``context-manager-resolutions`` level, and that
level goes on to CONSTRUCT sugar (``populate_source_derived_resource_refs`` ->
``ClassDef.sugar()``). This is the #7171 null-reporter class in a second
costume: nodes writing into a channel that can never answer.

THE ENTRANCE IS THE CENSUS ENTRANCE: ``measure_file_via_enumerate``. A bare
``SourceFile.from_path`` seats its own reporter and does not reach this.

The fix is NOT to let the retention check accept a ``NullReporter`` -- that
check is the instrument, and it is what caught this.
``test_retention_refusal_names_which_fault.py`` pins both of its arms.

CLOSED. #7382 seated the two bare enumerate opens and added
``_seat_roll_call_reporter`` for the residency-hit leak; #7383 routed the
``auditFrontier`` facts leaf through the construction door. Both fixed WHICH
reporter reaches the door. Neither could fix WHICH NODES the seating walk
reaches -- and the seating walk was minting the very shells it seated, leaving
the bind-time roster (``function_nodes`` / ``module_direct_bindings``) on the
first opener's ``NULL_REPORTER`` forever. That roster is where the frame owner
handed to retention comes from. See
``test_bind_time_roster_is_seated_too.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus

# The enrolled seat that reproduces at the aggregate level. `io/parsers/readers.py`
# is historically one of the three files that escaped the original D3 reporter
# leak by refusing before reaching it; it is the one that surfaces reporter
# seating defects.
SEAT = "io/parsers/readers.py"

ABSENT_REGISTRATION_TEXT = "producer reporter owns no registration table"
PRE_SPLIT_REFUSAL_TEXT = "foreign or absent producer node registration"

# THE HOLE UNDERNEATH. With the retention defect repaired, this seat reaches a
# DIFFERENT, pre-existing defect the refusal was shadowing::
#
#     sugar.enumerate error: {'code': -32603,
#       'message': "'SpreadCallSugar' object has no attribute 'args'"}
#     manager_summary_derivation._populate_same_module_class_manager_uses:1851
#       application = collect_application(call.sugar())
#
# A bare ``AttributeError`` names no construct, no coordinate and no shape, so
# ``_panic_from_exception`` mints no row: the file still dies and the seat is
# still a census hole -- for a different cause, which is the next repair. It is
# recorded here, strict, so the day it banks a row this tooth is told.
SHADOWED_ATTRIBUTE_ERROR = "'SpreadCallSugar' object has no attribute 'args'"


def _recensus_consumer():
    scripts = Path(__file__).resolve().parents[2] / "sugar-lift-py-tests" / "scripts"
    assert scripts.is_dir(), f"missing recensus scripts at {scripts}"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import recensus_enumerate_consumer

    return recensus_enumerate_consumer


def _measure_seat(seat: str) -> dict[str, Any]:
    """Measure ONE enrolled corpus seat exactly as a recensus shard does."""
    from sugar_lift_python_source.source_oracle import install_root_for

    corpus = authenticated_pandas_corpus().root
    target = corpus.joinpath(*seat.split("/"))
    assert target.is_file(), f"missing enrolled corpus seat {target}"
    installed = install_root_for(str(target))
    locus_root = corpus if installed is None else Path(installed)
    return _recensus_consumer().measure_file_via_enumerate(
        workspace_root=corpus,
        file_rel=seat,
        contract_refs=None,
        distribution="pandas",
        source_workspace_root=locus_root,
    )


def _instrument_failure_message(row: dict[str, Any]) -> str:
    return str((row.get("instrumentFailure") or {}).get("message") or "")


_PREFIX_WALK = r"""
import json, sys
from pathlib import Path

sys.path.insert(0, SCRIPTS)
import recensus_enumerate_consumer as consumer
from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_python_source.source_oracle import install_root_for
from sugar_source_tree.tree import SourceTree
import sugar_source_tree.panic as panic_mod

corpus = authenticated_pandas_corpus().root
roster = sorted(
    p.resolve().relative_to(corpus).as_posix() for p in SourceTree(corpus).paths()
)
index = roster.index(SEAT)

real = panic_mod.backend_defect
refusals = []


def watch(**kwargs):
    if "retain_registered_node_from" in str(kwargs.get("owner")):
        refusals.append(str(kwargs.get("observed")))
    return real(**kwargs)


panic_mod.backend_defect = watch
row = {}
try:
    for lead in roster[max(0, index - 60) : index + 1]:
        target = corpus.joinpath(*lead.split("/"))
        installed = install_root_for(str(target))
        row = consumer.measure_file_via_enumerate(
            workspace_root=corpus,
            file_rel=lead,
            contract_refs=None,
            distribution="pandas",
            source_workspace_root=corpus if installed is None else Path(installed),
        )
finally:
    panic_mod.backend_defect = real

print("RESULT_JSON " + json.dumps({
    "terminalKind": row.get("terminalKind"),
    "instrumentFailure": str((row.get("instrumentFailure") or {}).get("message") or ""),
    "refusals": refusals,
}))
"""


def _measure_corpus_prefix_ending_at(seat: str) -> tuple[dict[str, Any], list[str]]:
    """Measure the enrolled seats leading up to ``seat``, and return ITS row.

    THE PROCESS STATE IS THE REPRODUCTION. Measured alone, this seat is clean:
    nothing has opened it yet, so the census door's own reporter is the only one
    the tree ever had. In a shard it is opened long before it is measured, as a
    dependency of an earlier file's frame resolution, on the shared
    ``NULL_REPORTER`` -- and enumeration protocol §4 makes that preparation
    process-resident, so the later open inherits those nodes. Sixty preceding
    seats in roster order reproduces it.

    IN A SUBPROCESS, deliberately. Residency, walk sessions and demand memos are
    all process state, so this measurement is only itself in a process that ran
    nothing else. In-process, these guards passed alone and failed beside other
    corpus tests -- an instrument whose reading depends on what ran before it is
    not an instrument.
    """
    import json
    import subprocess

    scripts = Path(__file__).resolve().parents[2] / "sugar-lift-py-tests" / "scripts"
    program = (
        f"SEAT = {seat!r}\nSCRIPTS = {str(scripts)!r}\n" + _PREFIX_WALK
    )
    completed = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        timeout=3600,
    )
    line = next(
        (
            ln
            for ln in completed.stdout.splitlines()
            if ln.startswith("RESULT_JSON ")
        ),
        None,
    )
    assert line is not None, (
        "the prefix walk produced no result; it must never be read as clean.\n"
        f"returncode={completed.returncode}\n"
        f"stdout tail={completed.stdout[-2000:]}\n"
        f"stderr tail={completed.stderr[-2000:]}"
    )
    result = json.loads(line[len("RESULT_JSON ") :])
    row = {
        "terminalKind": result["terminalKind"],
        "instrumentFailure": {"message": result["instrumentFailure"]},
    }
    return row, list(result["refusals"])


@pytest.fixture(scope="module")
def measured_prefix() -> tuple[dict[str, Any], list[str]]:
    return _measure_corpus_prefix_ending_at(SEAT)


@pytest.fixture(scope="module")
def measured_seat(measured_prefix) -> dict[str, Any]:
    return measured_prefix[0]


# CLOSED at #7385+1 (this branch). The fourth door was not a bare open at all:
# ``_seat_roll_call_reporter`` walked ``source_file.nodes()``, and because
# ``Node.__getattr__`` memoizes child slots under a key containing
# ``self.reporter``, that walk MINTS the shells it then seats. The bind-time
# roster handed to ``SourceUnit.bind_typed_module`` -- ``function_nodes`` and
# ``module_direct_bindings`` -- is never on that walk, and it is exactly where
# ``SourceUnit`` reads the definition that becomes
# ``SourceVisibleCallFrameV1.owner``, the producer handed to retention. Seating
# that roster is the repair; see
# ``sugar-lift-python-source/tests/test_bind_time_roster_is_seated_too.py``,
# whose teeth are first-party and run in 20s.
#
# The three guards below were strict xfails and all three XPASSed on the repair,
# which is the machinery doing its job. Their markers are removed, not
# loosened: they are ordinary guards now and a regression must be red.


def test_seat_banks_a_countable_terminal(measured_seat: dict[str, Any]) -> None:
    """GUARD: the seat banks a row, not a hole.

    ``construction-panic`` is the product working -- a named, countable row.
    What is refused is a ``terminalKind`` naming neither, which is the void
    that marks the aggregate unmeasured and stops compose sealing.
    """
    assert measured_seat.get("terminalKind") in {"constructed", "construction-panic"}, (
        f"CENSUS HOLE at {SEAT}: terminalKind="
        f"{measured_seat.get('terminalKind')!r}. instrumentFailure="
        f"{_instrument_failure_message(measured_seat)[:800]}"
    )


def test_no_producer_is_born_without_a_registration_table(
    measured_prefix: tuple[dict[str, Any], list[str]],
) -> None:
    """GUARD: the SPECIFIC refusal, at the moment it would be raised.

    This is the defect itself, not its shadow. Across the whole prefix walk --
    every producer tree any of these seats resolves through -- no retention may
    be handed a node whose producer owns no registration table.
    """
    refusals = measured_prefix[1]
    absent = [text for text in refusals if ABSENT_REGISTRATION_TEXT in text]
    assert not absent, (
        f"{len(absent)} node(s) reached retention unregistered while measuring "
        f"the seats leading to {SEAT}; a producer was born on a channel that "
        f"owns no registration. first={absent[0]!r}"
    )
    stale = [text for text in refusals if PRE_SPLIT_REFUSAL_TEXT in text]
    assert not stale, (
        f"the pre-split conflated refusal is still being raised: {stale[0]!r}"
    )


def test_seat_never_names_an_unregistered_producer(
    measured_seat: dict[str, Any],
) -> None:
    """GUARD: the SPECIFIC refusal text.

    ``terminalKind`` alone is answered by anything that stops the file dying,
    including a swallow that relocated the panic. This asserts the exact
    wording the recensus banked is gone from the row -- in BOTH spellings, the
    one measured at run 31037550343 and the split-out absent arm, so this tooth
    cannot be satisfied by renaming the refusal.
    """
    message = _instrument_failure_message(measured_seat)
    assert ABSENT_REGISTRATION_TEXT not in message, (
        f"CENSUS HOLE at {SEAT}: the node is still born unregistered. "
        f"message={message[:800]}"
    )
    assert PRE_SPLIT_REFUSAL_TEXT not in message, (
        f"CENSUS HOLE at {SEAT}: the pre-split refusal still escapes as an "
        f"instrument failure. message={message[:800]}"
    )
    # The hole did not move: what is left underneath is the named, recorded
    # AttributeError, not a relocated retention refusal.
    if message:
        assert SHADOWED_ATTRIBUTE_ERROR in message, (
            f"UNEXPECTED HOLE at {SEAT}: neither the retention refusal nor the "
            f"recorded shadowed defect. message={message[:800]}"
        )


def test_the_enumerate_door_opens_on_a_registering_reporter() -> None:
    """GUARD: the MECHANISM, not the green.

    Both teeth above are satisfied by anything that stops the file dying --
    including a change elsewhere that happens to keep this one seat off the
    retention path. This asserts the thing that was actually wrong: the
    ``context-manager-resolutions`` open passes a reporter that can hold a
    registration. ``NULL_REPORTER`` cannot, and is what was passed.
    """
    from sugar_source_tree.reporter import CollectingReporter, NullReporter
    import sugar_lift_py_tests.lift_rpc as lift_rpc

    seen: list[object] = []
    real = lift_rpc.open_source_file_for_construction

    def spy(*args, **kwargs):
        seen.append(kwargs.get("reporter"))
        return real(*args, **kwargs)

    lift_rpc.open_source_file_for_construction = spy
    try:
        _measure_seat(SEAT)
    finally:
        lift_rpc.open_source_file_for_construction = real

    assert seen, "the census entrance never reached open_source_file_for_construction"
    unregistering = [
        reporter
        for reporter in seen
        if reporter is None or isinstance(reporter, NullReporter)
    ]
    assert not unregistering, (
        "the census entrance opened a construction tree on a reporter that owns "
        "no registration table; every node in that tree is born unregistered "
        f"(observed {[type(r).__name__ for r in unregistering]})"
    )
    assert any(isinstance(reporter, CollectingReporter) for reporter in seen), (
        "no CollectingReporter was seated at the census entrance -- the roster "
        "occurrence a retained producer registration is read from"
    )


def test_a_resident_tree_is_seated_onto_its_nodes_not_just_its_file() -> None:
    """GUARD: the MECHANISM, at the leak.

    ``SourceFile.__init__`` on a residency hit rebinds ``self.reporter`` and
    stops. Passing ``reporter=`` to the census door is therefore not, by
    itself, seating: the nodes keep the first opener's channel. This opens one
    small file twice -- first bare (making it resident on ``NULL_REPORTER``),
    then through the census door with a real reporter -- and demands that the
    NODES moved, not only the file object.

    Uses a first-party file, so it is fast and independent of the corpus.
    """
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
    from sugar_lift_python_source.source_oracle import workspace_path_source
    from sugar_source_tree.reporter import CollectingReporter, NullReporter
    from sugar_source_tree.tree import SourceFile

    target = Path(__file__).resolve()
    root = target.parent

    # SAME SEAT SPELLING as the door below, or residency simply misses and this
    # tooth proves nothing.
    first = SourceFile(workspace_path_source(str(target), root=str(root)))
    first_nodes = list(first.nodes())
    assert first_nodes, "no nodes materialized on the bare open"
    assert all(isinstance(n.reporter, NullReporter) for n in first_nodes)

    collector = CollectingReporter()
    second = open_source_file_for_construction(
        target, root=root, reporter=collector, populate_derived=False
    )
    assert second.reporter is collector
    unseated = [n for n in second.nodes() if n.reporter is not collector]
    assert not unseated, (
        "the resident tree's nodes still carry the first opener's reporter; "
        f"{len(unseated)} node(s) are writing into a channel this open does "
        "not hold, so nothing they register can ever be retained"
    )
    assert collector.registered, (
        "seating rebound the nodes but registered none of them -- the roll call "
        "is empty and every retention from this tree will read as absent"
    )
