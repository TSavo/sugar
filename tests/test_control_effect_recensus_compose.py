"""Teeth for recensus LPT compose seal (banked law R1–R6 + dual-belt attendance)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = (
    ROOT
    / "implementations/python/sugar-lift-py-tests/scripts"
)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


COMPOSE = _load(
    "compose_control_effect_board",
    SCRIPTS / "compose_control_effect_board.py",
)
ATTEND = _load(
    "heavy_measurement_attendance",
    ROOT / "tools/heavy_measurement_attendance.py",
)


def _row(
    file: str,
    *,
    category: str = "completed",
    fn: int = 1,
    auth: int | None = None,
    panic: bool = False,
):
    """fn = enumerated; auth = population mass (defaults to fn).

    functionsTotal is always the population (roster/AST mass), never zeroed
    by defect category — that was the #7073 regression.
    """
    authenticated = fn if auth is None else auth
    enumerated = 0 if (panic or category != "completed") else fn
    if panic:
        return (
            file,
            {
                "category": "construction-panic",
                "functionsTotal": authenticated,
                "functionsClean": None,
                "cleanRatioRefused": True,
                "functionsEnumerated": enumerated,
                "functionsAuthenticated": authenticated,
                "astSites": {"site:function-def": authenticated},
                "families": {"ConstructionPanic": 1},
                "panic": {"file": file, "type": "ConstructionPanic", "message": "x"},
                "R_instrument_blind": 0,
            },
        )
    blind = category in {"backend-defect", "instrument-defect-unresolvable-dispatch"}
    return (
        file,
        {
            "category": category,
            "functionsTotal": authenticated,
            "functionsClean": (fn if category == "completed" and not blind else None),
            "cleanRatioRefused": bool(blind or category != "completed"),
            "functionsEnumerated": enumerated,
            "functionsAuthenticated": authenticated,
            "astSites": {"site:function-def": authenticated},
            "families": {},
            "R_instrument_blind": 1 if blind else 0,
            **(
                {
                    "defect": {
                        "file": file,
                        "type": "BackendDefect",
                        "message": "instrument failed",
                    }
                }
                if blind
                else {}
            ),
        },
    )


def _plan(files: list[str], *, k: int = 1, bins: list[list[str]] | None = None):
    if bins is None:
        if k == 1:
            bins = [list(files)]
        else:
            raise ValueError("bins required for k>1")
    return COMPOSE.build_plan(
        enrolled_files=files,
        shard_count=k,
        measured_commit="deadbeef",
        aggregate_hash="agg",
        manifest_shape_cid="cid",
        bins=bins,
        split_mode="test",
        prior_hits=0,
        prior_misses=0,
        estimated_loads=[1.0] * k,
    )


def test_compose_scoreboard_authority_true_only_here() -> None:
    assert COMPOSE.SCOREBOARD_AUTHORITY is True
    worker = (SCRIPTS / "control_effect_recensus.py").read_text(encoding="utf-8")
    assert "SCOREBOARD_AUTHORITY = False" in worker
    assert "SCOREBOARD_AUTHORITY = True" not in worker.split("compose_control_effect_board")[0]


def test_k1_compose_seals_with_dual_denom_and_body_cid() -> None:
    files = ["pandas/a.py", "pandas/b.py"]
    # a: enumerated 3 of 3 authenticated; b: panic, auth 2 still in population.
    rows = [
        _row("pandas/a.py", fn=3, auth=3),
        _row("pandas/b.py", fn=0, auth=2, panic=True),
    ]
    status, body = COMPOSE.compose_k1_from_rows(
        rows,
        enrolled_files=files,
        measured_commit="deadbeef",
        aggregate_hash="agg",
        manifest_shape_cid="cid",
    )
    assert status == "sealed"
    assert body["measurementClass"] == "control-effect-recensus"
    assert body["status"] == "sealed"
    assert body["measured"] is True
    assert body["bodyCid"]
    assert body["R_construction_panics"] == 1
    assert body["denominator"]["files"]["enrolled"] == 2
    # Population mass (roster-preserved), not enumerate-only.
    assert body["denominator"]["functions"]["total"] == 5
    assert body["denominator"]["functions"]["enumerated"] == 3
    assert body["denominator"]["functions"]["unaccounted"] == 2
    assert body["denominator"]["functions"]["unit"] == "construction-function-locus"
    # Dual units: file enrolled count is not the function total slot.
    assert "files" in body["denominator"] and "functions" in body["denominator"]
    # Clean refused when any file refuses (panic row).
    assert body["denominator"]["functions"].get("cleanRatioRefused") is True


def test_board_refuses_enumerated_as_authenticated_population() -> None:
    """C1 law: instrument-blind rows must not shrink the function denominator.

    Advisor (freeze): instrument-defect rows contribute 0 to num AND denom so
    clean% is structurally blind. Same shape one level up on the seal board:
    18230 enumerated-only must never mint denominator.functions.total.
    """
    files = ["pandas/good.py", "pandas/blind.py"]
    rows = [
        _row("pandas/good.py", fn=2, auth=2),
        _row("pandas/blind.py", category="backend-defect", fn=0, auth=10),
    ]
    status, body = COMPOSE.compose_k1_from_rows(
        rows,
        enrolled_files=files,
        measured_commit="deadbeef",
        aggregate_hash="agg",
        manifest_shape_cid="cid",
    )
    assert status == "sealed"
    # Population is sum of row functionsTotal (2+10), never enumerated-only (2).
    assert body["denominator"]["functions"]["total"] == 12
    assert body["functionsTotal"] == 12
    assert body["functionsEnumerated"] == 2
    assert body["functionsUnaccounted"] == 10
    assert body["R_instrument_blind"] == 1
    assert body["R_instrument_blind_functions"] == 10
    # Must not present 2/2 clean as if the corpus were fully measured.
    assert body["denominator"]["functions"]["enumerated"] == 2
    assert body.get("functionsConstructClean") is None
    assert body.get("cleanRatioRefused") is True
    denom_fn = body["denominator"]["functions"]
    assert denom_fn["total"] != denom_fn["enumerated"]


def test_missing_shard_emits_unmeasured_without_class() -> None:
    files = ["a.py", "b.py", "c.py", "d.py"]
    bins = [["a.py", "b.py"], ["c.py", "d.py"]]
    plan = _plan(files, k=2, bins=bins)
    partial0 = COMPOSE.mint_partial(
        plan=plan,
        shard_index=0,
        terminal_rows=[_row("a.py"), _row("b.py")],
    )
    # Only s00 present — s01 missing.
    status, body = COMPOSE.compose_from_partials(plan, [partial0])
    assert status == "unmeasured"
    assert body["kind"] == COMPOSE.KIND_UNMEASURED
    assert "measurementClass" not in body
    assert "R_construction_panics" not in body
    assert "bodyCid" not in body
    assert "s01" in body["missingShards"]
    assert body["measured"] is False
    assert body["status"] == "unmeasured"


def test_unmeasured_envelope_does_not_attend_heavy_roster(tmp_path: Path) -> None:
    env = COMPOSE.unmeasured_envelope(
        plan={"planCid": "p", "measuredCommit": "deadbeef"},
        missing_shards=["s03"],
        unmeasured_reasons={"s03": "receipt absent"},
        measured_commit="deadbeef",
    )
    # Even if a buggy caller re-adds the class, sealed triple is required.
    spoof = dict(env)
    spoof["measurementClass"] = "control-effect-recensus"
    path = tmp_path / "pandas-control-effect" / "unmeasured.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(spoof), encoding="utf-8")
    attended, _ = ATTEND.receipts_attendance(tmp_path)
    assert "control-effect-recensus" not in attended
    assert ATTEND._class_from_payload(path, spoof) is None


def test_sealed_board_attends_heavy_roster(tmp_path: Path) -> None:
    files = ["a.py"]
    status, body = COMPOSE.compose_k1_from_rows(
        [_row("a.py", fn=1)],
        enrolled_files=files,
        measured_commit="deadbeef",
        aggregate_hash="agg",
        manifest_shape_cid="cid",
    )
    assert status == "sealed"
    path = tmp_path / "pandas-control-effect" / "recensus.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(body), encoding="utf-8")
    attended, _ = ATTEND.receipts_attendance(tmp_path)
    assert "control-effect-recensus" in attended


def test_partial_never_attends_as_board(tmp_path: Path) -> None:
    plan = _plan(["a.py", "b.py"], k=1)
    partial = COMPOSE.mint_partial(
        plan=plan,
        shard_index=0,
        terminal_rows=[_row("a.py"), _row("b.py")],
    )
    assert partial["measurementClass"] == "control-effect-recensus-shard"
    assert "R_construction_panics" not in partial
    path = tmp_path / "pandas-control-effect" / "partial-s00.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(partial), encoding="utf-8")
    attended, _ = ATTEND.receipts_attendance(tmp_path)
    assert "control-effect-recensus" not in attended


def test_two_partials_compose_stable_compose_cid() -> None:
    files = ["a.py", "b.py"]
    bins = [["a.py"], ["b.py"]]
    plan = _plan(files, k=2, bins=bins)
    p0 = COMPOSE.mint_partial(plan=plan, shard_index=0, terminal_rows=[_row("a.py", fn=2)])
    p1 = COMPOSE.mint_partial(plan=plan, shard_index=1, terminal_rows=[_row("b.py", fn=3)])
    s1, b1 = COMPOSE.compose_from_partials(plan, [p0, p1])
    s2, b2 = COMPOSE.compose_from_partials(plan, [p1, p0])  # order independent
    assert s1 == s2 == "sealed"
    assert b1["composeCid"] == b2["composeCid"]
    assert b1["R_construction_panics"] == 0
    # auth defaults to fn in _row → 2+3 population
    assert b1["denominator"]["functions"]["total"] == 5
    assert b1["functionsEnumerated"] == 5
    assert b1["perShardCids"]["s00"] == p0["partialCid"]
    assert b1["perShardCids"]["s01"] == p1["partialCid"]


def test_partial_with_top_level_panics_refused() -> None:
    plan = _plan(["a.py"], k=1)
    partial = COMPOSE.mint_partial(
        plan=plan, shard_index=0, terminal_rows=[_row("a.py")]
    )
    # Corrupt: inject forbidden C2 field.
    bad = dict(partial)
    bad["R_construction_panics"] = 1
    bad["partialCid"] = COMPOSE.canonical_cid(
        {k: v for k, v in bad.items() if k != "partialCid"}
    )
    status, body = COMPOSE.compose_from_partials(plan, [bad])
    assert status == "unmeasured"
    assert "s00" in body["missingShards"]
