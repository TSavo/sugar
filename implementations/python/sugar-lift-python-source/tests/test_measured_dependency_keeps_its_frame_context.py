"""Measuring a file does not change what a later file's dependency frame reads (#7772).

A process-level test (three files through one process), not a solver twin. It was
2 red, 1 green while a residency hit rebound ``unit.construction_context``; the
rebinding is deleted, and an open that carries a different context now prepares
its own unit. The text below records the defect as it was measured.

Three corpus files through ONE process, in manifest order, each measured exactly
as a recensus seat measures it (``measure_file_via_enumerate``):

1. ``_testing/contexts.py`` -- its frame resolution opens ``compat/_optional.py``
   as a DEPENDENCY: ``_resolve_source_visible_frame_uncached`` opens the file
   with its own producer reporter and its own ``TreeConstructionContextV1`` and
   keeps ``(source_file, producer_root, ...)`` in the walk session
   (``SourceResolutionSession.module_materializations``), which lives as long as
   the process.
2. ``compat/_optional.py`` -- measured as a corpus file. Every ``sugar.enumerate``
   level opens it through the residency door, which answered with the SAME
   resident ``SourceUnit`` and rebound ``unit.construction_context`` to that
   open's context (``process_resident_file.source_file_from_identity``, the hit
   branch; again in ``SourceFile.__init__``).
3. ``tests/io/pytables/test_file_handling.py`` -- its frame resolution asks for
   ``import_optional_dependency`` again. The session answers with the product
   from (1), but the unit now carries the context from (2). A shell's field row
   is keyed by the unit's context (``Node._coordinate``), so
   ``producer_root.body`` misses its row and mints NEW ``FunctionDef`` shells on
   the old producer reporter, whose table already holds the first shell for that
   ref. The frame owner is the unregistered second shell, and retention refuses::

       BACKEND DEFECT [ConstructionTestimonyReporterV1.retain_registered_node_from]
         blame:     pandas/compat/_optional.py:107:0
         observed:  foreign producer node registration

The file ends with no terminal state. Without (2) it ends in its named refusal
(``With._construct_sugar``, source-body-gap for ``pandas.HDFStore``).

The retention check is the instrument and is right. What is wrong is that a
value belonging to one open (the construction context) is stored on the
process-resident unit, so one file's open changes what another file's memoized
dependency product reads. The repair is not to relax the check and not to reset
state between files.

Measured on ``290632df0``. The first commit at which these three files reproduce
is ``d27b84860`` (#7679): it let ``HDFStore``'s projection reach ``__init__``,
which is the call that asks for the frame. It reached the defect; the rebinding
it reaches is older.

Two small changes were measured on corpus slice 7 of 8 (177 files); neither is
committed here. Putting the product's context back on a session hit gives the
two pytables files the refusal rows they have without the trigger and leaves the
other 175 rows unchanged, but it is one more re-seat, at one door: the prefix
door (``session.prefix_file_hit``, same file) reads the same live slot. Dropping
the session's module product moves the defect:
``tests/series/methods/test_to_csv.py`` then ends with no terminal and three
files change refusal.

IN A SUBPROCESS, deliberately: residency and walk sessions are process state, so
the reading is only itself in a process that ran nothing else.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

DEPENDENT_FIRST = "_testing/contexts.py"
DEPENDENCY = "compat/_optional.py"
DEPENDENT_LATER = "tests/io/pytables/test_file_handling.py"

TERMINALS = {"constructed", "construction-panic"}

_WALK = r"""
import json, sys
from pathlib import Path

sys.path.insert(0, SCRIPTS)
import recensus_enumerate_consumer as consumer
from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_python_source.source_oracle import install_root_for

corpus = authenticated_pandas_corpus().root
rows = []
for seat in SEATS:
    target = corpus.joinpath(*seat.split("/"))
    installed = install_root_for(str(target))
    row = consumer.measure_file_via_enumerate(
        workspace_root=corpus,
        file_rel=seat,
        contract_refs=None,
        source_workspace_root=corpus if installed is None else Path(installed),
    )
    rows.append({
        "seat": seat,
        "terminalKind": row.get("terminalKind"),
        "instrumentFailure": str((row.get("instrumentFailure") or {}).get("message") or ""),
    })
print("RESULT_JSON " + json.dumps(rows))
"""


def _measure_in_one_process(seats: tuple[str, ...]) -> list[dict[str, str]]:
    scripts = Path(__file__).resolve().parents[2] / "sugar-lift-py-tests" / "scripts"
    program = f"SEATS = {seats!r}\nSCRIPTS = {str(scripts)!r}\n" + _WALK
    completed = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        timeout=600,
    )
    line = next(
        (ln for ln in completed.stdout.splitlines() if ln.startswith("RESULT_JSON ")),
        None,
    )
    assert line is not None, (
        "the walk produced no result; it must never be read as clean.\n"
        f"returncode={completed.returncode}\n"
        f"stdout tail={completed.stdout[-2000:]}\n"
        f"stderr tail={completed.stderr[-2000:]}"
    )
    return list(json.loads(line[len("RESULT_JSON ") :]))


@pytest.fixture(scope="module")
def with_dependency_measured() -> list[dict[str, str]]:
    return _measure_in_one_process((DEPENDENT_FIRST, DEPENDENCY, DEPENDENT_LATER))


def test_control_later_file_reaches_a_terminal_when_dependency_is_not_measured() -> None:
    """CONTROL: the same two dependents, without measuring the dependency between."""
    rows = _measure_in_one_process((DEPENDENT_FIRST, DEPENDENT_LATER))
    assert [row["terminalKind"] in TERMINALS for row in rows] == [True, True], rows


def test_every_file_reaches_a_terminal_when_dependency_is_measured_between(
    with_dependency_measured: list[dict[str, str]],
) -> None:
    """Each of the three files ends constructed or refused by name."""
    without_terminal = [
        row for row in with_dependency_measured if row["terminalKind"] not in TERMINALS
    ]
    assert not without_terminal, (
        "a file ended with no terminal state after an earlier file in the same "
        f"process was measured: {without_terminal}"
    )


def test_later_frame_owner_is_the_producer_registered_occurrence(
    with_dependency_measured: list[dict[str, str]],
) -> None:
    """The dependency frame owner handed to retention is the shell its producer registered."""
    later = with_dependency_measured[-1]
    assert "retain_registered_node_from" not in later["instrumentFailure"], later
