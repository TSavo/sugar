"""Recensus is a sugar.enumerate consumer — no private walk side door."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "implementations/python/sugar-lift-py-tests/scripts"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    # scripts import each other by bare name
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec.loader.exec_module(mod)
    return mod


CONSUMER = _load(
    "recensus_enumerate_consumer",
    SCRIPTS / "recensus_enumerate_consumer.py",
)
RECENSUS = _load(
    "control_effect_recensus",
    SCRIPTS / "control_effect_recensus.py",
)


def test_measure_file_is_retired_side_door() -> None:
    with pytest.raises(RuntimeError, match="retired side door"):
        RECENSUS._measure_file(
            Path("x.py"),
            relative="x.py",
            workspace_root=Path("."),
        )


def test_consumer_source_forbids_private_walk_imports() -> None:
    text = (SCRIPTS / "recensus_enumerate_consumer.py").read_text(encoding="utf-8")
    assert "open_source_file_for_construction" not in text or text.count(
        "open_source_file_for_construction"
    ) <= 2
    assert "SourceFile(" not in text
    assert "sugar.enumerate" in text
    assert CONSUMER.SCOREBOARD_AUTHORITY is False


def test_production_loop_calls_enumerate_consumer_not_measure_file() -> None:
    text = (SCRIPTS / "control_effect_recensus.py").read_text(encoding="utf-8")
    assert "measure_file_via_enumerate" in text
    # The only reference to _measure_file should be the retired stub definition
    # and error strings — not a production call site.
    assert "row = _measure_file(" not in text
    assert "row = measure_file_via_enumerate(" in text


def test_terminal_from_enumerate_maps_roster_and_panics() -> None:
    row = CONSUMER.terminal_from_enumerate(
        file_rel="pkg/mod.py",
        function_nodes=[{"memento": {"function_name": "a"}}, {"memento": {"function_name": "b"}}],
        function_gaps=[],
        audit={
            "semanticCore": {
                "status": "failed",
                "panics": [
                    {
                        "kind": "ConstructionPanic",
                        "reason": "write more Sugar",
                        "gap": {"kind": "SugarNotWritten", "reason": "write more Sugar"},
                        "locus": "pkg/mod.py:1:0",
                    }
                ],
            }
        },
        construction_gaps=[],
    )
    assert row["enumerateSource"] is True
    assert row["functionsTotal"] == 2
    assert row["families"].get("SugarNotWritten") == 1
    assert row["category"] == "completed"  # roster present; residual in families


def test_functions_gap_without_nodes_is_defect() -> None:
    row = CONSUMER.terminal_from_enumerate(
        file_rel="pkg/mod.py",
        function_nodes=[],
        function_gaps=[{"reason": "no such file"}],
        audit=None,
        construction_gaps=[],
    )
    assert row["category"] == "backend-defect"
    assert row["functionsTotal"] == 0


def test_c3_enrolled_demand_unresolved_emits_artifact_fields_and_list() -> None:
    """A/B: residual with EnrolledDemandUnresolved → defect wire + named list."""
    from sugar_lift_py_tests.context_manager_resolution import (
        ContextManagerResolutionGapV1,
        SourceFragmentCoordinateV1,
    )
    from sugar_source_tree.panic import ContextManagerResolutionConstructionGap

    site = SourceFragmentCoordinateV1("blake3-512:" + ("ab" * 32), 3, 4, 3, 13)
    gap = ContextManagerResolutionGapV1(
        "demand:blake3-512:cm",
        site,
        "context-manager:dependency.manager",
        "unresolved-symbol",
        (),
    )
    residual = ContextManagerResolutionConstructionGap(
        blame=site,
        kind=gap.kind,
        demand_cid=gap.demand_cid,
        candidate_member_cids=(),
        coordinate=site,
        owner="With._construct_sugar",
        observed="authenticated preconstruction resolution gap: unresolved-symbol",
        requested="one resolved authenticated ContextManagerContractRefV1",
        fix="publish or resolve the exact typed CM contract",
        resolution=gap,
    )
    assert residual.decidability is not None
    assert residual.decidability.holds({"enrolled_demand_unresolved": False}) is False

    row = CONSUMER.terminal_from_enumerate(
        file_rel="pandas/io/json/_json.py",
        function_nodes=[{"memento": {"function_name": f"f{i}"}} for i in range(62)],
        function_gaps=[],
        audit=None,
        construction_gaps=[],
        residual_phase_failed=True,
        residual_error=residual,
    )
    assert row["category"] == "designed-gap"
    assert row["R_source_undecidable_refusals"] == 1
    assert len(row["sourceUndecidableRefusals"]) == 1
    inhab = row["sourceUndecidableRefusals"][0]
    assert inhab["decidabilityKind"] == "EnrolledDemandUnresolved"
    assert inhab["demandFamily"] == "context-manager"
    assert inhab["demandCid"] == "demand:blake3-512:cm"
    assert inhab["gapKind"] == "unresolved-symbol"
    assert inhab["expectedRefType"] == "ContextManagerContractRefV1"
    assert inhab["useSite"]
    assert inhab["file"] == "pandas/io/json/_json.py"
    # Defect row carries the same artifact fields (A).
    defect = row["defect"]
    assert defect["decidabilityKind"] == "EnrolledDemandUnresolved"
    assert defect["demandFamily"] == "context-manager"
    assert defect["honestResidual"] is True
    assert row["families"].get("EnrolledDemandUnresolved") == 1


def test_c3_honest_without_sealed_ground_is_not_source_undecidable_count() -> None:
    """Recursion honest residual is designed-gap but not EnrolledDemandUnresolved."""
    row = CONSUMER.terminal_from_enumerate(
        file_rel="pkg/deep.py",
        function_nodes=[{"memento": {"function_name": "f"}}],
        function_gaps=[],
        audit=None,
        construction_gaps=[],
        residual_phase_failed=True,
        residual_error=RecursionError("maximum recursion depth exceeded"),
    )
    assert row["category"] == "designed-gap"
    assert row["R_source_undecidable_refusals"] == 0
    assert row["sourceUndecidableRefusals"] == []
    assert "decidabilityKind" not in (row.get("defect") or {})


def test_live_enumerate_roster_on_fixture(tmp_path: Path) -> None:
    """D2 against real sugar.enumerate handler (in-process)."""
    src = tmp_path / "mod.py"
    src.write_text(
        "def one():\n    return 1\n\ndef two():\n    return 2\n",
        encoding="utf-8",
    )
    nodes, gaps = CONSUMER.demand_function_roster(
        workspace_root=tmp_path,
        file_rel="mod.py",
    )
    assert gaps == []
    names = sorted(
        n["memento"].get("function_name")
        or n["memento"].get("source_function_name")
        for n in nodes
    )
    assert names == ["one", "two"]
