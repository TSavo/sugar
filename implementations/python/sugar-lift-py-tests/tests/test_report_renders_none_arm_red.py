"""Report path holds per-def FactoryPanic and projects the None arm red.

AGENTS.md: sugar lift --report --visual is the match pretty-printed -- every
Some arm green-with-citation, every None arm red-with-effect. One unowned
node must not kill the workspace render; clean defs still contribute rows.
"""

from __future__ import annotations

from sugar_lift_py_tests.kit_rpc.factory_walk_row_dto import FactoryWalkRedRowDto
from sugar_lift_py_tests.lift_rpc import audit_lift_file, lift_file_payload

_SOURCE = """\
def clean():
    return 1

def broken(xs):
    while xs:
        return xs[0]
    return None
"""


def test_report_path_holds_while_and_keeps_clean_def() -> None:
    """(1) Two-def file: clean rows + red factory_walk naming While; no raise."""
    payload = lift_file_payload(_SOURCE, "frontier.py")

    ir_names = [item.name for item in payload.ir]
    assert "clean" in ir_names, f"clean def must still mint rows; ir={ir_names}"
    assert "broken" not in ir_names

    red_rows = [
        row for row in payload.factory_walk if isinstance(row, FactoryWalkRedRowDto)
    ]
    assert red_rows, f"expected a red factory_walk row; walk={payload.factory_walk}"
    while_rows = [row for row in red_rows if row.ast_kind == "While"]
    assert while_rows, f"expected While red row; red={[(r.ast_kind, r.reason) for r in red_rows]}"
    gap_row = while_rows[0]
    assert gap_row.status == "unclassified"
    assert "write more Sugar" in gap_row.reason
    assert "While" in gap_row.reason
    assert gap_row.line == 5  # while xs: inside broken

    # Green walk rows for the clean def still present.
    green_selected = [
        row.selected
        for row in payload.factory_walk
        if not isinstance(row, FactoryWalkRedRowDto)
    ]
    assert "FunctionDefSugar" in green_selected
    assert "ReturnSugar" in green_selected

    # RPC shape the visual drinks: unresolved + verdict=gap + reason.
    rpc = gap_row.to_rpc()
    assert rpc["status"] == "unresolved"
    assert rpc["verdict"] == "gap"
    assert "write more Sugar" in rpc["reason"]


def test_hold_panic_false_stays_loud() -> None:
    """True production semantics: hold_panic=False still aborts on first gap."""
    from sugar_lift_py_tests.factory.factory_gap import FactoryPanic

    try:
        audit_lift_file(_SOURCE, "frontier.py", hold_panic=False)
    except FactoryPanic as panic:
        assert panic.info.observed == "While"
        return
    raise AssertionError("hold_panic=False must re-raise FactoryPanic")
