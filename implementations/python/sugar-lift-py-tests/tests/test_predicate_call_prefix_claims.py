from __future__ import annotations

import pytest

from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import audit_lift_file, lift_file_payload


def _axis(source: str, file: str) -> dict:
    rpc = lift_file_payload(source, file).to_rpc()
    return account_lift_coverage(census_source(source, file=file), rpc).to_json()[
        "assertions"
    ]


def _requests_481_source() -> str:
    # requests 2.34.2 adapters.py:481, kept at its production coordinate. The
    # later Delete is the same owned-context boundary seen in sessions.py:327.
    return "\n" * 478 + (
        "class HTTPAdapter:\n"
        "    def get_connection_with_tls_context(self, request):\n"
        "        assert _is_prepared(request)\n"
        "        del request\n"
    )


def test_requests_adapters_481_prefix_predicate_call_lifts_and_cites() -> None:
    source = _requests_481_source()
    axis = _axis(source, "requests/adapters.py")

    assert axis["lifted_cited"] == 1
    assert axis["refused_loud"] == 0
    assert axis["silently_unaccounted"] == 0
    assert axis["lifted_loci"][0]["line"] == 481


def test_datetime_137_rebound_local_stays_refused_loud() -> None:
    source = "\n" * 134 + (
        "def _ord_to_ymd(year, n1, n4, n100):\n"
        "    leapyear = n1 == 3 and (n4 != 24 or n100 == 3)\n"
        "    assert leapyear == _is_leap(year)\n"
        "    del leapyear\n"
    )
    axis = _axis(source, "Lib/datetime.py")

    assert axis["lifted_cited"] == 0
    assert axis["refused_loud"] == 1
    assert axis["silently_unaccounted"] == 0
    assert axis["refused_loci"][0]["line"] == 137


def test_unliftable_predicate_operand_stays_refused_loud() -> None:
    source = "def f(x):\n    assert predicate((yield x))\n    return x\n"
    file = "unliftable-predicate.py"

    _payload, gaps = audit_lift_file(source, file, hold_panic=True)
    axis = _axis(source, file)

    assert gaps
    assert axis["lifted_cited"] == 0
    assert axis["refused_loud"] == 1
    assert axis["silently_unaccounted"] == 0


def test_rebound_formal_after_gap_stays_refused_loud() -> None:
    source = "def f(x):\n    x = transform()\n    assert p(x)\n"
    axis = _axis(source, "rebound-formal.py")

    assert axis["lifted_cited"] == 0
    assert axis["refused_loud"] == 1
    assert axis["silently_unaccounted"] == 0


def test_unrebound_formal_after_unrelated_gap_still_lifts() -> None:
    source = "def f(x):\n    missing += 1\n    assert p(x)\n"
    axis = _axis(source, "stable-formal.py")

    assert axis["lifted_cited"] == 1
    assert axis["refused_loud"] == 0
    assert axis["silently_unaccounted"] == 0


@pytest.mark.parametrize(
    "rebind",
    [
        "x = value",
        "x += 1",
        "for x in values:\n        pass",
        "with manager as x:\n        pass",
        "del x",
        "(x := value)",
    ],
)
def test_all_prior_store_and_del_shapes_fence_formal_replay(rebind: str) -> None:
    source = f"def f(x):\n    {rebind}\n    missing += 1\n    assert p(x)\n"
    axis = _axis(source, "rebind-shapes.py")

    assert axis["lifted_cited"] == 0
    assert axis["refused_loud"] == 1
    assert axis["silently_unaccounted"] == 0


def test_retained_prefix_claim_is_truthy_call_with_call_edge() -> None:
    payload = lift_file_payload(_requests_481_source(), "requests/adapters.py").to_rpc()
    assertion = next(
        row
        for row in payload["ir"]
        if any(
            warrant.get("role") == "assertion"
            for warrant in row.get("sourceWarrants", [])
        )
    )

    assert assertion["inv"] == {
        "kind": "atomic",
        "name": "py.truthy",
        "args": [
            {
                "kind": "ctor",
                "name": "call:_is_prepared",
                "args": [{"kind": "var", "name": "request"}],
            }
        ],
    }
    assert payload["callEdges"] == [
        {
            "kind": "call-edge",
            "sourceContract": "get_connection_with_tls_context",
            "targetSymbol": "call:_is_prepared",
            "callSiteLocus": {
                "file": "requests/adapters.py",
                "line": 481,
                "col": 15,
            },
            "callsite": "requests/adapters.py:481:15",
        }
    ]
