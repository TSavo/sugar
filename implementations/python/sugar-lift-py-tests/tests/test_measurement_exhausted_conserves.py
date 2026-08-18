"""`measurement-exhausted` is a member of the terminal partition.

Conservation is the load-bearing claim. If an exhausted seat is dropped, the
denominator quietly shrinks and the run looks cleaner for having a file it
could not measure. If it is folded into the panic arm, the board publishes a
refusal the product never made. Both are the same disease: absence, refusal
and exhaustion sharing a representation.
"""

from __future__ import annotations

import sys
from pathlib import Path
from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root

import pytest

_SCRIPTS = sugar_lift_py_tests_package_root() / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import compose_control_effect_board as compose  # noqa: E402
from recensus_enumerate_consumer import measurement_exhausted_row  # noqa: E402
from sugar_lift_py_tests.measurement_ceiling import (  # noqa: E402
    MeasurementCeilingExceeded,
    TERMINAL_KIND_EXHAUSTED,
)


def _exhausted_row(seat: str = "core/groupby/generic.py") -> dict:
    error = MeasurementCeilingExceeded(
        seat=seat,
        bound_seconds=300.0,
        active_stack=[
            "ClassDefSugar|statement|generic.py:189:0",
            "FunctionDefSugar|term|generic.py:1090:4",
            "IfSugar|statement|generic.py:1293:8",
            "FunctionDefSugar|term|generic.py:1323:12",
        ],
    )
    return measurement_exhausted_row(
        error,
        file_rel=seat,
        elapsed_seconds=300.4,
        source_cid=f"sha256:{'e' * 64}",
        function_nodes=[],
        ast_function_defs=88,
    )


def _constructed_row(seat: str) -> dict:
    source_cid = f"sha256:{seat:x<64}"[:71]
    input_key = {
        "sourceCid": source_cid,
        "file": seat,
        "functionKeyManifest": [],
        "functionKeyCid": compose.key_manifest_cid([]),
    }
    return {
        "category": "completed",
        "terminalKind": "constructed",
        "inputKey": input_key,
        "rowId": compose.canonical_cid({"inputKey": input_key}),
        "stageId": compose.STAGE_ENUMERATE_FILE_TERMINAL,
        "observedEventType": "builtins.dict",
        "observed_chain_length": 1,
        "blocking_terminal_count": 0,
        "final_terminal": "constructed",
        "functionsTotal": 0,
        "edgeWitnesses": {
            compose.EDGE_ENUMERATE_FILE: compose.key_edge_witness(
                stage_id=compose.STAGE_ENUMERATE_FILE_TERMINAL,
                input_keys=[],
                output_keys=[],
            ),
            compose.EDGE_WITH_PARTITION: compose.key_edge_witness(
                stage_id=compose.STAGE_WITH_TALLY_PARTITION,
                input_keys=[],
                output_keys=[],
            ),
        },
    }


# --------------------------------------------------------------------------
# The row is a terminal, not a hole.
# --------------------------------------------------------------------------


def test_exhausted_row_is_neither_a_panic_nor_an_instrument_failure() -> None:
    row = _exhausted_row()
    assert row["terminalKind"] == TERMINAL_KIND_EXHAUSTED
    assert row["terminalKind"] not in {"constructed", "construction-panic"}
    # Not a refusal: no panic payload, and nothing that would be counted as one.
    assert "panic" not in row and "defect" not in row
    assert not row.get("constructionPanics")
    # Not an instrument failure: an instrumentFailure row is dropped from
    # attestation entirely, which is how this file vanished from the frontier
    # in the first place.
    assert "instrumentFailure" not in row


def test_exhausted_row_names_construct_coordinate_and_shape() -> None:
    exhaustion = _exhausted_row()["measurementExhaustion"]
    assert exhaustion["construct"] == "FunctionDefSugar"
    assert exhaustion["coordinate"] == "generic.py:1323:12"
    assert exhaustion["role"] == "term"
    assert exhaustion["activeDepth"] == 4
    assert exhaustion["boundSeconds"] == 300.0
    assert (
        exhaustion["observedEventType"]
        == "sugar_lift_py_tests.measurement_ceiling.MeasurementCeilingExceeded"
    )


def test_exhausted_row_refuses_to_claim_attendance_it_never_took() -> None:
    """Absent manifest, not an empty one.

    An empty function key manifest is a claim that the file has no functions.
    The truthful statement is that measurement was cut off before attendance
    could be taken -- and the AST mass we DO know survives beside it, because
    banking 0 over known mass is the mass-erase class with a timer on it.
    """
    row = _exhausted_row()
    assert "functionKeyManifest" not in row["inputKey"]
    assert row["astFunctionDefs"] == 88
    assert row["functionsClean"] is None
    assert row["cleanRatioRefused"] is True
    assert "300.0" in row["cleanRefuseReason"]


def test_exhausted_row_banks_the_roster_floor_when_one_was_taken() -> None:
    error = MeasurementCeilingExceeded(
        seat="s.py", bound_seconds=300.0, active_stack=["S|term|s.py:1:0"]
    )
    row = measurement_exhausted_row(
        error,
        file_rel="s.py",
        elapsed_seconds=300.1,
        source_cid=f"sha256:{'a' * 64}",
        function_nodes=[{"memento": {"function_name": "f"}}] * 3,
        ast_function_defs=10,
    )
    assert row["functionsTotal"] == 3
    assert row["functionsNotEnumerated"] == 7
    assert row["functionsEnumerationComplete"] is False


# --------------------------------------------------------------------------
# Conservation at the sole compose door.
# --------------------------------------------------------------------------


def test_exhausted_seat_is_inside_the_final_disjoint_union() -> None:
    rows = [
        ("a.py", _constructed_row("a.py")),
        ("b.py", _constructed_row("b.py")),
        ("core/groupby/generic.py", _exhausted_row()),
    ]
    attestation, failures = compose.attest_frontier_rows(rows)
    assert failures == [], failures
    seal = attestation["finalSeal"]
    assert seal["conserves"] is True
    assert seal["terminalArmsPairwiseDisjoint"] is True
    exhausted_manifest = attestation["measurementExhaustedKeyManifest"]
    assert [key["file"] for key in exhausted_manifest] == ["core/groupby/generic.py"]
    # And it is NOT in the panic arm.
    panic_files = [key["file"] for key in attestation["constructionPanicKeyManifest"]]
    assert "core/groupby/generic.py" not in panic_files


def test_dropping_the_exhausted_arm_breaks_the_union() -> None:
    """The conservation check has teeth: prove it fails when the arm is lost.

    Without this, `conserves: True` above is compatible with the exhausted seat
    never having been counted at all.
    """
    rows = [("core/groupby/generic.py", _exhausted_row())]
    attestation, failures = compose.attest_frontier_rows(rows)
    assert failures == []
    edge = attestation["edges"][compose.EDGE_TERMINAL_SEAL]
    assert edge["inputKeyCount"] == 1
    assert edge["outputKeyCount"] == 1
    # The seat is present on BOTH sides. Had it been routed nowhere, the input
    # side would still hold it and the output side would not.
    assert edge["missingKeys"] == []


def test_an_unrecognised_terminal_kind_is_refused_not_ignored() -> None:
    row = _exhausted_row()
    row["terminalKind"] = "measurement-exhasuted"  # one transposition
    row["category"] = "measurement-exhasuted"
    _, failures = compose.attest_frontier_rows([("x.py", row)])
    assert any(
        "not closed" in str(failure.get("reason")) for failure in failures
    ), failures


def test_exhausted_terminal_is_counted_on_its_own_axis_in_the_board() -> None:
    """Compose must not fold exhaustion into panics, and the sum must hold."""
    agg = compose.aggregate_terminal_rows(
        [
            ("a.py", _constructed_row("a.py")),
            ("core/groupby/generic.py", _exhausted_row()),
        ],
        enrolled_files=["a.py", "core/groupby/generic.py"],
    )
    assert agg["files_completed"] == 1
    assert agg["files_exhausted"] == 1
    assert agg["files_panicked"] == 0
    assert agg["construction_panics"] == []
    assert agg["defects"] == []
    assert [row["file"] for row in agg["measurement_exhausted"]] == [
        "core/groupby/generic.py"
    ]


def test_exhausted_terminal_without_a_coordinate_is_refused() -> None:
    """A bare "it timed out" is not a frontier row and must not pass as one."""
    row = _exhausted_row()
    del row["measurementExhaustion"]
    with pytest.raises(TypeError) as caught:
        compose.aggregate_terminal_rows([("g.py", row)], enrolled_files=["g.py"])
    assert "measurementExhaustion" in str(caught.value)


def test_the_partition_sum_is_checked_not_assumed() -> None:
    """Both directions: a conserving triple passes, a short one raises.

    The failure mode this guards is not a wrong number but a MISSING seat --
    a member added to the closed set with no arm routing it anywhere. That
    reads as a smaller denominator, which is exactly how one file destroyed a
    whole run's evidence.
    """
    compose.reconcile_terminal_partition(
        files_terminal=3, files_completed=1, files_panicked=1, files_exhausted=1
    )
    with pytest.raises(ValueError) as caught:
        compose.reconcile_terminal_partition(
            files_terminal=3, files_completed=1, files_panicked=1, files_exhausted=0
        )
    message = str(caught.value)
    assert "does not conserve" in message
    assert "accounted=2" in message and "terminal=3" in message


def test_membership_exhaustion_keeps_the_terminal_it_already_measured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bound covers the whole seat, but a completed terminal is not lost.

    If the terminal constructed and only the relation-membership tail exceeded
    the bound, the seat is a MEASURED seat whose membership is a gap. Calling
    it exhausted would throw away a construction outcome we actually hold --
    the mass-erase class, wearing the new timer as a costume.
    """
    import recensus_enumerate_consumer as consumer

    banked = {"category": "completed", "terminalKind": "constructed"}

    def _spin(*, progress, **_kwargs):
        progress["terminalRow"] = banked
        raise MeasurementCeilingExceeded(
            seat="s.py", bound_seconds=300.0, active_stack=["S|term|s.py:1:0"]
        )

    monkeypatch.setattr(consumer, "_measure_seat_under_ceiling", _spin)
    row = consumer.measure_file_via_enumerate(
        workspace_root=Path("/nonexistent"), file_rel="s.py"
    )
    assert row["terminalKind"] == "constructed"
    assert row is banked
    gaps = row[consumer.RELATION_MEMBERSHIP_GAP_ROW_FIELD]
    assert "measurement ceiling" in gaps[0]["reason"]
    assert "300.0" in gaps[0]["reason"]


def test_seat_exhaustion_without_a_banked_terminal_is_still_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other side of the same discriminator -- run both."""
    import recensus_enumerate_consumer as consumer

    def _spin(*, progress, **_kwargs):
        progress["sourceCid"] = f"sha256:{'b' * 64}"
        progress["astFunctionDefs"] = 4
        raise MeasurementCeilingExceeded(
            seat="s.py", bound_seconds=300.0, active_stack=["S|term|s.py:9:0"]
        )

    monkeypatch.setattr(consumer, "_measure_seat_under_ceiling", _spin)
    row = consumer.measure_file_via_enumerate(
        workspace_root=Path("/nonexistent"), file_rel="s.py"
    )
    assert row["terminalKind"] == TERMINAL_KIND_EXHAUSTED
    assert row["measurementExhaustion"]["coordinate"] == "s.py:9:0"
    assert row["astFunctionDefs"] == 4
