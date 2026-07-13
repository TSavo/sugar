from __future__ import annotations

from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import audit_lift_file

SAME_MODULE_TABLE_DIG = (
    "TABLE = (10, 20)\n"
    "\n"
    "def lookup(index):\n"
    "    value = TABLE[index]\n"
    "    return value\n"
    "\n"
    "def caller(index):\n"
    "    return lookup(index) + 1\n"
)

COMPOSED_MODULE_CONSTANTS = (
    "BASE = 10\n"
    "OFFSET = BASE + 2\n"
    "TABLE = [BASE, OFFSET]\n"
    "\n"
    "def select(index):\n"
    "    return TABLE[index] + OFFSET\n"
)


def test_same_module_callee_dig_preserves_module_constant_temporal() -> None:
    payload, gaps = audit_lift_file(SAME_MODULE_TABLE_DIG, "module_table.py")

    assert not gaps
    caller = next(row for row in payload.ir if row.name == "caller")
    assert "call:lookup" in repr(caller.post)
    assert "TABLE" not in repr(gaps)


def test_same_module_tuple_constant_uses_factory_built_tuple_floor() -> None:
    payload, _gaps = audit_lift_file(SAME_MODULE_TABLE_DIG, "module_table.py")
    lookup = next(row for row in payload.ir if row.name == "lookup")

    assert "py.subscript" in repr(lookup.post)
    assert "tuple" in repr(lookup.post)
    assert "python:module" not in repr(lookup.post)


def test_module_constants_compose_arithmetic_and_list_tables_in_order() -> None:
    payload, gaps = audit_lift_file(COMPOSED_MODULE_CONSTANTS, "composed.py")

    assert not gaps
    select = next(row for row in payload.ir if row.name == "select")
    assert "py.subscript" in repr(select.post)
    assert "array" in repr(select.post)
    assert "python:module" not in repr(select.post)


def test_full_datetime_module_globals_survive_same_module_dig(
    cpython_311_datetime_path,
) -> None:
    path = cpython_311_datetime_path
    source = path.read_text(encoding="utf-8")
    payload, gaps = audit_lift_file(source, str(path), hold_panic=True)
    assertions = account_lift_coverage(
        census_source(source, file=str(path)), payload.to_rpc()
    ).to_json()["assertions"]
    messages = [gap.message for gap in gaps]

    assert assertions["lifted_cited"] == 14
    assert assertions["refused_loud"] == 31
    assert assertions["silently_unaccounted"] == 0
    assert not any("observed=_DAYS_BEFORE_MONTH" in message for message in messages)
    assert any(
        ":175:4" in message and "observed=Try requested=statement" in message
        for message in messages
    )
