"""#7073 regression teeth: roster-preserved mass + non-tautological clean.

Defect 1: a banked function roster must survive residual-phase failure
(functionsTotal stays N). The retired _measure_file banked full population on
mid-file ConstructionPanic; dropping to 0 is the shrunken-denominator lie.

Defect 2: functionsClean must not default to functionsTotal. A metric that
can only report 1.0 is refused, not banked as perfection.
"""

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
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec.loader.exec_module(mod)
    return mod


CONSUMER = _load(
    "recensus_enumerate_consumer",
    SCRIPTS / "recensus_enumerate_consumer.py",
)
COMPOSE = _load(
    "compose_control_effect_board",
    SCRIPTS / "compose_control_effect_board.py",
)


def test_residual_failure_preserves_roster_functions_total(monkeypatch) -> None:
    """D2 banks 3 functions; D3 raises; row still has functionsTotal=3."""
    nodes = [
        {"memento": {"function_name": "a"}},
        {"memento": {"function_name": "b"}},
        {"memento": {"function_name": "c"}},
    ]

    def fake_roster(**_k):
        return nodes, []

    def boom_residual(**_k):
        raise RuntimeError("sugar.enumerate error: residual phase crashed")

    monkeypatch.setattr(CONSUMER, "demand_function_roster", fake_roster)
    monkeypatch.setattr(CONSUMER, "demand_construction_residual", boom_residual)
    monkeypatch.setattr(CONSUMER, "count_ast_function_defs", lambda _p: 3)

    row = CONSUMER.measure_file_via_enumerate(
        workspace_root=Path("/tmp"),
        file_rel="pkg/mod.py",
    )
    assert row["functionsTotal"] == 3
    assert row["functionsEnumerated"] == 3
    assert row["rosterPreservedAfterResidualFailure"] is True
    assert row["category"] == "panic"
    # Clean must not claim 3/3 perfection after residual failure.
    assert row["functionsClean"] is None
    assert row["cleanRatioRefused"] is True


def test_open_roster_failure_still_zero_when_no_ast(monkeypatch) -> None:
    """True open failure (no roster, no AST) keeps empty denominator."""

    def boom_roster(**_k):
        raise RuntimeError("no such file")

    monkeypatch.setattr(CONSUMER, "demand_function_roster", boom_roster)
    monkeypatch.setattr(CONSUMER, "count_ast_function_defs", lambda _p: None)

    row = CONSUMER.measure_file_via_enumerate(
        workspace_root=Path("/tmp"),
        file_rel="missing.py",
    )
    assert row["functionsTotal"] == 0
    assert row["functionsEnumerated"] == 0
    assert row["category"] == "panic"


def test_roster_failure_banks_ast_population_not_silent_zero(monkeypatch) -> None:
    """Instrument crash before roster still names AST mass (instrument-blind)."""

    def boom_roster(**_k):
        raise RuntimeError("sugar.enumerate error: mid-roster crash")

    monkeypatch.setattr(CONSUMER, "demand_function_roster", boom_roster)
    monkeypatch.setattr(CONSUMER, "count_ast_function_defs", lambda _p: 12)

    row = CONSUMER.measure_file_via_enumerate(
        workspace_root=Path("/tmp"),
        file_rel="pkg/heavy.py",
    )
    assert row["functionsTotal"] == 12
    assert row["functionsEnumerated"] == 0
    assert row["functionsEnumerationComplete"] is False
    assert row["functionsClean"] is None
    assert row["cleanRatioRefused"] is True


def test_clean_defaults_are_refused_not_tautological() -> None:
    """Without sourceAudit.functionsClean, residual-empty audit may earn clean;
    without audit after residual failure, clean is refused."""
    nodes = [{"memento": {"function_name": "a"}}, {"memento": {"function_name": "b"}}]
    # Residual failed → refuse clean
    row = CONSUMER.terminal_from_enumerate(
        file_rel="x.py",
        function_nodes=nodes,
        function_gaps=[],
        audit=None,
        construction_gaps=[],
        residual_phase_failed=True,
        residual_error=RuntimeError("boom"),
        ast_fn=2,
    )
    assert row["functionsTotal"] == 2
    assert row["functionsClean"] is None
    assert row["cleanRatioRefused"] is True

    # Residual succeeded, empty panics → earned clean == total
    row2 = CONSUMER.terminal_from_enumerate(
        file_rel="x.py",
        function_nodes=nodes,
        function_gaps=[],
        audit={"semanticCore": {"status": "ok", "panics": []}},
        construction_gaps=[],
        residual_phase_failed=False,
        ast_fn=2,
    )
    assert row2["functionsClean"] == 2
    assert row2["cleanRatioRefused"] is False


def test_honest_source_audit_clean_is_used() -> None:
    nodes = [{"memento": {"function_name": n}} for n in "abcd"]
    row = CONSUMER.terminal_from_enumerate(
        file_rel="x.py",
        function_nodes=nodes,
        function_gaps=[],
        audit={
            "semanticCore": {"status": "ok", "panics": []},
            "auxiliaryRows": {"sourceAudit": {"functionsClean": 3}},
        },
        construction_gaps=[],
        residual_phase_failed=False,
        ast_fn=4,
    )
    assert row["functionsTotal"] == 4
    assert row["functionsClean"] == 3
    assert row["cleanRatioRefused"] is False


def test_compose_refuses_tautological_clean_on_board() -> None:
    """Board must not mint functionsConstructClean when any file refused clean."""
    rows = [
        (
            "good.py",
            {
                "category": "completed",
                "functionsTotal": 2,
                "functionsEnumerated": 2,
                "functionsClean": 2,
                "cleanRatioRefused": False,
                "families": {},
            },
        ),
        (
            "blind.py",
            {
                "category": "panic",
                "functionsTotal": 10,
                "functionsEnumerated": 0,
                "functionsClean": None,
                "cleanRatioRefused": True,
                "cleanRefuseReason": "roster demand failed",
                "defect": {"file": "blind.py", "type": "RuntimeError", "message": "x"},
                "families": {},
            },
        ),
    ]
    status, body = COMPOSE.compose_k1_from_rows(
        rows,
        enrolled_files=["good.py", "blind.py"],
        measured_commit="deadbeef",
        aggregate_hash="agg",
        manifest_shape_cid="cid",
    )
    assert status == "sealed"
    # Population includes instrument-blind mass (10), not dropped to 2.
    assert body["functionsTotal"] == 12
    # Clean ratio refused — not 2/2 perfection.
    assert body["cleanRatioRefused"] is True
    assert body["functionsConstructClean"] is None
    assert body["denominator"]["functions"].get("cleanRatioRefused") is True
    assert body["denominator"]["functions"].get("clean") is None



def test_consumer_source_forbids_clean_equal_total_assignment() -> None:
    """Static tooth: no bare functions_clean = functions_total default.

    ANY RATIO WHOSE NUMERATOR DEFAULTS TO ITS DENOMINATOR IS NOT A MEASUREMENT.
    Makes the class unrepresentable rather than fixing today's instance.
    """
    import ast

    path = SCRIPTS / "recensus_enumerate_consumer.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    crimes: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        if node.targets[0].id not in {"functions_clean", "functionsClean"}:
            continue
        if isinstance(node.value, ast.Name) and node.value.id in {
            "functions_total",
            "functionsTotal",
        }:
            crimes.append(
                f"L{node.lineno}: {node.targets[0].id} = {node.value.id} "
                "(identity default - not a measurement)"
            )
    assert not crimes, (
        "ANY RATIO WHOSE NUMERATOR DEFAULTS TO ITS DENOMINATOR IS NOT A "
        "MEASUREMENT.\n" + "\n".join(crimes)
    )


def test_outer_shell_escape_banks_recovered_roster_not_zero(
    tmp_path: Path, monkeypatch
) -> None:
    """Outer last-resort must not bank functionsTotal=0 over a recoverable roster.

    Latent hole: except Exception banked 0 whenever measure_file escaped. Make
    that shape unrepresentable - recover D2 (or AST) mass and name residual.
    """
    recensus = _load(
        "control_effect_recensus",
        SCRIPTS / "control_effect_recensus.py",
    )
    src = tmp_path / "multi.py"
    src.write_text(
        "def a():\n    return 1\n\ndef b():\n    return 2\n\ndef c():\n    return 3\n",
        encoding="utf-8",
    )

    # Escape shape: a BaseException that is not process control.
    class NewBaseExceptionGap(BaseException):
        pass

    nodes = [
        {"memento": {"function_name": "a"}},
        {"memento": {"function_name": "b"}},
        {"memento": {"function_name": "c"}},
    ]

    def fake_roster(**_k):
        return nodes, []

    monkeypatch.setattr(CONSUMER, "demand_function_roster", fake_roster)
    # Also patch the name as imported by the helper after its import.
    import recensus_enumerate_consumer as consumer_mod

    monkeypatch.setattr(consumer_mod, "demand_function_roster", fake_roster)

    row = recensus.terminal_after_measure_escape(
        path=src,
        relative="multi.py",
        workspace_root=tmp_path,
        error=NewBaseExceptionGap("escaped past consumer"),
        category="panic",
    )
    assert row["functionsTotal"] == 3, (
        f"outer shell must bank recovered roster, got {row.get('functionsTotal')}"
    )
    assert row.get("rosterPreservedAfterResidualFailure") is True
    assert row.get("cleanRatioRefused") is True
    assert row.get("functionsClean") is None
    defect = row.get("defect") or {}
    assert defect.get("type") == "NewBaseExceptionGap" or "NewBaseExceptionGap" in str(
        row.get("families") or {}
    )


def test_outer_shell_escape_banks_ast_when_roster_demand_also_fails(
    tmp_path: Path, monkeypatch
) -> None:
    """If D2 recovery also fails, AST mass still forbids silent zero."""
    recensus = _load(
        "control_effect_recensus",
        SCRIPTS / "control_effect_recensus.py",
    )
    src = tmp_path / "multi.py"
    src.write_text(
        "def a():\n    return 1\n\ndef b():\n    return 2\n",
        encoding="utf-8",
    )

    def boom_roster(**_k):
        raise RuntimeError("roster recovery failed too")

    import recensus_enumerate_consumer as consumer_mod

    monkeypatch.setattr(consumer_mod, "demand_function_roster", boom_roster)

    row = recensus.terminal_after_measure_escape(
        path=src,
        relative="multi.py",
        workspace_root=tmp_path,
        error=RuntimeError("outer escape"),
        category="panic",
    )
    assert row["functionsTotal"] == 2  # AST FunctionDef count
    assert row["functionsEnumerated"] == 0
    assert row.get("cleanRatioRefused") is True
