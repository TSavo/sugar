#!/usr/bin/env python3
"""Sole seal door for the control-effect recensus board.

SCOREBOARD_AUTHORITY = True lives HERE only. Workers
(``control_effect_recensus.py``) are SCOREBOARD_AUTHORITY = False and emit
partials (or a k=1 full-bin journal) that this module alone may mint as
``measurementClass=control-effect-recensus``.

Law (banked): R1–R6, dual-belt attendance, serial seal retired.
  compose_control_effect_board(plan, partials) → SealedBoard | UnmeasuredEnvelope

Partials: measurementClass=control-effect-recensus-shard; never top-level
R_construction_panics. UNMEASURED envelope omits measurementClass entirely.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

# Sole True declaration for the kit (test_one_authoritative_scoreboard).
SCOREBOARD_AUTHORITY = True

MEASUREMENT_CLASS_BOARD = "control-effect-recensus"
MEASUREMENT_CLASS_SHARD = "control-effect-recensus-shard"
KIND_SEALED = "control-effect-construction-recensus"
KIND_UNMEASURED = "control-effect-recensus-unmeasured/v1"
KIND_PARTIAL = "control-effect-recensus-shard-partial/v1"
KIND_PLAN = "control-effect-recensus-shard-plan/v1"
COMPOSE_SCHEMA = "control-effect-recensus-compose/v1"
PARTIAL_SCHEMA = "control-effect-recensus-shard-partial/v1"
PLAN_SCHEMA = "control-effect-recensus-shard-plan/v1"

_PANDAS_3_0_3_AGGREGATE_HASH = (
    "bbb70a76f4032eda3362102c8bd872ca769b6f8143a91f60a36374fa1066b76c"
)
_PANDAS_3_0_3_MANIFEST_SHAPE_CID = (
    "sha256:a223a4499d0909f22190748b4aca9144e35a58fec31e84cb924e2c25fd3c03d0"
)

_TOOLS = Path(__file__).resolve().parents[4] / "tools"
if _TOOLS.is_dir() and str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

# Package root for sealed board function facts (C4 Step 1).
_PKG_SRC = Path(__file__).resolve().parents[1] / "src"
if _PKG_SRC.is_dir() and str(_PKG_SRC) not in sys.path:
    sys.path.insert(0, str(_PKG_SRC))

from sugar_lift_py_tests.c4.board_function_facts import (  # noqa: E402
    LocalReading,
    board_fields_from_sealed_facts,
    seal_functions_clean_v1,
    seal_functions_enumerated_v1,
    seal_functions_population_v1,
)


def _blake3_512(data: bytes) -> str:
    try:
        import blake3  # type: ignore

        return "blake3-512:" + blake3.blake3(data, max_threads=1).digest(64).hex()
    except Exception:  # noqa: BLE001
        return "sha256:" + hashlib.sha256(data).hexdigest()


def canonical_cid(obj: Mapping[str, Any]) -> str:
    """Content id of a JSON-stable object (sort_keys, no host noise)."""
    rendered = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return _blake3_512(rendered.encode("utf-8"))


def shard_file_set_cid(files: Sequence[str]) -> str:
    return _blake3_512("\n".join(sorted(files)).encode("utf-8"))


def build_plan(
    *,
    enrolled_files: Sequence[str],
    shard_count: int,
    measured_commit: str,
    aggregate_hash: str,
    manifest_shape_cid: str,
    bins: Sequence[Sequence[str]],
    split_mode: str,
    prior_hits: int,
    prior_misses: int,
    estimated_loads: Sequence[float],
    demand_table_cid: str | None = None,
    demand_table_path: str | None = None,
) -> dict[str, Any]:
    enrolled = sorted(enrolled_files)
    bin_lists = [list(b) for b in bins]
    if len(bin_lists) != shard_count:
        raise ValueError(
            f"plan bins length {len(bin_lists)} != shard_count {shard_count}"
        )
    flat: list[str] = []
    for b in bin_lists:
        flat.extend(b)
    if sorted(flat) != enrolled:
        raise ValueError(
            "plan bins must partition enrolledFiles (union equality failed)"
        )
    if len(flat) != len(set(flat)):
        raise ValueError("plan bins must be pairwise disjoint (duplicate file)")
    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "kind": KIND_PLAN,
        "measuredCommit": measured_commit,
        "aggregateHash": aggregate_hash,
        "manifestShapeCid": manifest_shape_cid,
        "shardCount": shard_count,
        "splitMode": split_mode,
        "priorHits": prior_hits,
        "priorMisses": prior_misses,
        "enrolledFiles": enrolled,
        "bins": bin_lists,
        "estimatedLoadS": [float(x) for x in estimated_loads],
    }
    # Prebuilt provisional demand table: content-addressed once at plan time;
    # every shard LOADS it so cold processes never re-walk the corpus (k=8).
    if demand_table_cid is not None:
        plan["demandTableCid"] = demand_table_cid
    if demand_table_path is not None:
        plan["demandTablePath"] = demand_table_path
    plan["planCid"] = canonical_cid({k: v for k, v in plan.items() if k != "planCid"})
    return plan


def mint_partial(
    *,
    plan: Mapping[str, Any],
    shard_index: int,
    terminal_rows: Sequence[tuple[str, Mapping[str, Any]]],
    measured_commit: str | None = None,
    status: str = "completed",
    unmeasured_reason: str | None = None,
) -> dict[str, Any]:
    """Mint a shard partial. Never includes R_construction_panics top-level."""
    shard_count = int(plan["shardCount"])
    if shard_index < 0 or shard_index >= shard_count:
        raise ValueError(f"shard_index {shard_index} out of range for k={shard_count}")
    assigned = list(plan["bins"][shard_index])
    assigned_set = set(assigned)
    terminals = [(f, dict(r)) for f, r in terminal_rows]
    terminal_files = [f for f, _ in terminals]
    missing = sorted(assigned_set - set(terminal_files))
    extra = sorted(set(terminal_files) - assigned_set)
    dups = sorted({f for f in terminal_files if terminal_files.count(f) > 1})
    malformed = [
        f
        for f, raw in terminals
        if not isinstance(raw, dict) or not raw.get("category")
    ]
    files_complete = (
        not missing
        and not extra
        and not dups
        and not malformed
        and len(terminal_files) == len(assigned)
    )
    fn_total = sum(int((r or {}).get("functionsTotal") or 0) for _, r in terminals)
    fn_enum = sum(
        int(
            (r or {}).get("functionsEnumerated")
            if (r or {}).get("functionsEnumerated") is not None
            else (r or {}).get("functionsTotal")
            or 0
        )
        for _, r in terminals
    )
    clean_refused = any(
        (r or {}).get("cleanRatioRefused") or (r or {}).get("functionsClean") is None
        for _, r in terminals
        if int((r or {}).get("functionsTotal") or 0) > 0
    )
    fn_clean: int | None
    if clean_refused:
        fn_clean = None
    else:
        fn_clean = sum(int((r or {}).get("functionsClean") or 0) for _, r in terminals)

    panics: list[dict[str, Any]] = []
    families: Counter[str] = Counter()
    instrument_defects: list[dict[str, Any]] = []
    for file, raw in terminals:
        cat = str(raw.get("category") or "")
        families.update(raw.get("families") or {})
        if cat == "panic":
            panic = raw.get("panic")
            if isinstance(panic, dict):
                panics.append(dict(panic))
            elif "ConstructionPanic" not in (raw.get("families") or {}):
                families["ConstructionPanic"] += 1
        elif cat not in {"completed", ""}:
            defect = raw.get("defect")
            instrument_defects.append(
                dict(defect)
                if isinstance(defect, dict)
                else {"file": file, "type": cat, "message": cat}
            )

    measured = status == "completed" and files_complete and unmeasured_reason is None
    if not measured and unmeasured_reason is None:
        unmeasured_reason = (
            f"sub-population incomplete missing={missing} extra={extra} "
            f"dups={dups} malformed={malformed}"
        )
        status = "unmeasured"

    body: dict[str, Any] = {
        "schema": PARTIAL_SCHEMA,
        "kind": KIND_PARTIAL,
        "measurementClass": MEASUREMENT_CLASS_SHARD,
        "SCOREBOARD_AUTHORITY": False,
        "measuredCommit": measured_commit or plan.get("measuredCommit"),
        "planCid": plan["planCid"],
        "aggregateHash": plan.get("aggregateHash"),
        "manifestShapeCid": plan.get("manifestShapeCid"),
        "shardIndex": shard_index,
        "shardCount": shard_count,
        "populationScope": {
            "kind": "shard-bin",
            "assignedFiles": assigned,
            "assignedFileCount": len(assigned),
        },
        "shardFileSetCid": shard_file_set_cid(assigned),
        "terminalFiles": terminal_files,
        "terminalRows": [
            {"file": f, "result": r} for f, r in terminals
        ],
        "subDenominator": {
            "files": {
                "enrolled": len(assigned),
                "terminal": len(terminal_files),
                "complete": files_complete,
                "missingFiles": missing,
                "extraFiles": extra,
                "duplicateFiles": dups,
                "malformedRows": malformed,
            },
            "functions": {
                "total": fn_total,
                "enumerated": fn_enum,
                "clean": fn_clean,
                "cleanRatioRefused": clean_refused,
                "unit": "construction-function-locus",
            },
        },
        "shardResiduals": {
            "constructionPanics": panics,
            "families": dict(families),
            "instrumentDefects": instrument_defects,
            "R_construction_panics_shard": len(panics),
        },
        "status": status,
        "measured": measured,
        "unmeasuredReason": unmeasured_reason,
    }
    # Forbidden fields must never appear:
    assert "R_construction_panics" not in body
    body["partialCid"] = canonical_cid(
        {k: v for k, v in body.items() if k != "partialCid"}
    )
    return body


def aggregate_terminal_rows(
    measured_rows: Sequence[tuple[str, Mapping[str, Any]]],
    *,
    enrolled_files: Sequence[str],
    manifest_cid: str | None = None,
) -> dict[str, Any]:
    """Aggregate checkpoint-style (file, result) rows into residual counters.

    Does not mint measurementClass or seal fields — compose does that.
    """
    file_names = list(enrolled_files)
    terminal_files = [file for file, _ in measured_rows]
    missing_files = sorted(set(file_names) - set(terminal_files))
    duplicate_files = sorted(
        {file for file in terminal_files if terminal_files.count(file) > 1}
    )
    malformed_rows = sorted(
        file
        for file, raw in measured_rows
        if not isinstance(raw, dict) or not raw.get("category")
    )

    families: Counter[str] = Counter()
    desugar_families: Counter[str] = Counter()
    desugar_categories: Counter[str] = Counter()
    desugar_by_category_owner: Counter[str] = Counter()
    backend_defects: Counter[str] = Counter()
    cm_resolutions: Counter[str] = Counter()
    unrecognized_cm_kinds: Counter[str] = Counter()
    ast_sites: Counter[str] = Counter()
    desugar_construction_panics: list[dict[str, Any]] = []
    desugar_defects: list[dict[str, Any]] = []
    desugar_designed_gaps: list[dict[str, Any]] = []
    unresolvable_dispatch: list[dict[str, Any]] = []
    construction_panics: list[dict[str, Any]] = []
    defects: list[dict[str, Any]] = []
    floor_rows: list[dict[str, Any]] = []
    files_completed = 0
    functions_total = 0
    functions_clean = 0
    functions_enumerated = 0
    clean_ratio_refused = False
    clean_refuse_reasons: list[str] = []
    r_instrument_blind = 0
    r_instrument_blind_functions = 0

    for file, raw in measured_rows:
        row = dict(raw)
        category = str(row.get("category"))
        floor_rows.append({"file": file, "category": category})
        ft = int(row.get("functionsTotal") or 0)
        functions_total += ft
        functions_enumerated += int(
            row.get("functionsEnumerated")
            if row.get("functionsEnumerated") is not None
            else (ft if category == "completed" else 0)
        )
        # Clean: never treat missing as 0-of-total tautology. Null → refuse ratio.
        if row.get("cleanRatioRefused") or row.get("functionsClean") is None:
            if ft > 0 or row.get("cleanRatioRefused"):
                clean_ratio_refused = True
                reason = row.get("cleanRefuseReason") or "functionsClean unmeasured"
                clean_refuse_reasons.append(f"{file}:{reason}")
        else:
            functions_clean += int(row.get("functionsClean") or 0)
        # R_instrument_blind taxonomy deleted — panic is panic.
        families.update(row.get("families") or {})
        desugar_families.update(row.get("desugarFamilies") or {})
        desugar_categories.update(row.get("desugarCategories") or {})
        desugar_by_category_owner.update(row.get("desugarByCategoryOwner") or {})
        backend_defects.update(row.get("backendDefects") or {})
        cm_resolutions.update(row.get("cmResolutions") or {})
        unrecognized_cm_kinds.update(row.get("unrecognizedCmResolutionKinds") or {})
        ast_sites.update(row.get("astSites") or {})
        desugar_construction_panics.extend(row.get("desugarConstructionPanics") or [])
        desugar_defects.extend(row.get("desugarDefects") or [])
        desugar_designed_gaps.extend(row.get("desugarDesignedGaps") or [])

        if category == "completed":
            files_completed += 1
        else:
            # construct-or-panic: anything not completed is a panic (no kind labels)
            panic = row.get("panic")
            if isinstance(panic, dict):
                construction_panics.append(dict(panic))
            defect = row.get("defect") or panic
            if isinstance(defect, dict):
                defects.append(dict(defect))
            elif panic is not None:
                defects.append({"file": file, "type": "panic", "message": str(panic)})
            else:
                defects.append(
                    {"file": file, "type": str(category), "message": str(category)}
                )

    files_complete = (
        len(measured_rows) == len(file_names)
        and not missing_files
        and not duplicate_files
        and not malformed_rows
    )
    return {
        "families": families,
        "desugar_families": desugar_families,
        "desugar_categories": desugar_categories,
        "desugar_by_category_owner": desugar_by_category_owner,
        "backend_defects": backend_defects,
        "cm_resolutions": cm_resolutions,
        "unrecognized_cm_kinds": unrecognized_cm_kinds,
        "ast_sites": ast_sites,
        "desugar_construction_panics": desugar_construction_panics,
        "desugar_defects": desugar_defects,
        "desugar_designed_gaps": desugar_designed_gaps,
        "unresolvable_dispatch": unresolvable_dispatch,
        "construction_panics": construction_panics,
        "defects": defects,
        "floor_rows": floor_rows,
        "files_completed": files_completed,
        "functions_total": functions_total,
        "functions_clean": functions_clean,
        "functions_enumerated": functions_enumerated,
        "clean_ratio_refused": clean_ratio_refused,
        "clean_refuse_reasons": clean_refuse_reasons[:50],
        "r_instrument_blind": r_instrument_blind,
        "r_instrument_blind_functions": r_instrument_blind_functions,
        "missing_files": missing_files,
        "duplicate_files": duplicate_files,
        "malformed_rows": malformed_rows,
        "files_complete": files_complete,
        "enrolled_files": file_names,
        "terminal_count": len(measured_rows),
        "manifest_cid": manifest_cid,
    }


def seal_board_from_aggregate(
    agg: Mapping[str, Any],
    *,
    plan: Mapping[str, Any] | None,
    per_shard_cids: Mapping[str, str] | None,
    compose_cid: str | None,
    measured_commit: str,
    corpus: str | None = None,
    corpus_root: str | None = None,
    corpus_pin_summary: Mapping[str, Any] | None = None,
    aggregate_hash: str | None = None,
    manifest_shape_cid: str | None = None,
    paths: Mapping[str, str] | None = None,
    elapsed_seconds: float | None = None,
    source_stamp: Mapping[str, Any] | None = None,
    with_census: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Mint the sealed authoritative board body. Sole mint of the class."""
    file_names = list(agg["enrolled_files"])
    families = Counter(agg["families"])
    desugar_families = Counter(agg["desugar_families"])
    desugar_categories = Counter(agg["desugar_categories"])
    backend_defects = Counter(agg["backend_defects"])
    construction_panics = list(agg["construction_panics"])
    defects = list(agg["defects"])
    r_construction = sum(families.values())
    r_desugar = sum(desugar_families.values())
    r_backend = sum(backend_defects.values())

    # C4 Step 1: three sealed meanings, not one overloaded int.
    # LocalReadings are free; only the seal doors + board_fields_from_sealed_facts
    # may mint board function fields. Bare ints cannot pass the consumer.
    pin_id = (
        aggregate_hash
        or (plan or {}).get("aggregateHash")
        or _PANDAS_3_0_3_AGGREGATE_HASH
    )
    pop_fact = seal_functions_population_v1(
        LocalReading(int(agg["functions_total"]), "functions_total"),
        tip=measured_commit,
        pin=str(pin_id),
    )
    enum_fact = seal_functions_enumerated_v1(
        LocalReading(int(agg.get("functions_enumerated") or 0), "functions_enumerated"),
        tip=measured_commit,
        pin=str(pin_id),
    )
    if agg.get("clean_ratio_refused"):
        clean_fact = seal_functions_clean_v1(
            LocalReading(None, "functions_clean"),
            tip=measured_commit,
            pin=str(pin_id),
            refused=True,
            refuse_reason=(
                "one or more files refused functionsClean "
                "(would be tautological clean%)"
            ),
        )
    else:
        clean_fact = seal_functions_clean_v1(
            LocalReading(int(agg["functions_clean"]), "functions_clean"),
            tip=measured_commit,
            pin=str(pin_id),
            refused=False,
        )
    # Consumer close: bare int cannot become a board field.
    fn_fields = board_fields_from_sealed_facts(pop_fact, enum_fact, clean_fact)

    body: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": KIND_SEALED,
        "measurementClass": MEASUREMENT_CLASS_BOARD,
        "status": "sealed",
        "measured": True,
        "SCOREBOARD_AUTHORITY": True,
        "measuredCommit": measured_commit,
        "authority": (
            "sole authoritative Python corpus scoreboard; every other census "
            "output is non-authoritative; sole seal door is compose_control_effect_board"
        ),
        "composeMode": "lpt-enrollment-v1" if plan else "k1-compose-v1",
        "corpusAuthentication": {
            "aggregateHash": aggregate_hash
            or (plan or {}).get("aggregateHash")
            or "",
            "requiredAggregateHash": _PANDAS_3_0_3_AGGREGATE_HASH,
            "manifestShapeCid": manifest_shape_cid
            or (plan or {}).get("manifestShapeCid")
            or "",
            "requiredManifestShapeCid": _PANDAS_3_0_3_MANIFEST_SHAPE_CID,
        },
        "commit": measured_commit,
        "corpus": corpus,
        "corpusRoot": corpus_root,
        "corpusPin": dict(corpus_pin_summary) if corpus_pin_summary else None,
        "door": "enum:path_source→SourceFile→functions→sugar→desugar",
        "isolation": "in-process",
        "paths": dict(paths or {}),
        # Dual unit denominator — files and functions NEVER share a slot.
        # functions.* comes only from sealed meaning types (C4 consumer close).
        "denominator": {
            "files": {
                "enrolled": len(file_names),
                "terminalRows": int(agg["terminal_count"]),
                "completed": int(agg["files_completed"]),
                "corpusManifestCid": agg.get("manifest_cid"),
                "enrolledFiles": list(file_names),
                "missingFiles": list(agg["missing_files"]),
                "duplicateFiles": list(agg["duplicate_files"]),
                "malformedRows": list(agg["malformed_rows"]),
                "complete": bool(agg["files_complete"]),
            },
            "functions": dict(fn_fields["denominator_functions"]),
            # Back-compat flat keys (file unit only) for older readers.
            "enrolled": len(file_names),
            "terminalRows": int(agg["terminal_count"]),
            "completed": int(agg["files_completed"]),
            "corpusManifestCid": agg.get("manifest_cid"),
            "enrolledFiles": list(file_names),
            "missingFiles": list(agg["missing_files"]),
            "duplicateFiles": list(agg["duplicate_files"]),
            "malformedRows": list(agg["malformed_rows"]),
            "complete": bool(agg["files_complete"]),
        },
        "filesTotal": len(file_names),
        "filesCompleted": int(agg["files_completed"]),
        "enrolledFiles": len(file_names),
        "populationSize": len(file_names),
        "defects": defects,
        "instrumentDefects": list(defects),
        "R_instrument_defects": len(defects),
        "constructionPanics": construction_panics,
        "R_construction_panics": len(construction_panics),
        # Function fields only via sealed types — bare ints cannot land here.
        "functionsTotal": fn_fields["functionsTotal"],
        "functionsEnumerated": fn_fields["functionsEnumerated"],
        "functionsUnaccounted": fn_fields["functionsUnaccounted"],
        "functionsConstructClean": fn_fields["functionsConstructClean"],
        "cleanRatioRefused": fn_fields["cleanRatioRefused"],
        "sealedFunctionFactCids": dict(fn_fields["sealedFactCids"]),
        "cleanRefuseReasons": list(agg.get("clean_refuse_reasons") or []),
        "R": r_construction,
        "R_construction": r_construction,
        "families": dict(
            sorted(families.items(), key=lambda item: (-item[1], item[0]))
        ),
        "R_desugar": r_desugar,
        "desugarCategories": dict(
            sorted(desugar_categories.items(), key=lambda item: (-item[1], item[0]))
        ),
        "R_desugar_owed_work": int(desugar_categories.get("typed-refusal", 0)),
        "R_desugar_accounted_semantics": int(
            desugar_categories.get("constructed-effect", 0)
        ),
        "desugarByCategoryOwner": dict(
            sorted(
                Counter(agg["desugar_by_category_owner"]).items(),
                key=lambda item: (-item[1], item[0]),
            )
        ),
        "desugarFamilies": dict(
            sorted(desugar_families.items(), key=lambda item: (-item[1], item[0]))
        ),
        "R_backend_defects": r_backend,
        "backendDefects": dict(
            sorted(backend_defects.items(), key=lambda item: (-item[1], item[0]))
        ),
        "cmResolutions": dict(
            sorted(
                Counter(agg["cm_resolutions"]).items(),
                key=lambda item: (-item[1], item[0]),
            )
        ),
        "R_cm_derived_contract": int(
            Counter(agg["cm_resolutions"]).get("derived-contract", 0)
        ),
        "withCensus": with_census,
        "astSitePrevalence": dict(
            sorted(
                Counter(agg["ast_sites"]).items(),
                key=lambda item: (-item[1], item[0]),
            )
        ),
        "desugarConstructionPanics": list(agg["desugar_construction_panics"]),
        "R_desugar_construction_panics": len(agg["desugar_construction_panics"]),
        "desugarDefects": list(agg["desugar_defects"]),
        "R_desugar_defects": len(agg["desugar_defects"]),
        "unresolvableDispatchTargets": list(agg["unresolvable_dispatch"]),
        "R_unresolvable_dispatch_targets": len(agg["unresolvable_dispatch"]),
        "elapsedSeconds": elapsed_seconds,
        "planCid": (plan or {}).get("planCid"),
        "perShardCids": dict(sorted((per_shard_cids or {}).items())),
        "composeSchema": COMPOSE_SCHEMA,
    }
    if source_stamp is not None:
        body["sourceStamp"] = dict(source_stamp)
        # Host/load noise stays in sourceStamp; bodyCid excludes it.
    if compose_cid is not None:
        body["composeCid"] = compose_cid
    # bodyCid over seal-domain fields (exclude host-volatile sourceStamp).
    seal_domain = {
        k: v
        for k, v in body.items()
        if k not in {"sourceStamp", "bodyCid", "paths", "elapsedSeconds"}
    }
    body["bodyCid"] = canonical_cid(seal_domain)
    return body


def unmeasured_envelope(
    *,
    plan: Mapping[str, Any] | None,
    missing_shards: Sequence[str],
    unmeasured_reasons: Mapping[str, str],
    measured_commit: str | None = None,
) -> dict[str, Any]:
    """Attendance testimony only. NEVER measurementClass=control-effect-recensus."""
    env: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": KIND_UNMEASURED,
        # measurementClass OMITTED — dual belt A
        "status": "unmeasured",
        "measured": False,
        "measuredCommit": measured_commit
        or (plan or {}).get("measuredCommit"),
        "planCid": (plan or {}).get("planCid"),
        "missingShards": list(missing_shards),
        "unmeasuredReasons": dict(unmeasured_reasons),
        "denominator": {"complete": False},
    }
    assert "measurementClass" not in env
    assert "R_construction_panics" not in env
    assert "bodyCid" not in env
    return env


def compose_from_partials(
    plan: Mapping[str, Any],
    partials: Sequence[Mapping[str, Any]],
    *,
    corpus: str | None = None,
    corpus_root: str | None = None,
    corpus_pin_summary: Mapping[str, Any] | None = None,
    paths: Mapping[str, str] | None = None,
    elapsed_seconds: float | None = None,
    source_stamp: Mapping[str, Any] | None = None,
    with_census_fn=None,
) -> tuple[str, dict[str, Any]]:
    """Sole compose door. Returns (\"sealed\"|\"unmeasured\", body)."""
    k = int(plan["shardCount"])
    by_index: dict[int, Mapping[str, Any]] = {}
    missing: list[str] = []
    reasons: dict[str, str] = {}

    for p in partials:
        try:
            idx = int(p["shardIndex"])
        except (KeyError, TypeError, ValueError):
            continue
        by_index[idx] = p

    for i in range(k):
        seat = f"s{i:02d}"
        p = by_index.get(i)
        if p is None:
            missing.append(seat)
            reasons[seat] = "receipt absent"
            continue
        if p.get("planCid") != plan.get("planCid"):
            missing.append(seat)
            reasons[seat] = f"planCid mismatch got={p.get('planCid')!r}"
            continue
        if p.get("measurementClass") != MEASUREMENT_CLASS_SHARD:
            missing.append(seat)
            reasons[seat] = (
                f"wrong measurementClass {p.get('measurementClass')!r} "
                f"(want {MEASUREMENT_CLASS_SHARD})"
            )
            continue
        if p.get("status") == "unmeasured" or not p.get("measured"):
            missing.append(seat)
            reasons[seat] = str(
                p.get("unmeasuredReason") or "partial status=unmeasured"
            )
            continue
        assigned = list(plan["bins"][i])
        if p.get("shardFileSetCid") != shard_file_set_cid(assigned):
            missing.append(seat)
            reasons[seat] = "shardFileSetCid mismatch vs plan bin"
            continue
        sub = (p.get("subDenominator") or {}).get("files") or {}
        if not sub.get("complete"):
            missing.append(seat)
            reasons[seat] = "subDenominator.files.complete is false"
            continue
        if "R_construction_panics" in p:
            missing.append(seat)
            reasons[seat] = "partial carries forbidden top-level R_construction_panics"
            continue

    if missing:
        return "unmeasured", unmeasured_envelope(
            plan=plan,
            missing_shards=missing,
            unmeasured_reasons=reasons,
            measured_commit=str(plan.get("measuredCommit") or ""),
        )

    # Concat terminals in enrolled order for determinism.
    row_by_file: dict[str, Mapping[str, Any]] = {}
    per_shard_cids: dict[str, str] = {}
    for i in range(k):
        p = by_index[i]
        per_shard_cids[f"s{i:02d}"] = str(p.get("partialCid") or "")
        for entry in p.get("terminalRows") or []:
            if not isinstance(entry, dict):
                continue
            f = entry.get("file")
            r = entry.get("result")
            if isinstance(f, str) and isinstance(r, dict):
                row_by_file[f] = r

    enrolled = list(plan["enrolledFiles"])
    measured_rows = [(f, row_by_file[f]) for f in enrolled if f in row_by_file]
    agg = aggregate_terminal_rows(
        measured_rows,
        enrolled_files=enrolled,
        manifest_cid=str(plan.get("manifestShapeCid") or ""),
    )
    if not agg["files_complete"]:
        return "unmeasured", unmeasured_envelope(
            plan=plan,
            missing_shards=["compose"],
            unmeasured_reasons={
                "compose": (
                    f"full concat incomplete missing={agg['missing_files']} "
                    f"dups={agg['duplicate_files']} malformed={agg['malformed_rows']}"
                )
            },
            measured_commit=str(plan.get("measuredCommit") or ""),
        )

    partial_cids_sorted = sorted(per_shard_cids.values())
    compose_cid = canonical_cid(
        {
            "schema": COMPOSE_SCHEMA,
            "planCid": plan.get("planCid"),
            "partialCids": partial_cids_sorted,
        }
    )

    with_census = None
    if with_census_fn is not None:
        with_census = with_census_fn(
            Counter(agg["cm_resolutions"]),
            Counter(agg["ast_sites"]),
            Counter(agg["unrecognized_cm_kinds"]),
        )

    board = seal_board_from_aggregate(
        agg,
        plan=plan,
        per_shard_cids=per_shard_cids,
        compose_cid=compose_cid,
        measured_commit=str(plan.get("measuredCommit") or ""),
        corpus=corpus,
        corpus_root=corpus_root,
        corpus_pin_summary=corpus_pin_summary,
        aggregate_hash=str(plan.get("aggregateHash") or ""),
        manifest_shape_cid=str(plan.get("manifestShapeCid") or ""),
        paths=paths,
        elapsed_seconds=elapsed_seconds,
        source_stamp=source_stamp,
        with_census=with_census,
    )
    return "sealed", board


def compose_k1_from_rows(
    measured_rows: Sequence[tuple[str, Mapping[str, Any]]],
    *,
    enrolled_files: Sequence[str],
    measured_commit: str,
    aggregate_hash: str,
    manifest_shape_cid: str,
    corpus: str | None = None,
    corpus_root: str | None = None,
    corpus_pin_summary: Mapping[str, Any] | None = None,
    paths: Mapping[str, str] | None = None,
    elapsed_seconds: float | None = None,
    source_stamp: Mapping[str, Any] | None = None,
    with_census_fn=None,
    manifest_cid: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """k=1 path: one full-bin partial + compose (serial observation, one seal door)."""
    enrolled = sorted(enrolled_files)
    plan = build_plan(
        enrolled_files=enrolled,
        shard_count=1,
        measured_commit=measured_commit,
        aggregate_hash=aggregate_hash,
        manifest_shape_cid=manifest_shape_cid,
        bins=[enrolled],
        split_mode="k1",
        prior_hits=0,
        prior_misses=0,
        estimated_loads=[0.0],
    )
    partial = mint_partial(
        plan=plan,
        shard_index=0,
        terminal_rows=list(measured_rows),
        measured_commit=measured_commit,
    )
    return compose_from_partials(
        plan,
        [partial],
        corpus=corpus,
        corpus_root=corpus_root,
        corpus_pin_summary=corpus_pin_summary,
        paths=paths,
        elapsed_seconds=elapsed_seconds,
        source_stamp=source_stamp,
        with_census_fn=with_census_fn,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan",
        type=Path,
        required=True,
        help="shard plan JSON (planCid identity)",
    )
    parser.add_argument(
        "--partials-dir",
        type=Path,
        required=True,
        help="directory of partial-*.json shard bodies",
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="sealed board or unmeasured envelope path",
    )
    args = parser.parse_args(argv)
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    partials: list[dict[str, Any]] = []
    for path in sorted(args.partials_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("kind") == KIND_PARTIAL:
            partials.append(data)
    status, body = compose_from_partials(plan, partials)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"COMPOSE status={status} out={args.out} "
        f"missing={body.get('missingShards')} bodyCid={body.get('bodyCid')}",
        flush=True,
    )
    return 0 if status == "sealed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
