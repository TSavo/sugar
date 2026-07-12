from __future__ import annotations

import ast
from pathlib import Path

import pytest

from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import audit_lift_file


VENDOR = Path(__file__).parent / "vendor" / "cpython-3.11" / "datetime.py"
LIFTED_DATETIME_ASSERTS = (
    53, 60, 65, 67, 131, 137, 144, 243, 274, 328, 504, 618, 620, 625, 626, 627, 628,
    633, 636, 640, 641, 643, 647, 648, 652, 668, 669, 670, 671, 679, 680,
    681, 867, 1126, 1440, 1480, 1507, 1510, 1889, 2044, 2047,
)


def _negate_assertion(source: str, line: int) -> str:
    tree = ast.parse(source, filename=str(VENDOR))
    assertion = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assert) and node.lineno == line
    )
    assert assertion.lineno == assertion.end_lineno
    rows = source.splitlines(keepends=True)
    row = rows[line - 1]
    start = assertion.test.col_offset
    end = assertion.test.end_col_offset
    row = f"{row[:start]}not ({row[start:end]}){row[end:]}"
    rows[line - 1] = row
    return "".join(rows)


@pytest.mark.parametrize("line", LIFTED_DATETIME_ASSERTS)
def test_datetime_lifted_assertion_bad_twin_refuses_loudly(line: int) -> None:
    """Every claimed datetime fact rejects its exact negated full-file twin."""
    source = _negate_assertion(VENDOR.read_text(encoding="utf-8"), line)
    filename = str(VENDOR)
    payload, _gaps = audit_lift_file(source, filename, hold_panic=True)
    assertions = account_lift_coverage(
        census_source(source, file=filename), payload.to_rpc()
    ).to_json()["assertions"]

    refused_lines = {locus["line"] for locus in assertions["refused_loci"]}
    assert line in refused_lines, (
        f"datetime.py:{line} accepted its negated twin; "
        "a claimed assertion must discriminate, never rubber-stamp"
    )
    assert assertions["silently_unaccounted"] == 0
