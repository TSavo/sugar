from __future__ import annotations

from sugar_lift_py_tests.idd.lift_coverage_census import (
    BodyOwnerDisposition,
    reconcile_body_owner_loci,
)
from sugar_lift_py_tests.lift_rpc import audit_lift_file
from sugar_lift_py_tests.idd.pandas_wall import summarize_pandas_completed_wall
from sugar_lift_py_tests.idd.pandas_wall import PandasWallFloors, check_pandas_wall_floors


def test_bad_twin_pre_factory_skip_is_a_typed_conservation_violation() -> None:
    source = "def kept():\n    return 1\n\ndef vanished():\n    return 2\n"
    payload, _ = audit_lift_file(source, "twins.py")
    rows = [
        row
        for row in payload.factory_walk
        if not (row.ast_kind == "FunctionDef" and row.line == 4)
    ]

    census = reconcile_body_owner_loci(source, file="twins.py", factory_rows=rows)

    assert census.complete is False
    assert [violation.locus.identity for violation in census.violations] == [
        "twins.py:4:0:FunctionDef"
    ]
    assert census.violations[0].disposition is BodyOwnerDisposition.VIOLATION


def test_good_twins_constructed_and_loud_parent_gap_conserve_subtree() -> None:
    source = "def clean():\n    return 1\n\ndef loud(xs):\n    while xs:\n        return xs[0]\n"

    payload, _ = audit_lift_file(source, "twins.py")
    rows = [row.to_rpc() for row in payload.factory_walk]
    for row in rows:
        if row.get("ast_kind") == "FunctionDef" and row.get("line") == 4:
            row["verdict"] = "gap"
            row["status"] = "unresolved"
            row["reason"] = "loud parent refusal"
    census = reconcile_body_owner_loci(
        source, file="twins.py", factory_rows=rows
    )
    by_id = {entry.locus.identity: entry.disposition for entry in census.entries}

    assert census.complete is True
    assert by_id["twins.py:1:0:FunctionDef"] is BodyOwnerDisposition.CONSTRUCTED
    assert by_id["twins.py:4:0:FunctionDef"] is BodyOwnerDisposition.LOUD_GAP
    assert by_id["twins.py:5:4:While"] in {
        BodyOwnerDisposition.LOUD_GAP,
        BodyOwnerDisposition.INACTIVE_BOUNDARY,
    }


def test_audit_report_publishes_closed_source_factory_conservation_census() -> None:
    payload, _ = audit_lift_file("def f():\n    return 1\n", "good.py")

    rpc = payload.to_rpc()
    conservation = rpc["factoryAuditSummary"]["sourceFactoryConservation"]

    assert conservation["complete"] is True
    assert conservation["sourceLoci"] == 1
    assert conservation["classificationCounts"] == {
        "constructed": 1,
        "inactive-boundary": 0,
        "loud-gap": 0,
        "violation": 0,
    }
    assert conservation["entries"][0]["locus"] == "good.py:1:0:FunctionDef"


def test_pandas_wall_counts_a_conservation_violation_as_a_gap() -> None:
    report = {
        "lineAccounting": [],
        "contracts": [],
        "callEdges": [],
        "factoryWalk": [],
        "sourceFactoryConservation": {
            "complete": False,
            "violations": [
                {
                    "locus": "lost.py:9:4:If",
                    "astKind": "If",
                    "reason": "disappeared before factory classification",
                }
            ],
        },
    }

    summary = summarize_pandas_completed_wall(report)

    assert summary.gaps_total == 1
    assert summary.gap_templates == {
        "Conservation|source→factory|If|classification": 1
    }

    floors = PandasWallFloors(
        mode="complete",
        gaps_total_ceiling=99,
        gap_template_ceilings={
            "Conservation|source→factory|If|classification": 99
        },
        green=summary.green,
        pre_bearing=summary.pre_bearing,
        implications=summary.implications,
        frontier_needle="",
        frontier_owner="",
        frontier_shape="",
    )
    assert any(
        "source-to-factory conservation violation" in breach
        for breach in check_pandas_wall_floors(summary, floors)
    )


def test_generator_expression_registers_its_deferred_body_universe() -> None:
    source = (
        "def validate(tz_comps):\n"
        "    return all(x == 0 for x in tz_comps)\n"
    )
    payload, _ = audit_lift_file(source, "datetime.py")
    conservation = payload.source_factory_conservation
    assert conservation is not None
    assert conservation.complete is True
    generator = next(
        entry for entry in conservation.entries if entry.locus.kind == "GeneratorExp"
    )
    assert generator.disposition is BodyOwnerDisposition.CONSTRUCTED
    assert any(
        row.ast_kind == "GeneratorExp" and row.line == 2
        for row in payload.factory_walk
    )
