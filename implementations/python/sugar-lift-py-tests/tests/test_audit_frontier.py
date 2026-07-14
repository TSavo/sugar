"""Construction frontier recovery is diagnostic-only.

Normal audit lifting is fail-fast. Explicit recovery returns the disjoint
RecoveredAuditDto and never a partial LiftReportPayloadDto.
"""

from __future__ import annotations

from sugar_lift_py_tests.kit_rpc import RecoveredAuditDto
from sugar_lift_py_tests.lift_rpc import audit_lift_file

_SOURCE = """\
def clean():
    return 1

def broken(xs):
    match xs:
        case 0:
            return xs
    return None
"""


def test_recovered_frontier_enumerates_gap_without_partial_ir() -> None:
    recovered = audit_lift_file(_SOURCE, "frontier.py", recover_panics=True)

    assert isinstance(recovered, RecoveredAuditDto)
    wire = recovered.to_rpc()
    assert wire["kind"] == "recovered-construction-audit"
    assert "ir" not in wire
    match_panics = [
        panic
        for panic in wire["panics"]
        if panic["gap"].get("observed") == "Match"
        or "Match" in panic["gap"].get("fix", "")
        or "Match" in panic["reason"]
    ]
    assert match_panics, wire["panics"]
    assert match_panics[0]["status"] == "mandatory-panic"


def test_recovered_frontier_demand_histogram_buckets_sugar() -> None:
    recovered = audit_lift_file(_SOURCE, "frontier.py", recover_panics=True)

    by_observed: dict[str, int] = {}
    for panic in recovered.to_rpc()["panics"]:
        observed = panic["gap"].get("observed", "unknown")
        by_observed[observed] = by_observed.get(observed, 0) + 1
    assert by_observed.get("Match", 0) >= 1


def test_audit_frontier_constructs_vararg_def_as_statement_binding() -> None:
    source = "def f(*args):\n    assert args\n    return args\n"

    payload, gaps = audit_lift_file(source, "default_def.py")

    def_rows = [
        row.to_rpc()
        for row in payload.factory_walk
        if row.to_rpc().get("ast_kind") == "FunctionDef"
    ]
    assert def_rows
    assert def_rows[0]["verdict"] == "complete"
    assert def_rows[0]["selected"] == "StatementFunctionDefSugar"
    assert gaps == []
    assert payload.ir == []


def test_audit_empty_module_is_an_honest_empty_set() -> None:
    payload, gaps = audit_lift_file("# package marker only\n", "pkg/__init__.py")

    assert payload.ir == []
    assert payload.factory_walk == []
    assert payload.source_mementos == []
    assert gaps == []


def test_owned_ordinary_function_def_still_lifts() -> None:
    payload, gaps = audit_lift_file("def ordinary(x):\n    return x\n", "ordinary.py")

    assert gaps == []
    assert payload.ir
    assert payload.factory_walk[0].selected == "FunctionDefSugar"
