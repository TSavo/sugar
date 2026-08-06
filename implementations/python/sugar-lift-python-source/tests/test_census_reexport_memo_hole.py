"""RED: the four pandas seats the re-export memo voided must measure to rows.

Full-corpus recensus run 31005668665 came back 65 completed / 109 panics /
4 instrument-failures. All four failures were one message::

    sugar.enumerate error: {'code': -32603, 'message':
      're-export warrants do not reach the resolved definition'}

That is ``ResolvedPythonObjectV1.__post_init__`` refusing an object whose
warrant chain stops short of the module the definition actually lives in. It
names no construct, no coordinate and no shape, so ``_panic_from_exception``
mints no row: the file dies, the shard marks its partial ``measured=False``,
and all eight seats go missing from compose.

The gap was NOT real. ``resolve_export``'s terminal memo is keyed on
``(distribution_artifact_cid, module_name, exported_name)`` and stored the
resolved definition while DISCARDING the re-export hops that key resolved
through. pandas re-exports heavily, so one middle module is legitimately
reached from several importers -- the relation was always plural. The first
arrival paid the hops; every later arrival read a triple pointing at a module
its own chain never names. Composing the reader's path with the memo's stored
suffix resolves it. The unit twins are in
``test_reexport_terminal_memo_warrant_chain.py``; these are the same defect at
the census entrance, on the seats that actually banked it.

THE ENTRANCE IS THE CENSUS ENTRANCE: ``measure_file_via_enumerate``, the sole
door ``control_effect_recensus`` measures a file through. A bare
``SourceFile.from_path`` is a different door and does not reach this.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus

# The exact enrolled pandas seats that came back status=instrument-failure
# from full-corpus recensus run 31005668665. All four, one cause.
REEXPORT_MEMO_SEATS = (
    "tests/io/excel/test_writers.py",
    "tests/io/excel/test_xlrd.py",
    "tests/io/json/test_readlines.py",
    "tests/io/parser/common/test_data_list.py",
)

# ``test_writers.py`` used to clear the re-export message and still not reach a
# row: underneath it sat a DIFFERENT, pre-existing defect the re-export abort
# was shadowing::
#
#     BACKEND DEFECT [ConstructionTestimonyReporterV1.retain_registered_node_from]
#       blame:    pandas/tests/io/excel/test_writers.py:157:8
#       observed: foreign or absent producer node registration
#                 (producer=NullReporter, node_reporter=NullReporter)
#
# That registration defect is now repaired: the enumerate door seats a
# registering reporter, and a process-residency hit re-seats the roll call onto
# the tree's existing nodes rather than relabelling only the file object. See
# ``test_enumerate_door_seats_the_registration_channel.py``. This seat banks a
# row, so the xfail it carried is gone -- removed because the hole closed, not
# because the tooth was inconvenient.

def _terminal_seat(seat: str):
    """All four seats bank a row; none is held open any more."""
    return seat


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


@pytest.mark.parametrize(
    "seat", [_terminal_seat(seat) for seat in REEXPORT_MEMO_SEATS]
)
def test_reexport_memo_seat_measures_to_a_countable_terminal(seat: str) -> None:
    """GUARD: the seat banks a row, not a hole.

    Whether the row is ``constructed`` or ``construction-panic`` is not this
    tooth's business -- a panic naming construct/coordinate/shape is the
    product working. What is refused is ``terminalKind`` naming neither.

    All four seats pass. ``test_writers.py`` was held open by a second,
    pre-existing registration defect until the enumerate door was seated.
    """
    row = _measure_seat(seat)
    assert row.get("terminalKind") in {"constructed", "construction-panic"}, (
        f"CENSUS HOLE at {seat}: terminalKind={row.get('terminalKind')!r}. "
        "One hole marks the whole shard measured=False and compose cannot "
        f"seal. instrumentFailure={_instrument_failure_message(row)[:600]}"
    )


@pytest.mark.parametrize("seat", REEXPORT_MEMO_SEATS)
def test_reexport_memo_seat_never_names_the_unreached_chain(seat: str) -> None:
    """GUARD: the SPECIFIC text.

    ``terminalKind`` alone is answered by anything that stops the file dying,
    including a swallow that relocated the ``ValueError``. This asserts the
    exact wording the recensus banked is gone from the row.

    All FOUR seats pass this, including the one still held by a different
    defect: that seat's re-export message really is gone.
    """
    message = _measure_seat(seat)
    assert (
        "re-export warrants do not reach the resolved definition"
        not in _instrument_failure_message(message)
    ), (
        f"CENSUS HOLE at {seat}: the unreached warrant chain still escapes as "
        f"an instrument failure. message={_instrument_failure_message(message)[:600]}"
    )


def test_the_reaching_check_is_still_enforced() -> None:
    """GUARD: the fix did not clear the hole by deleting the refusal.

    Composing the reader's path with the memo's suffix is a fix. Dropping
    ``ResolvedPythonObjectV1``'s reaching check, or letting the memo hand back
    a chain that stops short, would ALSO clear all four seats -- while
    publishing definitions no warrant reaches. Both halves are pinned here:
    the invariant still raises, and the memo still stores its own hops.
    """
    import inspect

    from sugar_lift_python_source import dependency_export_adapter as adapter
    from sugar_lift_python_source.dependency_artifact import ResolvedPythonObjectV1

    invariant = inspect.getsource(ResolvedPythonObjectV1.__post_init__)
    assert "re-export warrants do not reach the resolved definition" in invariant, (
        "the reaching invariant must still refuse a chain that stops short"
    )
    assert "re-export warrants do not form one source chain" in invariant, (
        "the chain-continuity invariant must still refuse a broken chain"
    )

    stored = inspect.getsource(adapter._export_terminal_result)
    assert "result.reexport_warrants[prefix:]" in stored, (
        "the terminal memo must store the hops its own key resolved through"
    )
