from __future__ import annotations

from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import audit_lift_file


def test_class_method_audit_root_preserves_predicate_claim_and_call_edge() -> None:
    source = "\n" * 478 + (
        "class HTTPAdapter:\n"
        "    def get_connection_with_tls_context(self, request):\n"
        "        assert _is_prepared(request)\n"
        "        del request\n"
    )
    payload, _gaps = audit_lift_file(source, "requests/adapters.py", hold_panic=True)
    rpc = payload.to_rpc()
    assertion = next(
        row
        for row in rpc["ir"]
        if any(
            warrant.get("role") == "assertion"
            for warrant in row.get("sourceWarrants", [])
        )
    )

    assert assertion["inv"]["name"] == "py.truthy"
    assert assertion["inv"]["args"][0]["name"] == "call:_is_prepared"
    assert rpc["callEdges"][0]["callSiteLocus"]["line"] == 481


def test_class_method_audit_root_keeps_tuple_isinstance_refused_loud() -> None:
    source = "\n" * 864 + (
        "class timedelta:\n"
        "    def _cmp(self, other):\n"
        "        assert isinstance(other, (timedelta, int))\n"
        "        return other\n"
    )
    payload, gaps = audit_lift_file(
        source, "/tmp/cpython-3.11-datetime.py", hold_panic=True
    )
    assertions = account_lift_coverage(
        census_source(source, file="/tmp/cpython-3.11-datetime.py"),
        payload.to_rpc(),
    ).to_json()["assertions"]

    assert gaps[0].info["observed"] == "TupleValue"
    assert assertions["lifted_cited"] == 0
    assert assertions["refused_loud"] == 1
    assert assertions["silently_unaccounted"] == 0
