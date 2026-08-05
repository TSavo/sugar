"""RED: the census entrance must never bank a hole nobody can read.

A construction PANIC is a countable frontier row — the product working. An
INSTRUMENT FAILURE is a hole: an exception that names no construct, no
coordinate and no shape, so ``_panic_from_exception`` cannot mint a row, the
shard marks its partial ``measured=False``, and compose cannot seal. Two such
holes were voiding pandas files in the full-corpus recensus (run 30999353264):

1. ``ImportValueUseSeatingGap("resolution-target-outside-binding", …)`` — a
   bare ``ValueError`` out of ``_seat_import_value_use_receipts``. The gap is
   REAL: the authenticated target is not reachable through the binding it
   claims. It was simply not typed as a terminal. It is now
   ``ImportValueUseResolutionGap`` (a ``SugarNotWritten``), which the populate
   membrane cites at the exact use coordinate.

2. ``ConstructedValueCategoryGap`` — a bare ``TypeError`` out of
   ``live_loop_construction._seal_runtime_state``, which canonicalizes a
   loop-carried binding state OUTSIDE the reporter membrane that normally
   wraps that gap. It is now ``ConstructedValueTestimonyNotWritten``.

Neither refusal is weakened and no value category is broadened: an unresolved
target still refuses, and ``ConstructedValueV2`` still names no arm for
``cpython_adapter._Handle`` (see
``sugar-source-tree/tests/test_cpython_call_handle_testimony.py``, which
requires that the adapter handle stay out). Only the SHAPE of the refusal
changed, from a hole into a row.

THE ENTRANCE IS THE CENSUS ENTRANCE: ``measure_file_via_enumerate``, the sole
door ``control_effect_recensus`` measures a file through. ``SourceFile``,
``SourceFile.from_path`` and a bare ``open_source_file_for_construction`` with
a provisional context are all DIFFERENT doors and reach none of this — the
seats below were verified not to reproduce through them.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus

# The exact enrolled pandas seats that came back
# ``status=instrument-failure`` from the full-corpus recensus, one per cause,
# each confirmed to reproduce through this door on the pinned corpus.
IMPORT_VALUE_USE_SEAT = "io/json/_json.py"
LIVE_LOOP_SEAL_SEAT = "io/pytables.py"


def _recensus_consumer():
    scripts = (
        Path(__file__).resolve().parents[2] / "sugar-lift-py-tests" / "scripts"
    )
    assert scripts.is_dir(), f"missing recensus scripts at {scripts}"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import recensus_enumerate_consumer

    return recensus_enumerate_consumer


def _measure_seat(seat: str) -> dict[str, Any]:
    """Measure ONE enrolled corpus seat exactly as a recensus shard does.

    TWO ROOTS, as the driver carries them: ``workspace_root`` is the corpus
    (WHICH tree is measured) and ``source_workspace_root`` is the install root
    the distribution recorded its seats against (what the minted address is
    stated against). Conflating them mints an address no other checkout
    resolves, and ``require_recorded_seat`` refuses it by name.
    """
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
    failure = row.get("instrumentFailure") or {}
    return str(failure.get("message") or "")


def _panic_messages(row: dict[str, Any]) -> list[str]:
    panics = list(row.get("enumerateConstructionPanics") or [])
    return [str(panic.get("message") or "") for panic in panics] + [
        str(panic.get("observed") or "") for panic in panics
    ]


def _assert_countable_terminal(row: dict[str, Any], seat: str) -> None:
    assert row.get("terminalKind") in {"constructed", "construction-panic"}, (
        f"CENSUS HOLE at {seat}: terminalKind="
        f"{row.get('terminalKind')!r}. A shard marks its partial "
        "measured=False if ANY file is an instrument failure, so this one hole "
        "voids all 178 seats and compose cannot seal. "
        f"instrumentFailure={_instrument_failure_message(row)[:600]}"
    )


# --------------------------------------------------------------------------
# Cause 1: the unresolved import value-use is a named terminal, not a hole.
# --------------------------------------------------------------------------


def test_unresolved_import_value_use_seat_measures_to_a_countable_terminal() -> None:
    """GUARD: the ``ImportValueUseResolutionGap`` raise in
    ``_seat_import_value_use_receipts``.

    Mutating that one raise back to ``ImportValueUseSeatingGap`` (a bare
    ``ValueError``) restores exactly the instrument failure the recensus
    banked for this seat.
    """
    row = _measure_seat(IMPORT_VALUE_USE_SEAT)
    _assert_countable_terminal(row, IMPORT_VALUE_USE_SEAT)


def test_unresolved_import_value_use_never_names_the_untyped_seating_gap() -> None:
    """GUARD: the SPECIFIC text of that same raise.

    ``terminalKind`` alone is answered by anything that stops the file dying,
    including a swallow. This asserts the retired refusal's own wording is gone
    from the banked row, so a fix that merely relocated the ``ValueError``
    cannot pass. ``resolution-`` is deliberately matched WITHOUT the
    ``ImportValueUseSeatingGap`` prefix it used to carry, because the typed
    refusal keeps naming the resolution kind.
    """
    row = _measure_seat(IMPORT_VALUE_USE_SEAT)
    message = _instrument_failure_message(row)
    assert "resolution-target-outside-binding" not in message, (
        "CENSUS HOLE: the untyped seating gap still escapes as an instrument "
        f"failure. message={message[:600]}"
    )
    assert "authenticated value-use receipt did not resolve" not in message, (
        "CENSUS HOLE: the value-use refusal is still leaving the entrance as a "
        f"hole rather than a row. message={message[:600]}"
    )


def test_import_value_use_resolution_gap_is_a_countable_census_row() -> None:
    """GUARD: the class, not the raise site.

    ``_panic_from_exception`` mints a countable construction-panic row for
    ``ConstructionPanic`` and ``SugarNotWritten`` ONLY; every other exception
    becomes an instrument failure. Demoting ``ImportValueUseResolutionGap`` off
    ``SugarNotWritten`` restores the hole without touching any raise site, so
    the inheritance gets its own tooth.
    """
    from sugar_source_tree.panic import (
        ImportValueUseResolutionGap,
        SugarNotWritten,
    )

    assert issubclass(ImportValueUseResolutionGap, SugarNotWritten)
    gap = ImportValueUseResolutionGap(
        blame="pandas/io/json/_json.py:1:0",
        owner="tooth",
        observed="authenticated value-use receipt did not resolve",
        requested="a resolved Python object",
        fix="resolve the target through the binding it names",
    )
    assert "IMPORT VALUE USE RESOLUTION GAP" in str(gap)


def test_unresolved_import_value_use_is_still_refused_never_seated() -> None:
    """GUARD: that the fix did not silence the gap.

    The neighbouring arms in ``_seat_import_value_use_receipts``
    (``dynamic-export``, ``static-export-absent``, ``reexport-cycle``,
    ``ambiguous-static-export``) answer with ``seat_receipt(); continue`` —
    honest open-world exports that carry no definition coordinate. Adding
    ``target-outside-binding`` to that set would ALSO clear the hole, while
    seating an unresolved target as an authenticated value. This tooth reads
    the source of the function and refuses that shape.
    """
    import inspect

    from sugar_lift_python_source.manager_construction import (
        _seat_import_value_use_receipts,
    )

    source = inspect.getsource(_seat_import_value_use_receipts)
    assert "ImportValueUseResolutionGap" in source, (
        "the unresolved-target arm must RAISE a named terminal"
    )
    for silently_seated in (
        '"target-outside-binding"',
        "'target-outside-binding'",
        '"artifact-module-absent"',
        "'artifact-module-absent'",
    ):
        assert silently_seated not in source, (
            f"SILENCED GAP: {silently_seated} was moved into an arm that seats "
            "the receipt and continues. An unresolved target is not an "
            "open-world export; seating it lets an unresolved value ride as "
            "authenticated."
        )


# --------------------------------------------------------------------------
# Cause 2: the live-loop sealer's constructed value has a typed door.
# --------------------------------------------------------------------------


def test_live_loop_seal_seat_measures_to_a_countable_terminal() -> None:
    """GUARD: the ``try``/``except`` around ``_constructed_preimage`` in
    ``live_loop_construction._seal_runtime_state``.

    Removing that door lets ``ConstructedValueCategoryGap`` — a bare
    ``TypeError`` — leave ``sugar.enumerate``, which is exactly how
    ``cpython_adapter._Handle`` voided this seat.
    """
    row = _measure_seat(LIVE_LOOP_SEAL_SEAT)
    _assert_countable_terminal(row, LIVE_LOOP_SEAL_SEAT)


def test_live_loop_seal_seat_no_longer_leaks_the_raw_category_gap() -> None:
    """GUARD: the SPECIFIC text, at the banked row.

    The raw gap's wording ("ConstructedValueV2 names its categories") must not
    appear as an instrument failure. It may still appear inside a construction
    PANIC — that is the refusal doing its job, and this tooth deliberately does
    not forbid it.
    """
    row = _measure_seat(LIVE_LOOP_SEAL_SEAT)
    message = _instrument_failure_message(row)
    assert "unclassified constructed value category" not in message, (
        "CENSUS HOLE: the raw ConstructedValueCategoryGap still escapes as an "
        f"instrument failure. message={message[:600]}"
    )
    assert "cpython_adapter._Handle" not in message, (
        f"CENSUS HOLE: the adapter handle still voids this seat. "
        f"message={message[:600]}"
    )


def test_live_loop_sealer_names_itself_when_a_value_has_no_category() -> None:
    """GUARD: the ``owner``/``observed`` of that door, at the unit.

    The reporter membrane (``ConstructionTestimonyReporterV1``) raises the SAME
    exception class from a DIFFERENT owner, so a tooth that only asserted the
    class would survive this guard's removal. Assert the owner.
    """
    from sugar_source_tree import nodes as nodes_module
    from sugar_source_tree.live_loop_construction import _seal_runtime_state
    from sugar_source_tree.panic import ConstructedValueTestimonyNotWritten

    class _Uncategorized:
        """No named ConstructedValueV2 arm, exactly like ``_Handle``."""

    class _StandInState:
        fragment = "tooth-fragment"

        def sugar(self):
            return _Uncategorized()

    # ``_seal_runtime_state`` dispatches on ``isinstance(state, Node)``, read
    # off ``sugar_source_tree.nodes`` at call time. Widen that ONE name so the
    # stand-in reaches the Node arm; the door under test is untouched.
    real_node = nodes_module.Node

    class _AdmitsStandIn(type):
        def __instancecheck__(cls, instance) -> bool:
            return isinstance(instance, (real_node, _StandInState))

    class _NodeOrStandIn(metaclass=_AdmitsStandIn):
        pass

    nodes_module.Node = _NodeOrStandIn  # type: ignore[assignment]
    try:
        with pytest.raises(ConstructedValueTestimonyNotWritten) as gap:
            _seal_runtime_state(_StandInState())
    finally:
        nodes_module.Node = real_node  # type: ignore[assignment]

    assert gap.value.owner == "live_loop_construction._seal_runtime_state"
    assert "loop-carried binding state has no content coordinate" in gap.value.observed
    assert "_Uncategorized" in gap.value.observed


def test_live_loop_sealer_still_refuses_the_adapter_handle_category() -> None:
    """GUARD: that the fix did not admit ``_Handle`` as a value category.

    The tempting "fix" for cause 2 is a named ``_cv2_entries`` arm for
    ``cpython_adapter._Handle``. That is a broadened category over a raw parser
    object with no authenticated content, and
    ``test_raw_or_reminted_parser_handle_never_becomes_semantic_testimony``
    already rules the adapter handle out. This tooth keeps the ruling local to
    the door that was changed.
    """
    from sugar_source_tree.binding_state import (
        ConstructedValueCategoryGap,
        constructed_value_cid_v2,
    )
    from sugar_source_tree.cpython_adapter import _Handle

    handle = _Handle.__new__(_Handle)
    with pytest.raises(ConstructedValueCategoryGap) as gap:
        constructed_value_cid_v2(handle)
    assert "cpython_adapter._Handle" in str(gap.value)
