"""The audit door holds FactoryPanic and enumerates the frontier: a clean def
still produces its universe row, an unowned node (While) becomes a structured
gap row (and a red factory_walk row), and the walk continues. hold_panic=False
stays panic-loud for callers that demand the abort."""

from __future__ import annotations

from sugar_lift_py_tests.audit_only import AuditOnlyGap
from sugar_lift_py_tests.lift_rpc import audit_lift_file


_SOURCE = """\
def clean():
    return 1

def broken(xs):
    while xs:
        return xs[0]
    return None
"""


def test_audit_frontier_enumerates_gap_and_keeps_clean_def() -> None:
    payload, gaps = audit_lift_file(_SOURCE, "frontier.py")

    # One structured gap naming the unowned While (write more Sugar ...).
    assert len(gaps) >= 1
    assert all(isinstance(gap, AuditOnlyGap) for gap in gaps)
    while_gaps = [
        gap
        for gap in gaps
        if gap.info.get("observed") == "While"
        or "While" in gap.info.get("fix", "")
        or "While" in gap.message
    ]
    assert while_gaps, f"expected a While gap, got {[g.info for g in gaps]}"
    gap = while_gaps[0]
    assert gap.message.startswith("write more Sugar") or gap.info.get("gap_kind") == "Sugar"
    assert gap.info.get("observed") == "While"
    assert "While" in gap.info.get("fix", "") or "while" in gap.info.get("fix", "").lower()

    # Clean def still produces a universe / function-contract row.
    ir_names = [
        item.name if hasattr(item, "name") else item.get("name")
        for item in payload.ir
    ]
    assert any(name == "clean" for name in ir_names), f"expected clean universe, ir={ir_names}"


def test_audit_frontier_demand_histogram_buckets_sugar() -> None:
    _payload, gaps = audit_lift_file(_SOURCE, "frontier.py")
    by_observed: dict[str, int] = {}
    for gap in gaps:
        observed = gap.info.get("observed", "unknown")
        by_observed[observed] = by_observed.get(observed, 0) + 1
    assert by_observed.get("While", 0) >= 1


def test_unowned_default_arg_function_def_refuses_loud_in_factory_walk() -> None:
    """Bad twin: an unowned def is a factory gap, never an invisible subtree."""
    source = "def hidden(x=1):\n    assert x == 1\n"

    payload, gaps = audit_lift_file(source, "default_arg.py")

    assert len(gaps) == 1
    assert gaps[0].info["observed"] == "FunctionDef"
    assert gaps[0].info["requested"] == "statement"
    assert gaps[0].info["blame"] == "default_arg.py:1:0"
    assert len(payload.factory_walk) == 1
    row = payload.factory_walk[0]
    assert row.ast_kind == "FunctionDef"
    assert row.status == "unclassified"
    assert row.to_rpc()["status"] == "unresolved"
    assert row.to_rpc()["verdict"] == "gap"


def test_owned_ordinary_function_def_still_lifts() -> None:
    payload, gaps = audit_lift_file(
        "def ordinary(x):\n    return x\n", "ordinary.py"
    )

    assert gaps == []
    assert payload.ir
    assert payload.factory_walk[0].selected == "FunctionDefSugar"


def test_audit_frontier_feeds_pandas_wall_construction_gap_scrape() -> None:
    """The wall drinks auditOnlyGaps from the RPC error line -- the ONE door."""
    import json

    from sugar_lift_py_tests.idd.pandas_wall import summarize_pandas_construction_gaps

    _payload, gaps = audit_lift_file(_SOURCE, "frontier.py")
    err_line = "lift plugin returned error: " + json.dumps(
        {
            "code": -32603,
            "message": "audit-only construction gaps",
            "data": {"auditOnlyGaps": [gap.to_json() for gap in gaps]},
        }
    )
    summary = summarize_pandas_construction_gaps(err_line)
    assert summary.mode == "construction-gaps"
    assert summary.gaps_total >= 1
    assert summary.gaps_by_bucket.get("Sugar", 0) >= 1
    assert any(
        "While" in template for template in summary.gap_templates
    ), summary.gap_templates


def test_audit_empty_module_is_an_honest_empty_set() -> None:
    payload, gaps = audit_lift_file("# package marker only\n", "pkg/__init__.py")

    assert payload.ir == []
    assert payload.factory_walk == []
    assert payload.source_mementos == []
    assert gaps == []
