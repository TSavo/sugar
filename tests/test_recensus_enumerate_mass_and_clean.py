"""#7073 regression teeth: roster-preserved mass + non-tautological clean.

Defect 1: a banked function roster must survive residual-phase failure
(functionsTotal stays N). The retired _measure_file banked full population on
mid-file ConstructionPanic; dropping to 0 is the shrunken-denominator lie.

Defect 2: functionsClean must not default to functionsTotal. A metric that
can only report 1.0 is refused, not banked as perfection.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

from repo_root_test_support import resolve_repo_root

ROOT = resolve_repo_root()
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


def _demand_table_kwargs() -> dict[str, object]:
    identity = COMPOSE.DemandTableIdentityV1(
        content_key="",
        corpus_manifest_cid="blake3-512:test-corpus",
        schema_version="python-demand-table/v1",
        producer_source_cid="blake3-512:test-producer",
        resolution_config_cid="blake3-512:test-config",
        parser_identity="cpython-3.12",
        file_count=2,
    )
    identity = COMPOSE.DemandTableIdentityV1(
        content_key=COMPOSE.cid_of_json(dict(identity.preimage())),
        corpus_manifest_cid=identity.corpus_manifest_cid,
        schema_version=identity.schema_version,
        producer_source_cid=identity.producer_source_cid,
        resolution_config_cid=identity.resolution_config_cid,
        parser_identity=identity.parser_identity,
        file_count=identity.file_count,
    )
    return {
        "demand_table_cid": "blake3-512:test-table",
        "demand_table_identity": identity.as_dict(),
    }


def test_residual_failure_preserves_roster_functions_total(
    tmp_path: Path, monkeypatch
) -> None:
    """D2 banks 3 functions; an ordinary D3 failure is unmeasured at mass 3."""
    src = tmp_path / "pkg/mod.py"
    src.parent.mkdir()
    src.write_text("def a(): pass\ndef b(): pass\ndef c(): pass\n", encoding="utf-8")
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
    monkeypatch.setattr(
        CONSUMER, "demand_context_manager_resolution_events", lambda **_k: ([], [])
    )
    monkeypatch.setattr(CONSUMER, "demand_construction_residual", boom_residual)
    monkeypatch.setattr(CONSUMER, "count_ast_function_defs", lambda _p: 3)

    row = CONSUMER.measure_file_via_enumerate(
        workspace_root=tmp_path,
        file_rel="pkg/mod.py",
    )
    assert row["functionsTotal"] == 3
    assert row["functionsEnumerated"] == 3
    assert row["rosterPreservedAfterResidualFailure"] is True
    assert "category" not in row
    assert row["instrumentFailure"]["phase"] == "residual"
    # Clean must not claim 3/3 perfection after residual failure.
    assert row["functionsClean"] is None
    assert row["cleanRatioRefused"] is True


def test_consumer_carries_pre_demand_and_real_audit_open_observations(
    tmp_path: Path, monkeypatch
) -> None:
    """D3 observes the real CID-and-seat resident without another prepare."""
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_source_tree.process_resident_file import (
        clear_process_resident_files,
        get_resident,
        prepare_count_for,
    )
    from sugar_source_tree.tree import SourceFile

    src = tmp_path / "pkg/mod.py"
    src.parent.mkdir()
    src.write_text("def a(): pass\n", encoding="utf-8")
    nodes = [{"memento": {"function_name": "a"}}]

    measured_path = src.resolve()
    _source, source_seat, source_cid = path_source(str(measured_path))
    clear_process_resident_files()
    SourceFile.from_path(measured_path)
    assert get_resident(source_cid, source_seat) is not None
    assert prepare_count_for(source_cid, source_seat) == 1

    monkeypatch.setattr(CONSUMER, "demand_function_roster", lambda **_k: (nodes, []))
    monkeypatch.setattr(
        CONSUMER, "demand_context_manager_resolution_events", lambda **_k: ([], [])
    )
    monkeypatch.setattr(
        CONSUMER,
        "demand_construction_residual",
        lambda **_k: ({"semanticCore": {"status": "ok", "panics": []}}, []),
    )
    monkeypatch.setattr(CONSUMER, "count_ast_function_defs", lambda _p: 1)
    monkeypatch.setattr(
        CONSUMER,
        "_take_d3_audit_open_observation",
        lambda source_cid: {
            "sourceCid": source_cid,
            "presentAtAuditOpen": True,
            "auditOpenReusedResident": True,
            "rootReporterSeatedAtAuditOpen": False,
            "collectorRegisteredAtAuditExit": False,
        },
    )

    try:
        row = CONSUMER.measure_file_via_enumerate(
            workspace_root=tmp_path,
            file_rel="pkg/mod.py",
            contract_refs=[],
        )

        assert row["inputKey"]["sourceCid"] == source_cid
        assert row["d3Residency"] == {
            "sourceCid": source_cid,
            "reached": True,
            "presentBeforeDemand": True,
            "presentAtAuditOpen": True,
            "auditOpenReusedResident": True,
            "rootReporterSeatedAtAuditOpen": False,
            "collectorRegisteredAtAuditExit": False,
            "presenceConfirmed": True,
        }
        assert get_resident(source_cid, source_seat) is not None
        assert prepare_count_for(source_cid, source_seat) == 1
    finally:
        clear_process_resident_files()


def test_d3_residency_aggregate_keeps_counts_and_file_coordinates() -> None:
    """Both answers and missing attendance survive partial/refusal transport."""
    rows = [
        (
            "hit.py",
            {
                "category": "completed",
                "functionsTotal": 1,
                "functionsEnumerated": 1,
                "functionsClean": 1,
                "cleanRatioRefused": False,
                "d3Residency": {
                    "sourceCid": "cid-hit",
                    "reached": True,
                    "presentBeforeDemand": True,
                    "presentAtAuditOpen": True,
                    "auditOpenReusedResident": True,
                    "rootReporterSeatedAtAuditOpen": False,
                    "collectorRegisteredAtAuditExit": False,
                    "presenceConfirmed": True,
                },
            },
        ),
        (
            "miss.py",
            {
                "category": "completed",
                "functionsTotal": 1,
                "functionsEnumerated": 1,
                "functionsClean": 1,
                "cleanRatioRefused": False,
                "d3Residency": {
                    "sourceCid": "cid-miss",
                    "reached": True,
                    "presentBeforeDemand": False,
                    "presentAtAuditOpen": False,
                    "auditOpenReusedResident": False,
                    "rootReporterSeatedAtAuditOpen": True,
                    "collectorRegisteredAtAuditExit": True,
                    "presenceConfirmed": True,
                },
            },
        ),
        (
            "early.py",
            {
                "instrumentFailure": {"phase": "roster"},
                "functionsTotal": 0,
                "functionsEnumerated": 0,
                "functionsClean": None,
                "cleanRatioRefused": True,
            },
        ),
    ]

    agg = COMPOSE.aggregate_terminal_rows(
        rows,
        enrolled_files=["hit.py", "miss.py", "early.py"],
    )
    exposure = agg["d3_residency_exposure"]
    assert exposure == {
        "filesEnrolled": 3,
        "d3Reached": 2,
        "d3NotReached": 1,
        "presentBeforeDemand": 1,
        "absentBeforeDemand": 1,
        "auditOpenHit": 1,
        "auditOpenMiss": 1,
        "auditOpenObserved": 2,
        "auditOpenUnconfirmed": 0,
        "presenceConfirmed": 2,
        "presenceMismatch": 0,
        "reporterSeated": 1,
        "reporterUnseated": 1,
        "collectorRegistered": 1,
        "collectorEmpty": 1,
        "hitFiles": ["hit.py"],
        "missFiles": ["miss.py"],
        "notReachedFiles": ["early.py"],
        "auditOpenUnconfirmedFiles": [],
        "presenceMismatchFiles": [],
        "reporterUnseatedFiles": ["hit.py"],
        "collectorEmptyFiles": ["hit.py"],
    }
    envelope = COMPOSE.unmeasured_envelope(
        plan=None,
        missing_shards=["compose"],
        unmeasured_reasons={"compose": "frontier refused"},
        d3_residency_exposure=exposure,
    )
    assert envelope["d3ResidencyExposure"] == exposure


def test_open_roster_failure_still_zero_when_no_ast(
    tmp_path: Path, monkeypatch
) -> None:
    """True open failure (no roster, no AST) keeps empty denominator."""

    def boom_roster(**_k):
        raise RuntimeError("no such file")

    (tmp_path / "missing.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(CONSUMER, "demand_function_roster", boom_roster)
    monkeypatch.setattr(CONSUMER, "count_ast_function_defs", lambda _p: None)

    row = CONSUMER.measure_file_via_enumerate(
        workspace_root=tmp_path,
        file_rel="missing.py",
    )
    assert row["functionsTotal"] == 0
    assert row["functionsEnumerated"] == 0
    assert "category" not in row
    assert row["instrumentFailure"]["phase"] == "roster"


def test_roster_failure_banks_ast_population_not_silent_zero(
    tmp_path: Path, monkeypatch
) -> None:
    """Instrument crash before roster still names AST mass (instrument-blind)."""

    def boom_roster(**_k):
        raise RuntimeError("sugar.enumerate error: mid-roster crash")

    src = tmp_path / "pkg/heavy.py"
    src.parent.mkdir()
    src.write_text("def one(): pass\n", encoding="utf-8")
    monkeypatch.setattr(CONSUMER, "demand_function_roster", boom_roster)
    monkeypatch.setattr(CONSUMER, "count_ast_function_defs", lambda _p: 12)

    row = CONSUMER.measure_file_via_enumerate(
        workspace_root=tmp_path,
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


def test_audit_panic_is_not_mislabeled_as_residual_phase_failure() -> None:
    """A returned D3 panic is not an escaped D3 call."""
    nodes = [{"memento": {"function_name": "a"}}]
    row = CONSUMER.terminal_from_enumerate(
        file_rel="x.py",
        function_nodes=nodes,
        function_gaps=[],
        audit={
            "semanticCore": {
                "status": "failed",
                "panics": [
                    {
                        "reason": "unconstructed child",
                        "gap": {
                            "owner": "WithSugar",
                            "coordinate": "x.py:1:0",
                            "observed": "OpaqueValue",
                            "requested": "ContextManagerResolution",
                            "fix": "construct the manager resolution",
                            "entrance": "sugar.enumerate:facts",
                            "observedEventType": "sugar_source_tree.panic.SugarNotWritten",
                            "construction_trace": [
                                {
                                    "kind": "source-construct",
                                    "constructOwner": "WithSugar",
                                    "coordinate": "x.py:1:0",
                                }
                            ],
                        },
                    }
                ],
            }
        },
        construction_gaps=[],
        residual_phase_failed=False,
        ast_fn=1,
    )
    assert row["category"] == "panic"
    assert row["rosterPreservedAfterResidualFailure"] is False


def test_reasonless_unauthenticated_audit_panic_is_instrument_failure() -> None:
    """A raw row without construction testimony cannot enter frontier width."""
    nodes = [{"memento": {"function_name": "a"}}]
    raw_panic = {"gap": {"observed": "OpaqueValue"}, "locus": "x.py:1:0"}
    row = CONSUMER.terminal_from_enumerate(
        file_rel="x.py",
        function_nodes=nodes,
        function_gaps=[],
        audit={"semanticCore": {"status": "failed", "panics": [raw_panic]}},
        construction_gaps=[],
        residual_phase_failed=False,
        ast_fn=1,
    )
    assert "category" not in row
    assert row["instrumentFailure"]["phase"] == "audit-panic-decode"
    assert str(raw_panic) in row["instrumentFailure"]["message"]


def test_compose_refuses_unattested_clean_board() -> None:
    """Legacy rows cannot mint a clean ratio or authenticated frontier width."""
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
        **_demand_table_kwargs(),
    )
    assert status == "unmeasured"
    assert body["status"] == "unmeasured"
    assert "frontierWidth" not in body
    assert "productPanicCount" not in body
    assert body["instrumentFailures"]



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


def test_main_has_one_reachable_panic_enrollment_arm() -> None:
    """Taxonomy deletion must not create duplicate, unreachable elif arms."""
    recensus_path = SCRIPTS / "control_effect_recensus.py"
    tree = ast.parse(recensus_path.read_text(encoding="utf-8"))
    main = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    )

    def is_panic_test(node) -> bool:
        return (
            isinstance(node, ast.Compare)
            and isinstance(node.left, ast.Name)
            and node.left.id == "category"
            and len(node.ops) == 1
            and isinstance(node.ops[0], ast.Eq)
            and len(node.comparators) == 1
            and isinstance(node.comparators[0], ast.Constant)
            and node.comparators[0].value == "panic"
        )

    duplicate_chains: list[list[int]] = []
    for node in ast.walk(main):
        if not isinstance(node, ast.If):
            continue
        lines: list[int] = []
        cursor = node
        while True:
            if is_panic_test(cursor.test):
                lines.append(cursor.lineno)
            if len(cursor.orelse) != 1 or not isinstance(cursor.orelse[0], ast.If):
                break
            cursor = cursor.orelse[0]
        if len(lines) > 1:
            duplicate_chains.append(lines)
    assert duplicate_chains == [], (
        "duplicate category == 'panic' elif arms make later enrollment "
        f"unreachable: {duplicate_chains}"
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
    assert "category" not in row
    assert row["instrumentFailure"]["observedEventType"].endswith(
        ".NewBaseExceptionGap"
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
