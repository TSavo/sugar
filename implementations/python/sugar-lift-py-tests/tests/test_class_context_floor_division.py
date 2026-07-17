from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import audit_lift_file

CLASS_METHOD_FLOOR_DIVISION = (
    "class time:\n"
    "    def _cmp(self, myoff):\n"
    "        myhhmm = self._hour * 60 - myoff // timedelta(minutes=1)\n"
    "        return myhhmm\n"
    "\n"
    "    def __hash__(self, m):\n"
    "        m //= timedelta(minutes=1)\n"
    "        return m\n"
)


def test_class_method_floor_division_and_rebind_construct() -> None:
    payload, gaps = audit_lift_file(CLASS_METHOD_FLOOR_DIVISION, "datetime.py")

    messages = [gap.message for gap in gaps]
    assert not any("observed=BinOp" in message for message in messages), messages
    assert not any("observed=AugAssign" in message for message in messages), messages
    assert {row.name for row in payload.ir if row.kind == "function-contract"} >= {
        "datetime.time._cmp",
        "datetime.time.__hash__",
    }


def test_matrix_multiply_constructs_free_symbolic_body() -> None:
    """#4387: free ``x @ y`` is MatrixMultiplyOpSugar → SymbolicValue ``@``."""
    source = "def f(x, y):\n    return x @ y\n"

    payload, gaps = audit_lift_file(source, "matmul_free.py", hold_panic=False)

    assert gaps == []
    assert payload.to_rpc().get("ir")


def test_floor_division_selects_distinct_term_and_statement_sugars() -> None:
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment
    from sugar_lift_py_tests.sugar.floor_div_assign_sugar import FloorDivAssignSugar
    from sugar_lift_py_tests.sugar.floor_divide_op_sugar import FloorDivideOpSugar

    fragments = SourceFragment.from_source(
        CLASS_METHOD_FLOOR_DIVISION, "datetime.py"
    ).walk()
    floor_div = next(
        fragment
        for fragment in fragments
        if fragment.observed == "BinOp" and fragment.operator_kind() == "FloorDiv"
    )
    floor_div_assign = next(
        fragment for fragment in fragments if fragment.observed == "AugAssign"
    )

    assert FloorDivideOpSugar.owns(floor_div)
    assert not FloorDivAssignSugar.owns(floor_div)
    assert FloorDivAssignSugar.owns(floor_div_assign)
    assert not FloorDivideOpSugar.owns(floor_div_assign)


def test_real_datetime_full_file_measurement(cpython_311_datetime_path) -> None:
    """#4104 recognition frontier: SHA-pinned datetime is stable zero."""
    path = cpython_311_datetime_path
    source = path.read_text(encoding="utf-8")
    payload, gaps = audit_lift_file(source, str(path))
    rpc = payload.to_rpc()
    axis = account_lift_coverage(census_source(source, file=str(path)), rpc).to_json()[
        "assertions"
    ]

    # Crime 1 closed: every on-disk assert is lifted+cited, none silent, none
    # soft-refused. Intermediate 14/31 snapshots are retired; this is the floor.
    assert axis["stated"] == 45
    assert axis["lifted_cited"] == 45
    assert axis["refused_loud"] == 0
    assert axis["silently_unaccounted"] == 0
    assert axis["is_zero"] is True
    assert gaps == []
    assert not any(
        "floor_divide" in gap.message and "floor-gap" in gap.message for gap in gaps
    )
