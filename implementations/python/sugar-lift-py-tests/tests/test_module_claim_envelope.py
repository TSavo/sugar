from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import audit_lift_file


def test_module_assertion_uses_the_existing_testimony_claim_envelope() -> None:
    source = "days = days_before_year(5)\nassert days == 4 * 365 + 1\n"

    payload, gaps = audit_lift_file(source, "vendor.py", hold_panic=True)
    assertions = account_lift_coverage(
        census_source(source, file="vendor.py"), payload.to_rpc()
    ).to_json()["assertions"]

    assert gaps == []
    assert assertions["lifted_cited"] == 1
    assert assertions["refused_loud"] == 0
    assert assertions["silently_unaccounted"] == 0
    rows = [
        row for row in payload.to_rpc()["ir"] if row["name"] == "<module>::assertion"
    ]
    assert len(rows) == 1
    assert rows[0]["kind"] == "contract"
    assert rows[0]["sourceWarrants"][0]["role"] == "assertion"
    assert rows[0]["sourceWarrants"][0]["sourceFunctionName"] == "<module>"


def test_module_assertion_lie_keeps_a_distinct_stated_formula() -> None:
    truthful, _ = audit_lift_file(
        "days = days_before_year(5)\nassert days == 4 * 365 + 1\n",
        "truthful.py",
        hold_panic=True,
    )
    lying, _ = audit_lift_file(
        "days = days_before_year(5)\nassert days == 4 * 365 + 2\n",
        "lying.py",
        hold_panic=True,
    )

    truthful_inv = truthful.to_rpc()["ir"][0]["inv"]
    lying_inv = lying.to_rpc()["ir"][0]["inv"]
    assert truthful_inv != lying_inv
