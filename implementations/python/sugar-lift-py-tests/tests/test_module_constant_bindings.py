from __future__ import annotations

from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import audit_lift_file

MODULE_BINDINGS = (
    "GOOD = 7\n"
    "BAD = (yield 1)\n"
    "\n"
    "def good():\n"
    "    return GOOD\n"
    "\n"
    "def bad():\n"
    "    return BAD\n"
)


def test_liftable_module_assignment_seeds_constructed_floor_value() -> None:
    payload, gaps = audit_lift_file(MODULE_BINDINGS, "module_constants.py")

    good = next(row for row in payload.ir if row.name == "good")
    assert good.post["args"][1] == {
        "kind": "const",
        "sort": {"kind": "primitive", "name": "Int"},
        "value": 7,
    }
    assert not any(gap.label.endswith(":4:0") for gap in gaps)


def test_unliftable_module_rhs_does_not_bind_name_or_poison_sibling() -> None:
    payload, gaps = audit_lift_file(MODULE_BINDINGS, "module_constants.py")

    assert any(row.name == "good" for row in payload.ir)
    bad_gap = next(gap for gap in gaps if gap.label.endswith(":7:0"))
    assert "observed=BAD requested=value" in bad_gap.message


def test_module_binding_uses_factory_floor_not_parallel_symbolic_spelling() -> None:
    payload, _gaps = audit_lift_file(MODULE_BINDINGS, "module_constants.py")
    good = next(row for row in payload.ir if row.name == "good")

    assert good.post["args"][1]["kind"] == "const"
    assert good.post["args"][1]["value"] == 7
    assert "python:module" not in repr(good.post)


def test_full_datetime_module_constants_expose_target_assertions(
    cpython_311_datetime_path,
) -> None:
    path = cpython_311_datetime_path
    source = path.read_text(encoding="utf-8")
    payload, gaps = audit_lift_file(source, str(path), hold_panic=True)
    assertions = account_lift_coverage(
        census_source(source, file=str(path)), payload.to_rpc()
    ).to_json()["assertions"]

    assert assertions["silently_unaccounted"] == 0
    assert assertions["lifted_cited"] == 14
    assert assertions["refused_loud"] == 31
    assert {
        locus["line"]
        for locus in assertions["lifted_loci"]
        if locus["line"] in {53, 60, 144}
    } == {53, 60, 144}
    assert {
        locus["line"]
        for locus in assertions["lifted_loci"]
        if locus["line"] in {131, 137}
    } == {131, 137}
    assert not any(
        gap.label.endswith(suffix)
        for gap in gaps
        for suffix in (":51:0", ":58:0", ":88:0")
    )
    next_gap = next(gap for gap in gaps if gap.label.endswith(":156:0"))
    assert "observed=_DAYS_BEFORE_MONTH requested=value" in next_gap.message
