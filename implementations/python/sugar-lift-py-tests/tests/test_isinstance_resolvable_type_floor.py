from __future__ import annotations

from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import audit_lift_file, lift_file_payload


def _datetime_cmp_source(type_arg: str = "timedelta") -> str:
    method = (
        "class timedelta:\n"
        "    def _cmp(self, other):\n"
        f"        assert isinstance(other, {type_arg})\n"
        "        return _cmp(self._getstate(), other._getstate())\n"
    )
    return "\n" * 864 + method


def _assertion_axis(source: str) -> dict:
    file = "/tmp/cpython-3.11-datetime.py"
    rpc = lift_file_payload(source, file).to_rpc()
    return account_lift_coverage(census_source(source, file=file), rpc).to_json()[
        "assertions"
    ]


def test_real_datetime_867_isinstance_assert_lifts_and_cites() -> None:
    axis = _assertion_axis(_datetime_cmp_source())

    assert axis["stated"] == 1
    assert axis["lifted_cited"] == 1
    assert axis["refused_loud"] == 0
    assert axis["silently_unaccounted"] == 0
    assert axis["lifted_loci"][0]["line"] == 867


def test_tuple_of_types_isinstance_stays_refused_loud() -> None:
    source = _datetime_cmp_source("(timedelta, int)")
    file = "/tmp/cpython-3.11-datetime.py"

    _payload, gaps = audit_lift_file(source, file, hold_panic=True)
    axis = _assertion_axis(source)

    assert gaps
    assert gaps[0].info["observed"] == "TupleValue"
    assert gaps[0].info["requested"] == "python:type coordinate dispatch"
    assert axis["lifted_cited"] == 0
    assert axis["refused_loud"] == 1
    assert axis["silently_unaccounted"] == 0


def test_resolved_class_isinstance_uses_native_tester_atom() -> None:
    source = _datetime_cmp_source()
    file = "/tmp/cpython-3.11-datetime.py"
    payload = lift_file_payload(source, file).to_rpc()

    assertion = next(
        row
        for row in payload["ir"]
        if any(
            warrant.get("role") == "assertion"
            for warrant in row.get("sourceWarrants", [])
        )
    )
    assert assertion["inv"]["name"] == "adt.is_python_type"
    assert assertion["inv"]["args"][1] == {
        "kind": "ctor",
        "name": "python:type",
        "args": [
            {
                "kind": "const",
                "sort": {"kind": "primitive", "name": "String"},
                "value": "timedelta",
            }
        ],
    }
    assert "call:isinstance" not in repr(assertion["inv"])
