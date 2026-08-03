#!/usr/bin/env python3
"""Recensus PATH smoke — micro-population integrity, NOT product R.

WALLS (advisor, binding):
  1. PATH verdict only: PATH_OK | PATH_RED | PATH_UNMEASURED.
     Never emit R_construction_panics, desugar board, or SCOREBOARD_AUTHORITY
     product fields. Smoke-scoped counts (if any) are nested under smokeCounts
     and refuse CommitMeasurement panics ingestion by construction.
  2. SCOREBOARD_AUTHORITY stays False here. Sole bankable panics producer is
     control_effect_recensus on the authenticated pandas corpus.
  3. Teeth are the instrument: constructed>0, the exact named construction-
     panic identities are conserved, unconstructed does not vanish, exact
     two-item accounting closes, sealed body on PATH_OK.
     Crash → PATH_UNMEASURED.
  4. Coverage honesty: four planted files retire serial path-rot discovery,
     not Class B corpus scale (thousands of with-items) or the full walk.
  5. measurementClass = recensus-path-smoke — never control-effect-recensus.

Planted fixtures (mr_blue conservation teeth + panic host):
  fixtures/recensus_path_smoke/
"""

from __future__ import annotations

# Explicit: never the sole authoritative scoreboard.
SCOREBOARD_AUTHORITY = False

import importlib.util
import json
import os
import re
import sys
import time
import traceback
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent
_PKG = _SCRIPTS.parent
_FIXTURES = _PKG / "fixtures" / "recensus_path_smoke"
_REPO = _PKG.parents[2]

MEASUREMENT_CLASS = "recensus-path-smoke"
KIND = "recensus-path-smoke-verdict"

# Forbidden product-shaped keys — presence alone is PATH_RED (unrepresentable
# as a green path body).
_FORBIDDEN_PRODUCT_KEYS = frozenset(
    {
        "R_construction_panics",
        "R_construction",
        "R_desugar",
        "controlEffectStableZero",
        "floorSummary",
        "SCOREBOARD_AUTHORITY",
    }
)

_EXPECTED_CONSTRUCTION_PANIC_IDENTITIES = (
    {
        "file": "planted_panic_host.py",
        "owner": "recensus-path-smoke-planted-panic",
        "coordinate": "planted_panic_host.py:1:0",
        "observedEventType": "sugar_lift_py_tests.gap.panic.ConstructionPanic",
        "requested": "constructed value",
        "entrance": "sugar.enumerate:roster",
    },
)

_RETIRED_MODULE_SUGAR_PANIC_IDENTITY = {
    "file": "planted_clean.py",
    "owner": "Module.sugar",
    "coordinate": "planted_clean.py:1:0-6:0[Module]",
    "observedEventType": "sugar_source_tree.panic.SugarNotWritten",
    "requested": "a constructed sugar object",
    "entrance": "sugar.enumerate:facts:auditFrontier",
}

_EXPECTED_MODULE_SUGAR_CONSTRUCTED_IDENTITY = {
    "file": "planted_clean.py",
    "sourceCid": (
        "blake3-512:6b64cbd185cd2da38bea697245ef05b21763197594c483bcbb1b4ae9fe40ed55"
        "a88d0b48a3d41e6786185707dac26d140110336390a8b53516e04f717f6e2b8b"
    ),
    "rowId": (
        "blake3-512:11e6c281e5d8750dbb061a27bd5589f9dcea7a28d967eea68709cccbfd8cacb3"
        "bbdba0bc3cce0fcb9204a3c8259d3e27aee4ac5d21cd55691368dedb882d1a95"
    ),
    "stageId": "recensus-enumerate-file-terminal/v1",
    "observedEventType": "builtins.dict",
    "category": "completed",
    "terminalKind": "constructed",
    "final_terminal": "constructed",
}


def _construction_panic_identity(panic: dict[str, Any]) -> dict[str, str | None]:
    """Project the stable fields that distinguish real terminals and duplicates."""
    return {
        key: panic.get(key) if isinstance(panic.get(key), str) else None
        for key in (
            "file",
            "owner",
            "coordinate",
            "observedEventType",
            "requested",
            "entrance",
        )
    }


def _sorted_panic_identities(
    panics: list[dict[str, Any]],
) -> list[dict[str, str | None]]:
    return sorted(
        (_construction_panic_identity(panic) for panic in panics),
        key=lambda row: tuple(str(row.get(key) or "") for key in sorted(row)),
    )


def _module_sugar_constructed_identity(
    row: dict[str, Any] | None,
) -> dict[str, str | None] | None:
    """Project the exact constructed row replacing the retired Module panic."""
    if not isinstance(row, dict):
        return None
    input_key = row.get("inputKey")
    if not isinstance(input_key, dict):
        return None
    return {
        "file": input_key.get("file")
        if isinstance(input_key.get("file"), str)
        else None,
        "sourceCid": input_key.get("sourceCid")
        if isinstance(input_key.get("sourceCid"), str)
        else None,
        "rowId": row.get("rowId") if isinstance(row.get("rowId"), str) else None,
        "stageId": row.get("stageId")
        if isinstance(row.get("stageId"), str)
        else None,
        "observedEventType": row.get("observedEventType")
        if isinstance(row.get("observedEventType"), str)
        else None,
        "category": row.get("category")
        if isinstance(row.get("category"), str)
        else None,
        "terminalKind": row.get("terminalKind")
        if isinstance(row.get("terminalKind"), str)
        else None,
        "final_terminal": row.get("final_terminal")
        if isinstance(row.get("final_terminal"), str)
        else None,
    }


def _narrate(msg: str) -> None:
    print(msg, flush=True)


def _worktree_sha() -> str:
    value = os.environ.get("WITH_WIRE_WORKTREE_SHA", "")
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise RuntimeError(
            "WITH_WIRE_WORKTREE_SHA must carry the exact committed reproducer SHA"
        )
    return value


def _load_recensus():
    path = _SCRIPTS / "control_effect_recensus.py"
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    spec = importlib.util.spec_from_file_location("control_effect_recensus", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Workers stay non-authoritative. The separate compose door owns the seal.
    assert getattr(module, "SCOREBOARD_AUTHORITY", None) is False, (
        "control_effect_recensus must remain SCOREBOARD_AUTHORITY=False"
    )
    from compose_control_effect_board import (
        SCOREBOARD_AUTHORITY as compose_authority,
    )

    assert compose_authority is True, (
        "compose_control_effect_board must remain the sole scoreboard authority"
    )
    return module


def _seal_path(
    *,
    out_dir: Path,
    path_verdict: str,
    path_phase: str,
    tooth: str | None,
    teeth: dict[str, Any],
    smoke_counts: dict[str, Any],
    phases: list[str],
    error: str | None = None,
) -> Path:
    body: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": KIND,
        "measurementClass": MEASUREMENT_CLASS,
        # PATH verdict only — never product panics R.
        "pathVerdict": path_verdict,
        "pathPhase": path_phase,
        "failedTooth": tooth,
        "teeth": teeth,
        "smokeCounts": smoke_counts,
        "phasesCompleted": phases,
        "scoreboardAuthority": False,
        "coverageHonesty": (
            "Measures recensus production PATH integrity over an enrolled "
            "micro-population. Does NOT measure C2 R_construction_panics on "
            "pandas. Does NOT retire the full corpus walk or Class B with-item "
            "scale. Smoke-green is not corpus-clean."
        ),
    }
    if error is not None:
        body["error"] = error
        body["status"] = "unmeasured"
        body["unmeasuredReason"] = error
    else:
        body["status"] = "completed" if path_verdict == "PATH_OK" else "path-red"
    # Unrepresentable: product keys must not appear on a path body.
    for banned in _FORBIDDEN_PRODUCT_KEYS:
        if banned in body:
            raise RuntimeError(f"smoke path body must not carry product key {banned}")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "path_verdict.json"
    path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    return path


def _measure_constructed(module, path: Path, workspace: Path) -> dict[str, Any]:
    """mr_blue plant: SourceDerived at live use-site → constructed tally.

    Isolate the plant in a single-file workspace so provisional demands see
    exactly one use-site (same isolation as test_with_census_conservation).
    """
    import shutil
    import tempfile

    from sugar_lift_py_tests.context_manager_contract import (
        EnterResultContractV1,
        ExitContractV1,
        ImportSignatureV2,
        ProtocolResourceSemanticsV1,
        ReturnTruthinessDispositionV1,
    )
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceDerivedContextManagerRefV1,
    )
    from sugar_lift_py_tests.ir import PrimitiveSort
    from sugar_lift_py_tests.lift_rpc import (
        open_source_file_for_construction,
        provisional_contract_refs_from_demands,
        tree_construction_context_for_workspace,
    )
    from sugar_lift_py_tests.outcome import Complete

    iso = Path(tempfile.mkdtemp(prefix="recensus-path-smoke-constructed-"))
    try:
        plant = iso / path.name
        shutil.copy2(path, plant)
        refs = provisional_contract_refs_from_demands(iso)
        ctx = tree_construction_context_for_workspace(iso, contract_refs=refs)
        source_file = open_source_file_for_construction(
            plant, root=iso, construction_context=ctx, populate_derived=False
        )
        if len(refs.by_use_site) != 1:
            raise RuntimeError(
                f"planted_constructed_with must have exactly one use-site; got "
                f"{len(refs.by_use_site)}"
            )
        use_site = next(iter(refs.by_use_site))

        class _Protocol:
            def enter_resource_outcome(self, _ctx=None):
                return Complete(SimpleNamespace(enter_value=None))

            def exit_outcome_for(self, _entered, _ctx=None):
                return Complete(False)

        ctx.source_derived_contract_refs[use_site] = SourceDerivedContextManagerRefV1(
            use_site=use_site,
            summary_cid="blake3-512:" + ("a" * 128),
            semantics=ProtocolResourceSemanticsV1(
                enter=EnterResultContractV1(sort=PrimitiveSort("Value")),
                exit=ExitContractV1(disposition=ReturnTruthinessDispositionV1()),
            ),
            import_signature=ImportSignatureV2(()),
            protocol=_Protocol(),
        )
        resolution_rows = module._tally_cm_resolutions(
            ctx, source_cid=source_file.unit.source_cid
        )
        sites = module._ast_site_prevalence(plant)
        partition = module._with_census_partition(resolution_rows, sites)
        return {
            "category": "completed",
            "cmResolutions": {
                "constructed": partition["constructed"],
                "unconstructed": partition["unconstructed"],
            },
            "withResolutionRows": resolution_rows,
            "families": {},
            "sites": dict(sites),
            "relative": f"recensus_path_smoke/{path.name}",
        }
    finally:
        shutil.rmtree(iso, ignore_errors=True)


def _measure_opaque(module, path: Path, workspace: Path) -> dict[str, Any]:
    """mr_blue plant: opaque With stays present as unconstructed."""
    import shutil
    import tempfile

    from sugar_lift_py_tests.lift_rpc import (
        open_source_file_for_construction,
        provisional_contract_refs_from_demands,
        tree_construction_context_for_workspace,
    )

    iso = Path(tempfile.mkdtemp(prefix="recensus-path-smoke-opaque-"))
    try:
        plant = iso / path.name
        shutil.copy2(path, plant)
        refs = provisional_contract_refs_from_demands(iso)
        ctx = tree_construction_context_for_workspace(iso, contract_refs=refs)
        source_file = open_source_file_for_construction(
            plant, root=iso, construction_context=ctx, populate_derived=True
        )
        resolution_rows = module._tally_cm_resolutions(
            ctx, source_cid=source_file.unit.source_cid
        )
        sites = module._ast_site_prevalence(plant)
        partition = module._with_census_partition(resolution_rows, sites)
        return {
            "category": "completed",
            "cmResolutions": {
                "constructed": partition["constructed"],
                "unconstructed": partition["unconstructed"],
            },
            "withResolutionRows": resolution_rows,
            "families": {},
            "sites": dict(sites),
            "relative": f"recensus_path_smoke/{path.name}",
        }
    finally:
        shutil.rmtree(iso, ignore_errors=True)


def _measure_clean(module, path: Path, workspace: Path) -> dict[str, Any]:
    """Production enumerate consumer for the planted Module.sugar terminal."""
    import shutil
    import tempfile

    from sugar_lift_py_tests.lift_rpc import provisional_contract_refs_from_demands
    from recensus_enumerate_consumer import measure_file_via_enumerate

    iso = Path(tempfile.mkdtemp(prefix="recensus-path-smoke-clean-"))
    try:
        plant = iso / path.name
        shutil.copy2(path, plant)
        refs = provisional_contract_refs_from_demands(iso)
        row = measure_file_via_enumerate(
            file_rel=path.name,
            workspace_root=iso,
            contract_refs=refs,
            distribution="recensus_path_smoke",
            source_workspace_root=iso,
        )
        row = dict(row)
        row["sites"] = dict(module._ast_site_prevalence(plant))
        row["relative"] = f"recensus_path_smoke/{path.name}"
        return row
    finally:
        shutil.rmtree(iso, ignore_errors=True)


def _measure_panic(module, path: Path, workspace: Path) -> dict[str, Any]:
    """Known panic through the production enumerate consumer."""
    import shutil
    import tempfile

    from sugar_lift_py_tests.gap.info import ConstructionGap
    from sugar_lift_py_tests.gap.panic import ConstructionPanic
    from recensus_enumerate_consumer import measure_file_via_enumerate
    import sugar_source_tree.tree as tree_mod

    iso = Path(tempfile.mkdtemp(prefix="recensus-path-smoke-panic-"))
    original = tree_mod.SourceFile.__init__

    def boom(self, *a, **k):
        raise ConstructionPanic(
            ConstructionGap(
                owner="recensus-path-smoke-planted-panic",
                blame=f"{path.name}:1:0",
                observed="OpaqueValue",
                requested="constructed value",
                fix="smoke tooth: cpanic must count 1",
            )
        )

    try:
        plant = iso / path.name
        shutil.copy2(path, plant)
        tree_mod.SourceFile.__init__ = boom  # type: ignore[method-assign]
        row = measure_file_via_enumerate(
            file_rel=path.name,
            workspace_root=iso,
            distribution="recensus_path_smoke",
            source_workspace_root=iso,
        )
    finally:
        tree_mod.SourceFile.__init__ = original  # type: ignore[method-assign]
        shutil.rmtree(iso, ignore_errors=True)
    row = dict(row)
    row["sites"] = dict(module._ast_site_prevalence(path))
    row["relative"] = f"recensus_path_smoke/{path.name}"
    return row


def _run_teeth(
    *,
    constructed: int,
    unconstructed: int,
    with_items_total: int,
    accounted: int,
    cpanic: int,
    construction_panics: list[dict[str, Any]],
    module_sugar_row: dict[str, Any] | None = None,
    conserves: bool,
    sealed_path: Path | None,
    path_verdict_so_far: str,
) -> tuple[dict[str, Any], str | None]:
    """Return (teeth_report, first_failed_tooth_name)."""
    teeth: dict[str, Any] = {}
    failed: str | None = None

    def fail(name: str, detail: str) -> None:
        nonlocal failed
        teeth[name] = {"pass": False, "detail": detail}
        if failed is None:
            failed = name

    def ok(name: str, detail: str) -> None:
        teeth[name] = {"pass": True, "detail": detail}

    if constructed > 0:
        ok("known_constructed", f"constructed={constructed}")
    else:
        fail("known_constructed", f"constructed={constructed} expected >0")

    observed_panic_identities = _sorted_panic_identities(construction_panics)
    expected_panic_identities = _sorted_panic_identities(
        [dict(row) for row in _EXPECTED_CONSTRUCTION_PANIC_IDENTITIES]
    )
    if observed_panic_identities == expected_panic_identities:
        ok(
            "known_panic",
            "exact terminal identities conserved: "
            + json.dumps(observed_panic_identities, sort_keys=True),
        )
    else:
        fail(
            "known_panic",
            f"cpanic={cpanic}; exact terminal identity mismatch: "
            f"observed={json.dumps(observed_panic_identities, sort_keys=True)} "
            f"expected={json.dumps(expected_panic_identities, sort_keys=True)}",
        )

    observed_module_sugar = _module_sugar_constructed_identity(module_sugar_row)
    retired_module_panic = _construction_panic_identity(
        dict(_RETIRED_MODULE_SUGAR_PANIC_IDENTITY)
    )
    if (
        observed_module_sugar == _EXPECTED_MODULE_SUGAR_CONSTRUCTED_IDENTITY
        and retired_module_panic not in observed_panic_identities
    ):
        ok(
            "module_sugar_constructed",
            "Module.sugar constructed at retired panic coordinate "
            f"{_RETIRED_MODULE_SUGAR_PANIC_IDENTITY['coordinate']}: "
            + json.dumps(observed_module_sugar, sort_keys=True),
        )
    else:
        fail(
            "module_sugar_constructed",
            "Module.sugar construction identity mismatch at retired panic coordinate "
            f"{_RETIRED_MODULE_SUGAR_PANIC_IDENTITY['coordinate']}: "
            f"observed={json.dumps(observed_module_sugar, sort_keys=True)} "
            "retiredPanicPresent="
            f"{retired_module_panic in observed_panic_identities}",
        )

    if unconstructed >= 1:
        ok("known_unconstructed", f"unconstructed={unconstructed}")
    else:
        fail(
            "known_unconstructed",
            f"unconstructed={unconstructed} expected >=1",
        )

    if with_items_total == 2 and accounted == with_items_total:
        ok(
            "with_items_accounted",
            f"accounted={accounted} with_items_total={with_items_total}",
        )
    else:
        fail(
            "with_items_accounted",
            f"accounted={accounted} with_items_total={with_items_total}; "
            "expected planted population 2/2",
        )

    if conserves:
        ok("conservation", "with census conserves")
    else:
        fail("conservation", "with census does not conserve")

    if sealed_path is not None and sealed_path.is_file():
        raw = sealed_path.read_text(encoding="utf-8")
        body = json.loads(raw)
        banned = [k for k in _FORBIDDEN_PRODUCT_KEYS if k in body]
        if banned:
            fail("no_product_r", f"forbidden product keys present: {banned}")
        elif body.get("measurementClass") != MEASUREMENT_CLASS:
            fail(
                "enrollment_class",
                f"measurementClass={body.get('measurementClass')!r} "
                f"expected {MEASUREMENT_CLASS!r}",
            )
        elif body.get("kind") != KIND:
            fail("enrollment_kind", f"kind={body.get('kind')!r}")
        else:
            ok("sealed_body", f"sealed {sealed_path}")
            ok("no_product_r", "no forbidden product keys")
            ok("enrollment_class", MEASUREMENT_CLASS)
    else:
        fail("sealed_body", "path_verdict.json missing")

    if path_verdict_so_far == "PATH_UNMEASURED":
        fail("crash_not_green", "path crashed — UNMEASURED, never green")
    else:
        ok("crash_not_green", "path completed without crash")

    return teeth, failed


def main(argv: list[str] | None = None) -> int:
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    started = time.time()
    phases: list[str] = []
    out_dir = Path(
        os.environ.get(
            "RECENSUS_PATH_SMOKE_OUT",
            str(_REPO / ".sugar" / "recensus-path-smoke"),
        )
    )
    # Isolate engine log under out-dir so smoke does not poison ambient state.
    engine_log = out_dir / "engine.jsonl"
    out_dir.mkdir(parents=True, exist_ok=True)
    os.environ["SUGAR_ENGINE_LOG"] = str(engine_log.resolve())
    os.environ["SUGAR_ENGINE_TRACE_EVENTS"] = "0"

    _narrate(
        f"PATH_SMOKE START measurementClass={MEASUREMENT_CLASS} "
        f"fixtures={_FIXTURES} out_dir={out_dir.resolve()}"
    )

    try:
        phases.append("load_recensus_module")
        _narrate("PATH_SMOKE phase=load_recensus_module")
        module = _load_recensus()
        worktree_sha = _worktree_sha()

        phases.append("enroll_micro_population")
        _narrate("PATH_SMOKE phase=enroll_micro_population")
        workspace = _FIXTURES
        constructed_path = workspace / "planted_constructed_with.py"
        opaque_path = workspace / "planted_opaque_with.py"
        clean_path = workspace / "planted_clean.py"
        panic_path = workspace / "planted_panic_host.py"
        for p in (constructed_path, opaque_path, clean_path, panic_path):
            if not p.is_file():
                raise FileNotFoundError(f"missing planted fixture: {p}")

        # Cache / out-dir write seam (must be writable).
        phases.append("cache_write")
        _narrate("PATH_SMOKE phase=cache_write")
        probe = out_dir / ".write-probe"
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink()

        # Manifest / pin shape over micro population (content auth for smoke only).
        phases.append("manifest_cid")
        _narrate("PATH_SMOKE phase=manifest_cid")
        from sugar_lift_py_tests.corpus_pin import pin_corpus
        from pandas_floor_summary import corpus_cid as corpus_manifest_shape_cid

        pin = pin_corpus(
            workspace, distribution="recensus_path_smoke", version="smoke-0"
        )
        shape_cid = corpus_manifest_shape_cid(list(pin.paths))
        _narrate(
            f"PATH_SMOKE pin files={len(pin.paths)} "
            f"aggregate={pin.aggregate_hash[:16]}… shape={shape_cid[:24]}…"
        )

        # Per-file lift (production doors) + panic plant.
        phases.append("per_file_lift")
        _narrate("PATH_SMOKE phase=per_file_lift")
        rows: list[dict[str, Any]] = []
        rows.append(_measure_constructed(module, constructed_path, workspace))
        _narrate("PATH_SMOKE measured planted_constructed_with")
        rows.append(_measure_opaque(module, opaque_path, workspace))
        _narrate("PATH_SMOKE measured planted_opaque_with")
        module_sugar_row = _measure_clean(module, clean_path, workspace)
        rows.append(module_sugar_row)
        _narrate("PATH_SMOKE measured planted_clean")
        rows.append(_measure_panic(module, panic_path, workspace))
        _narrate("PATH_SMOKE measured planted_panic_host")

        # Family counters + aggregation (board compose path pieces).
        phases.append("aggregation")
        _narrate("PATH_SMOKE phase=aggregation")
        cm: Counter[str] = Counter()
        with_resolution_rows: list[dict[str, Any]] = []
        sites: Counter[str] = Counter()
        families: Counter[str] = Counter()
        construction_panics: list[dict[str, Any]] = []
        for row in rows:
            cm.update({k: int(v) for k, v in (row.get("cmResolutions") or {}).items()})
            with_resolution_rows.extend(row.get("withResolutionRows") or [])
            sites.update({k: int(v) for k, v in (row.get("sites") or {}).items()})
            families.update({k: int(v) for k, v in (row.get("families") or {}).items()})
            if row.get("category") == "panic":
                panic = row.get("panic")
                if isinstance(panic, dict):
                    construction_panics.append(panic)
                if "ConstructionPanic" not in (row.get("families") or {}):
                    families["ConstructionPanic"] = (
                        int(families.get("ConstructionPanic") or 0) + 1
                    )

        cpanic = len(construction_panics)
        if cpanic == 0 and families.get("ConstructionPanic", 0) > 0:
            cpanic = int(families["ConstructionPanic"])

        # With-census conservation identity (the Class B door).
        phases.append("conservation")
        _narrate("PATH_SMOKE phase=conservation")
        partition = module._with_census_partition(with_resolution_rows, sites)
        constructed = int(partition.get("constructed") or 0)
        unconstructed = int(partition.get("unconstructed") or 0)
        with_items_total = int(partition.get("with_items_total") or 0)
        accounted = int(partition.get("accounted") or 0)
        conserves = bool(partition.get("conserves"))
        key_conservation = dict(partition.get("edgeWitness") or {})
        first_terminal_chain = {
            "worktreeSha": worktree_sha,
            "input": {
                "cmResolutions": dict(sorted(cm.items())),
                "site:with-item": with_items_total,
            },
            "coordinate": [
                "planted_constructed_with.py:10:4",
                "planted_opaque_with.py:5:4",
            ],
            "firstObservedTerminal": (
                "ValueError: with_items_total=2 constructed=0 gaps=0 "
                "accounted=0 unaccounted=2"
            ),
            "entrance": (
                "control_effect_recensus._with_census_partition "
                "(scripts/control_effect_recensus.py)"
            ),
            "afterFix": {
                "terminal": "constructed-result",
                "constructed": constructed,
                "unconstructed": unconstructed,
                "accounted": accounted,
                "with_items_total": with_items_total,
                "keyMissing": key_conservation.get("missingKeys"),
                "keyExtra": key_conservation.get("extraKeys"),
                "keyDuplicates": key_conservation.get("duplicateKeys"),
            },
        }
        _narrate(
            "PATH_SMOKE FIRST_TERMINAL_CHAIN "
            + json.dumps(first_terminal_chain, sort_keys=True)
        )

        # Discrimination lies (optional): one fault at a time so negative arms
        # are OBSERVED, not reasoned. Env RECENSUS_PATH_SMOKE_LIE=
        #   constructed_zero | swallow_panic | drop_opaque | crash_mid
        # A tooth only ever seen GREEN is decoration, not an instrument.
        lie = (os.environ.get("RECENSUS_PATH_SMOKE_LIE") or "").strip()
        if lie == "constructed_zero":
            _narrate("PATH_SMOKE LIE planted=constructed_zero")
            constructed = 0
            accounted = unconstructed
            conserves = accounted == with_items_total
            partition = dict(partition)
            partition["constructed"] = constructed
            partition["accounted"] = accounted
            partition["unaccounted"] = with_items_total - accounted
            partition["conserves"] = conserves
        elif lie == "swallow_panic":
            _narrate("PATH_SMOKE LIE planted=swallow_panic")
            cpanic = 0
            construction_panics = []
            families.pop("ConstructionPanic", None)
        elif lie == "drop_opaque":
            _narrate("PATH_SMOKE LIE planted=drop_opaque")
            # Vanish the unconstructed item; accounting teeth must PATH_RED.
            unconstructed = 0
            accounted = constructed
            conserves = accounted == with_items_total
            partition = dict(partition)
            partition["unconstructed"] = unconstructed
            partition["constructed"] = constructed
            partition["accounted"] = accounted
            partition["unaccounted"] = with_items_total - accounted
            partition["conserves"] = conserves
        elif lie == "crash_mid":
            _narrate("PATH_SMOKE LIE planted=crash_mid phase=after-conservation")
            raise RuntimeError(
                "planted crash mid-phase (discrimination arm: PATH_UNMEASURED)"
            )
        elif lie:
            raise RuntimeError(f"unknown RECENSUS_PATH_SMOKE_LIE={lie!r}")

        smoke_counts = {
            "note": (
                "smoke-scoped only — not R_construction_panics; "
                "CommitMeasurement must refuse these as panics terms"
            ),
            "filesMeasured": len(rows),
            "constructed": constructed,
            "unconstructed": unconstructed,
            "cpanic": cpanic,
            "constructionPanicIdentities": _sorted_panic_identities(
                construction_panics
            ),
            "moduleSugarConstructedIdentity": (
                _module_sugar_constructed_identity(module_sugar_row)
            ),
            "families": dict(sorted(families.items())),
            "cmResolutions": dict(sorted(cm.items())),
            "firstTerminalChain": first_terminal_chain,
            "withCensus": {
                "with_items_total": partition.get("with_items_total"),
                "constructed": constructed,
                "unconstructed": unconstructed,
                "accounted": accounted,
                "keyMultisetConservation": key_conservation,
                "conserves": conserves,
                "conservationIdentity": partition.get("conservationIdentity"),
            },
            "pin": {
                "fileCount": len(pin.paths),
                "aggregateHashPrefix": pin.aggregate_hash[:32],
                "manifestShapeCidPrefix": shape_cid[:40],
            },
        }

        # Attendance-style sealed path body (NOT control-effect-recensus).
        phases.append("seal_path_body")
        _narrate("PATH_SMOKE phase=seal_path_body")
        # Preliminary seal without teeth so sealed_body tooth can read the file;
        # then re-seal with final teeth/verdict.
        sealed = _seal_path(
            out_dir=out_dir,
            path_verdict="PATH_RED",  # provisional until teeth run
            path_phase="teeth",
            tooth=None,
            teeth={},
            smoke_counts=smoke_counts,
            phases=list(phases),
        )

        phases.append("teeth")
        _narrate("PATH_SMOKE phase=teeth")
        teeth, failed = _run_teeth(
            constructed=constructed,
            unconstructed=unconstructed,
            with_items_total=with_items_total,
            accounted=accounted,
            cpanic=cpanic,
            construction_panics=construction_panics,
            module_sugar_row=module_sugar_row,
            conserves=conserves,
            sealed_path=sealed,
            path_verdict_so_far="PATH_OK",
        )
        path_verdict = "PATH_OK" if failed is None else "PATH_RED"
        sealed = _seal_path(
            out_dir=out_dir,
            path_verdict=path_verdict,
            path_phase="done",
            tooth=failed,
            teeth=teeth,
            smoke_counts=smoke_counts,
            phases=list(phases) + ["done"],
        )
        # Attendance body separate class.
        attendance = {
            "schemaVersion": 1,
            "measurementClass": MEASUREMENT_CLASS,
            "measuredCommit": os.environ.get("GITHUB_SHA"),
            "status": "completed" if path_verdict == "PATH_OK" else "path-red",
            "pathVerdict": path_verdict,
        }
        (out_dir / "measurement.json").write_text(
            json.dumps(attendance, indent=2) + "\n", encoding="utf-8"
        )

        elapsed = time.time() - started
        _narrate(
            f"PATH_SMOKE DONE pathVerdict={path_verdict} failedTooth={failed} "
            f"constructed={constructed} unconstructed={unconstructed} "
            f"accounted={accounted}/{with_items_total} cpanic={cpanic} "
            f"elapsed_s={elapsed:.1f} sealed={sealed}"
        )
        if elapsed > 60:
            _narrate(
                f"PATH_SMOKE WARNING elapsed_s={elapsed:.1f} exceeded 60s budget"
            )
        return 0 if path_verdict == "PATH_OK" else 1

    except Exception as exc:  # noqa: BLE001 — crash is UNMEASURED path
        err = f"{type(exc).__name__}: {exc}"
        _narrate(f"PATH_SMOKE CRASH {err}")
        traceback.print_exc()
        phases.append("crash")
        try:
            _seal_path(
                out_dir=out_dir,
                path_verdict="PATH_UNMEASURED",
                path_phase="crash",
                tooth="crash_not_green",
                teeth={
                    "crash_not_green": {
                        "pass": False,
                        "detail": "crash is UNMEASURED path, never green",
                    }
                },
                smoke_counts={},
                phases=phases,
                error=err,
            )
            (out_dir / "measurement.json").write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "measurementClass": MEASUREMENT_CLASS,
                        "measuredCommit": os.environ.get("GITHUB_SHA"),
                        "status": "unmeasured",
                        "pathVerdict": "PATH_UNMEASURED",
                        "unmeasuredReason": err,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
