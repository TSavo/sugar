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

from sugar_lift_py_tests.repo_root import (
    resolve_repo_root,
    sugar_lift_py_tests_package_root,
)

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

# The three receipt edges are intentionally concrete.  V1 is not a general
# provenance framework; these names are the only paths the seal authenticates.
EDGE_ENUMERATE_FILE = "enumerate-roster-to-file-terminal/v1"
EDGE_WITH_PARTITION = "canonical-with-tally-to-partition/v1"
EDGE_TERMINAL_SEAL = "terminal-rows-to-aggregate-seal/v1"
STAGE_ENUMERATE_FILE_TERMINAL = "recensus-enumerate-file-terminal/v1"
STAGE_WITH_TALLY_PARTITION = "control-effect-with-tally-partition/v1"
STAGE_TERMINAL_AGGREGATE_SEAL = "compose-terminal-aggregate-seal/v1"
_CONSTRUCTION_PANIC_TYPE = "sugar_lift_py_tests.gap.panic.ConstructionPanic"
_SOURCE_PANIC_PREFIX = "sugar_source_tree.panic."
_TERMINAL_KINDS = frozenset({"constructed", "construction-panic"})
_TERMINAL_CONVENTION = {
    "observed_chain_length": "number of observed terminals in order",
    "blocking_terminal_count": "number of terminals that blocked construction",
    "final_terminal": "last observed terminal, separate from both counts",
}
_RUNTIME_AUTO = object()

_PANDAS_3_0_3_AGGREGATE_HASH = (
    "bbb70a76f4032eda3362102c8bd872ca769b6f8143a91f60a36374fa1066b76c"
)
_PANDAS_3_0_3_MANIFEST_SHAPE_CID = (
    "sha256:a223a4499d0909f22190748b4aca9144e35a58fec31e84cb924e2c25fd3c03d0"
)

_TOOLS = resolve_repo_root() / "tools"
if _TOOLS.is_dir() and str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

# Package root for sealed board function facts (C4 Step 1).
_PKG_SRC = sugar_lift_py_tests_package_root() / "src"
if _PKG_SRC.is_dir() and str(_PKG_SRC) not in sys.path:
    sys.path.insert(0, str(_PKG_SRC))

from sugar_lift_py_tests.c4.board_function_facts import (  # noqa: E402
    LocalReading,
    board_fields_from_sealed_facts,
    require_sealed_board_function_fields,
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


def _runtime_attestation_fields(
    runtime_attestation: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    """Validate one closed runtime witness without trusting its claimed CID."""
    from sugar_lift_py_tests.authenticated_pytest import runtime_cid_for_identity

    required_fields = {"requiredRuntime", "runtimeIdentity", "runtimeCid"}
    if not required_fields.issubset(runtime_attestation):
        return None, (
            "runtimeIdentity/v1 absent: "
            f"missing={sorted(required_fields - set(runtime_attestation))}"
        )
    required = runtime_attestation.get("requiredRuntime")
    identity = runtime_attestation.get("runtimeIdentity")
    claimed_cid = runtime_attestation.get("runtimeCid")
    if not isinstance(required, str) or not required:
        return None, "requiredRuntime absent from runtimeIdentity/v1 testimony"
    if not isinstance(identity, Mapping):
        return None, "runtimeIdentity/v1 absent"
    try:
        recomputed_cid = runtime_cid_for_identity(identity)
    except Exception as error:  # closed runtime schema names its own defect
        return None, f"runtimeIdentity/v1 malformed: {type(error).__name__}: {error}"
    if claimed_cid != recomputed_cid:
        return None, "runtimeCid is not recomputable from runtimeIdentity/v1"
    observed_required = f"{identity.get('implementation')}-{identity.get('version')}"
    if required != observed_required:
        return None, (
            "requiredRuntime mismatches its runtimeIdentity/v1: "
            f"required={required} observed={observed_required}"
        )
    return {
        "requiredRuntime": required,
        "runtimeIdentity": dict(identity),
        "runtimeCid": recomputed_cid,
    }, None


def resolve_executing_runtime_attestation() -> (
    tuple[dict[str, Any] | None, dict[str, Any]]
):
    """Authenticate the executing interpreter before any producer input opens."""
    from sugar_lift_py_tests import authenticated_pytest as runtime_authority

    try:
        required = runtime_authority.declared_interpreter_runtime()
    except Exception as error:
        return None, {
            "runtimeIdentityFailure": (
                f"requiredRuntime resolution failed: {type(error).__name__}: {error}"
            )
        }
    try:
        identity = runtime_authority.observe_runtime_identity_v1()
    except Exception as error:
        return None, {
            "requiredRuntime": required,
            "runtimeIdentityFailure": str(error),
        }

    identity_wire = identity.to_wire()
    try:
        runtime_cid = runtime_authority.runtime_cid_for_identity(identity)
    except Exception as error:
        return None, {
            "requiredRuntime": required,
            "runtimeIdentityFailure": str(error),
        }
    observed = {
        "requiredRuntime": required,
        "runtimeIdentity": identity_wire,
        "runtimeCid": runtime_cid,
    }
    try:
        runtime_authority.authenticate_runtime_identity_v1(identity)
    except runtime_authority.ExecutionEnvironmentMismatch as error:
        return None, {**observed, "runtimeIdentityMismatch": str(error)}
    except Exception as error:
        return None, {
            **observed,
            "runtimeIdentityFailure": f"{type(error).__name__}: {error}",
        }
    validated, reason = _runtime_attestation_fields(observed)
    if validated is None:
        return None, {**observed, "runtimeIdentityFailure": str(reason)}
    return validated, {}


def _resolve_runtime_argument(
    runtime_attestation: Mapping[str, Any] | None | object,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if runtime_attestation is _RUNTIME_AUTO:
        return resolve_executing_runtime_attestation()
    if runtime_attestation is None:
        return None, {"runtimeIdentityFailure": "runtimeIdentity/v1 absent"}
    if not isinstance(runtime_attestation, Mapping):
        return None, {"runtimeIdentityFailure": "runtimeIdentity/v1 malformed"}
    validated, reason = _runtime_attestation_fields(runtime_attestation)
    if validated is None:
        return None, {"runtimeIdentityFailure": str(reason)}
    return validated, {}


def shard_file_set_cid(files: Sequence[str]) -> str:
    return _blake3_512("\n".join(sorted(files)).encode("utf-8"))


def _canonical_key_manifest(keys: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = [dict(key) for key in keys]
    return sorted(
        rows,
        key=lambda row: json.dumps(
            row, sort_keys=True, separators=(",", ":"), default=str
        ),
    )


def key_manifest_cid(keys: Sequence[Mapping[str, Any]]) -> str:
    """CID over the canonical members, never over a count alone."""
    return canonical_cid({"keys": _canonical_key_manifest(keys)})


def _render_key(key: Mapping[str, Any]) -> str:
    return json.dumps(dict(key), sort_keys=True, separators=(",", ":"), default=str)


def _key_diff(
    input_keys: Sequence[Mapping[str, Any]],
    output_keys: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    inputs = Counter(_render_key(key) for key in input_keys)
    outputs = Counter(_render_key(key) for key in output_keys)
    representatives = {
        _render_key(key): dict(key) for key in [*input_keys, *output_keys]
    }
    missing = [
        representatives[rendered]
        for rendered, multiplicity in sorted((inputs - outputs).items())
        for _ in range(multiplicity)
    ]
    extra = [
        representatives[rendered]
        for rendered, multiplicity in sorted((outputs - inputs).items())
        for _ in range(multiplicity)
    ]
    duplicate = [
        {
            "side": side,
            "key": representatives[rendered],
            "multiplicity": multiplicity,
        }
        for side, counter in (("input", inputs), ("output", outputs))
        for rendered, multiplicity in sorted(counter.items())
        if multiplicity > 1
    ]
    return missing, extra, duplicate


def key_edge_witness(
    *,
    stage_id: str,
    input_keys: Sequence[Mapping[str, Any]],
    output_keys: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Producer witness shape.  Compose recomputes every diagnostic."""
    inputs = _canonical_key_manifest(input_keys)
    outputs = _canonical_key_manifest(output_keys)
    missing, extra, duplicate = _key_diff(inputs, outputs)
    return {
        "stageId": stage_id,
        "inputKeyManifest": inputs,
        "inputKeyCount": len(inputs),
        "inputKeyCid": key_manifest_cid(inputs),
        "outputKeyManifest": outputs,
        "outputKeyCount": len(outputs),
        "outputKeyCid": key_manifest_cid(outputs),
        "missingKeys": missing,
        "extraKeys": extra,
        "duplicateKeys": duplicate,
    }


def _source_file_cid(path: Path) -> str:
    return _blake3_512(path.read_bytes())


def _loaded_stage_map() -> tuple[dict[str, dict[str, str]], list[dict[str, Any]]]:
    here = Path(__file__).resolve().parent
    specs = {
        STAGE_ENUMERATE_FILE_TERMINAL: (
            "recensus_enumerate_consumer.measure_file_via_enumerate",
            here / "recensus_enumerate_consumer.py",
        ),
        STAGE_WITH_TALLY_PARTITION: (
            "control_effect_recensus._tally_cm_resolutions->_with_census_partition",
            here / "control_effect_recensus.py",
        ),
        STAGE_TERMINAL_AGGREGATE_SEAL: (
            "compose_control_effect_board.aggregate_terminal_rows->seal_board_from_aggregate",
            Path(__file__).resolve(),
        ),
    }
    stage_map: dict[str, dict[str, str]] = {}
    failures: list[dict[str, Any]] = []
    for stage_id, (qualname, path) in specs.items():
        try:
            source_cid = _source_file_cid(path)
        except OSError as error:
            failures.append(
                {
                    "stageId": stage_id,
                    "reason": "loaded stage source unavailable",
                    "observedEventType": f"{type(error).__module__}.{type(error).__qualname__}",
                    "message": str(error),
                }
            )
            continue
        stage_map[stage_id] = {
            "moduleQualname": qualname,
            "sourceFileCid": source_cid,
        }
    return stage_map, failures


def _read_key_manifest(
    witness: Mapping[str, Any], field: str, *, edge_id: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw = witness.get(field)
    if not isinstance(raw, list):
        return [], [{"edgeId": edge_id, "reason": f"{field} absent or not a list"}]
    keys: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for index, key in enumerate(raw):
        if not isinstance(key, dict) or not isinstance(key.get("sourceCid"), str):
            failures.append(
                {
                    "edgeId": edge_id,
                    "reason": f"{field}[{index}] lacks content-pinned sourceCid",
                    "key": key,
                }
            )
            continue
        keys.append(dict(key))
    return keys, failures


def _validate_edge_witness(
    edge_id: str,
    witness: object,
    *,
    expected_stage_id: str,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if not isinstance(witness, dict):
        return None, [{"edgeId": edge_id, "reason": "edge witness absent"}]
    failures: list[dict[str, Any]] = []
    if witness.get("stageId") != expected_stage_id:
        failures.append(
            {
                "edgeId": edge_id,
                "reason": (
                    f"stageId absent or wrong: got={witness.get('stageId')!r} "
                    f"want={expected_stage_id!r}"
                ),
            }
        )
    inputs, input_failures = _read_key_manifest(
        witness, "inputKeyManifest", edge_id=edge_id
    )
    outputs, output_failures = _read_key_manifest(
        witness, "outputKeyManifest", edge_id=edge_id
    )
    failures.extend(input_failures)
    failures.extend(output_failures)
    attested = key_edge_witness(
        stage_id=expected_stage_id,
        input_keys=inputs,
        output_keys=outputs,
    )
    for field in (
        "inputKeyCount",
        "inputKeyCid",
        "outputKeyCount",
        "outputKeyCid",
    ):
        if witness.get(field) != attested[field]:
            failures.append(
                {
                    "edgeId": edge_id,
                    "reason": f"{field} mismatch",
                    "claimed": witness.get(field),
                    "observed": attested[field],
                }
            )
    if attested["missingKeys"] or attested["extraKeys"] or attested["duplicateKeys"]:
        failures.append(
            {"edgeId": edge_id, "reason": "key conservation failed", **attested}
        )
    return attested, failures


def _terminal_row_failures(file: str, row: Mapping[str, Any]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    if row.get("instrumentFailure"):
        raw = row.get("instrumentFailure")
        failures.append(
            dict(raw)
            if isinstance(raw, dict)
            else {"file": file, "reason": "instrumentFailure", "message": str(raw)}
        )
        return failures
    input_key = row.get("inputKey")
    if not isinstance(input_key, dict) or not isinstance(
        input_key.get("sourceCid"), str
    ):
        failures.append({"file": file, "reason": "inputKey lacks sourceCid"})
    elif "functionKeyManifest" in input_key:
        function_keys = input_key.get("functionKeyManifest")
        if not isinstance(function_keys, list):
            failures.append(
                {"file": file, "reason": "functionKeyManifest is not a list"}
            )
        else:
            if len(function_keys) != int(row.get("functionsTotal") or 0):
                failures.append(
                    {
                        "file": file,
                        "reason": "function key attendance disagrees with functionsTotal",
                        "functionKeyCount": len(function_keys),
                        "functionsTotal": int(row.get("functionsTotal") or 0),
                    }
                )
            observed_function_cid = key_manifest_cid(function_keys)
            if input_key.get("functionKeyCid") != observed_function_cid:
                failures.append(
                    {
                        "file": file,
                        "reason": "functionKeyCid mismatch",
                        "claimed": input_key.get("functionKeyCid"),
                        "observed": observed_function_cid,
                    }
                )
    expected_row_id = (
        canonical_cid({"inputKey": input_key}) if isinstance(input_key, dict) else None
    )
    if row.get("rowId") != expected_row_id:
        failures.append(
            {
                "file": file,
                "reason": "stable rowId mismatch",
                "claimed": row.get("rowId"),
                "observed": expected_row_id,
            }
        )
    if row.get("stageId") != STAGE_ENUMERATE_FILE_TERMINAL:
        failures.append({"file": file, "reason": "terminal stageId absent or wrong"})
    observed_type = row.get("observedEventType")
    if not isinstance(observed_type, str) or "." not in observed_type:
        failures.append(
            {"file": file, "reason": "observedEventType is not fully qualified"}
        )
    terminal_kind = row.get("terminalKind")
    if terminal_kind not in _TERMINAL_KINDS:
        failures.append(
            {"file": file, "reason": f"terminalKind is not closed: {terminal_kind!r}"}
        )
        return failures
    category = row.get("category")
    expected_category = "completed" if terminal_kind == "constructed" else "panic"
    if category != expected_category:
        failures.append(
            {
                "file": file,
                "reason": "legacy category disagrees with terminalKind",
                "category": category,
                "terminalKind": terminal_kind,
            }
        )
    chain_length = row.get("observed_chain_length")
    blocking_count = row.get("blocking_terminal_count")
    if not isinstance(chain_length, int) or chain_length < 1:
        failures.append({"file": file, "reason": "observed_chain_length absent"})
    if blocking_count != (1 if terminal_kind == "construction-panic" else 0):
        failures.append({"file": file, "reason": "blocking_terminal_count disagrees"})
    if row.get("final_terminal") != terminal_kind:
        failures.append({"file": file, "reason": "final_terminal disagrees"})
    if terminal_kind == "construction-panic":
        if observed_type != _CONSTRUCTION_PANIC_TYPE and not str(
            observed_type
        ).startswith(_SOURCE_PANIC_PREFIX):
            failures.append(
                {
                    "file": file,
                    "reason": "ordinary exception relabelled as construction-panic",
                    "observedEventType": observed_type,
                }
            )
        panic = row.get("panic")
        required = {
            "owner",
            "coordinate",
            "observed",
            "requested",
            "fix",
            "entrance",
            "construction_trace",
        }
        if not isinstance(panic, dict) or not required.issubset(panic):
            failures.append(
                {
                    "file": file,
                    "reason": "non-authenticated ConstructionPanic payload",
                    "missing": (
                        sorted(required - set(panic or {}))
                        if isinstance(panic, dict)
                        else sorted(required)
                    ),
                }
            )
        elif not isinstance(panic.get("construction_trace"), list):
            failures.append(
                {"file": file, "reason": "construction_trace is not ordered"}
            )
        elif chain_length != len(panic["construction_trace"]):
            failures.append(
                {"file": file, "reason": "observed_chain_length disagrees with trace"}
            )
    return failures


def attest_frontier_rows(
    measured_rows: Sequence[tuple[str, Mapping[str, Any]]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Authenticate V1 terminal membership at the sole compose door."""
    failures: list[dict[str, Any]] = []
    stage_map, stage_failures = _loaded_stage_map()
    failures.extend(stage_failures)
    combined_inputs: dict[str, list[dict[str, Any]]] = {
        EDGE_ENUMERATE_FILE: [],
        EDGE_WITH_PARTITION: [],
    }
    combined_outputs: dict[str, list[dict[str, Any]]] = {
        EDGE_ENUMERATE_FILE: [],
        EDGE_WITH_PARTITION: [],
    }
    terminal_inputs: list[dict[str, Any]] = []
    constructed: list[dict[str, Any]] = []
    panicked: list[dict[str, Any]] = []
    terminal_rows: list[dict[str, Any]] = []
    expected_stages = {
        EDGE_ENUMERATE_FILE: STAGE_ENUMERATE_FILE_TERMINAL,
        EDGE_WITH_PARTITION: STAGE_WITH_TALLY_PARTITION,
    }
    for file, raw in measured_rows:
        row = dict(raw)
        failures.extend(_terminal_row_failures(file, row))
        key = row.get("inputKey")
        if isinstance(key, dict) and isinstance(key.get("sourceCid"), str):
            terminal_inputs.append(dict(key))
            if row.get("terminalKind") == "constructed":
                constructed.append(dict(key))
            elif row.get("terminalKind") == "construction-panic":
                panicked.append(dict(key))
        terminal_rows.append(
            {
                field: row.get(field)
                for field in (
                    "rowId",
                    "inputKey",
                    "stageId",
                    "observedEventType",
                    "terminalKind",
                    "observed_chain_length",
                    "blocking_terminal_count",
                    "final_terminal",
                    "panic",
                )
                if field in row
            }
        )
        edge_witnesses = row.get("edgeWitnesses")
        if not isinstance(edge_witnesses, dict):
            failures.append({"file": file, "reason": "edgeWitnesses absent"})
            continue
        for edge_id, stage_id in expected_stages.items():
            attested, edge_failures = _validate_edge_witness(
                edge_id,
                edge_witnesses.get(edge_id),
                expected_stage_id=stage_id,
            )
            failures.extend({"file": file, **failure} for failure in edge_failures)
            if attested is not None:
                combined_inputs[edge_id].extend(attested["inputKeyManifest"])
                combined_outputs[edge_id].extend(attested["outputKeyManifest"])

    edges: dict[str, dict[str, Any]] = {}
    for edge_id, stage_id in expected_stages.items():
        edge = key_edge_witness(
            stage_id=stage_id,
            input_keys=combined_inputs[edge_id],
            output_keys=combined_outputs[edge_id],
        )
        edges[edge_id] = edge
        if edge["missingKeys"] or edge["extraKeys"] or edge["duplicateKeys"]:
            failures.append(
                {
                    "edgeId": edge_id,
                    "reason": "composed key conservation failed",
                    **edge,
                }
            )

    terminal_edge = key_edge_witness(
        stage_id=STAGE_TERMINAL_AGGREGATE_SEAL,
        input_keys=terminal_inputs,
        output_keys=[*constructed, *panicked],
    )
    edges[EDGE_TERMINAL_SEAL] = terminal_edge
    if (
        terminal_edge["missingKeys"]
        or terminal_edge["extraKeys"]
        or terminal_edge["duplicateKeys"]
    ):
        failures.append(
            {
                "edgeId": EDGE_TERMINAL_SEAL,
                "reason": "final disjoint union failed",
                **terminal_edge,
            }
        )
    constructed_rendered = {_render_key(key) for key in constructed}
    panicked_rendered = {_render_key(key) for key in panicked}
    overlap = sorted(constructed_rendered & panicked_rendered)
    if overlap:
        failures.append(
            {
                "edgeId": EDGE_TERMINAL_SEAL,
                "reason": "constructed and construction-panic manifests overlap",
                "overlapKeys": [json.loads(row) for row in overlap],
            }
        )
    attestation = {
        "schema": "control-effect-frontier-attestation/v1",
        "stageMap": stage_map,
        "edges": edges,
        "terminalRows": terminal_rows,
        "constructedKeyManifest": _canonical_key_manifest(constructed),
        "constructedKeyCid": key_manifest_cid(constructed),
        "constructionPanicKeyManifest": _canonical_key_manifest(panicked),
        "constructionPanicKeyCid": key_manifest_cid(panicked),
        "instrumentFailures": list(failures),
        "terminalConvention": dict(_TERMINAL_CONVENTION),
        "finalSeal": {
            "inputKeyManifest": _canonical_key_manifest(terminal_inputs),
            "inputKeyCid": key_manifest_cid(terminal_inputs),
            "constructedAndPanicDisjoint": not overlap,
            "conserves": not terminal_edge["missingKeys"]
            and not terminal_edge["extraKeys"]
            and not terminal_edge["duplicateKeys"]
            and not overlap,
        },
    }
    return attestation, failures


def _frontier_manifests_for_common_seal(
    frontier_attestation: Mapping[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Project untrusted final-edge members; the callback validates them."""
    if not isinstance(frontier_attestation, Mapping):
        return [], []
    edges = frontier_attestation.get("edges")
    if not isinstance(edges, Mapping):
        return [], []
    edge = edges.get(EDGE_TERMINAL_SEAL)
    if not isinstance(edge, Mapping):
        return [], []
    inputs = edge.get("inputKeyManifest")
    outputs = edge.get("outputKeyManifest")
    return (
        (
            [dict(row) for row in inputs if isinstance(row, Mapping)]
            if isinstance(inputs, list)
            else []
        ),
        (
            [dict(row) for row in outputs if isinstance(row, Mapping)]
            if isinstance(outputs, list)
            else []
        ),
    )


def _validate_frontier_attestation_for_common_seal(
    frontier_attestation: Mapping[str, Any] | None,
    *,
    expected_panic_count: int,
) -> None:
    """Schema-local equality check executed by the universal mint door."""
    if not isinstance(frontier_attestation, Mapping):
        raise ValueError("frontier attestation absent")
    if frontier_attestation.get("schema") != "control-effect-frontier-attestation/v1":
        raise ValueError("frontier attestation schema is unsupported")
    if frontier_attestation.get("instrumentFailures") != []:
        raise ValueError("frontier attestation carries instrument failures")

    stage_map = frontier_attestation.get("stageMap")
    stage = (
        stage_map.get(STAGE_TERMINAL_AGGREGATE_SEAL)
        if isinstance(stage_map, Mapping)
        else None
    )
    expected_source_cid = _source_file_cid(Path(__file__).resolve())
    if (
        not isinstance(stage, Mapping)
        or stage.get("sourceFileCid") != expected_source_cid
    ):
        raise ValueError("compose validator stage source CID is absent or stale")

    edges = frontier_attestation.get("edges")
    if not isinstance(edges, Mapping):
        raise ValueError("frontier attestation edges absent")
    expected_edges = {
        EDGE_ENUMERATE_FILE: STAGE_ENUMERATE_FILE_TERMINAL,
        EDGE_WITH_PARTITION: STAGE_WITH_TALLY_PARTITION,
        EDGE_TERMINAL_SEAL: STAGE_TERMINAL_AGGREGATE_SEAL,
    }
    validated: dict[str, dict[str, Any]] = {}
    for edge_id, stage_id in expected_edges.items():
        attested, failures = _validate_edge_witness(
            edge_id,
            edges.get(edge_id),
            expected_stage_id=stage_id,
        )
        if failures or attested is None:
            raise ValueError(
                f"frontier edge {edge_id} failed common-seal validation: {failures}"
            )
        validated[edge_id] = attested

    terminal = validated[EDGE_TERMINAL_SEAL]
    constructed = frontier_attestation.get("constructedKeyManifest")
    panicked = frontier_attestation.get("constructionPanicKeyManifest")
    if not isinstance(constructed, list) or not isinstance(panicked, list):
        raise ValueError("frontier terminal partition manifests absent")
    if len(panicked) != expected_panic_count:
        raise ValueError(
            "aggregate panic magnitude disagrees with authenticated panic keys: "
            f"aggregate={expected_panic_count} attested={len(panicked)}"
        )
    final_edge = key_edge_witness(
        stage_id=STAGE_TERMINAL_AGGREGATE_SEAL,
        input_keys=terminal["inputKeyManifest"],
        output_keys=[*constructed, *panicked],
    )
    if (
        final_edge["missingKeys"]
        or final_edge["extraKeys"]
        or final_edge["duplicateKeys"]
    ):
        raise ValueError("frontier final disjoint union does not conserve")
    overlap = {_render_key(row) for row in constructed if isinstance(row, Mapping)} & {
        _render_key(row) for row in panicked if isinstance(row, Mapping)
    }
    if overlap:
        raise ValueError("frontier constructed and panic manifests overlap")
    final_seal = frontier_attestation.get("finalSeal")
    if (
        not isinstance(final_seal, Mapping)
        or final_seal.get("conserves") is not True
        or final_seal.get("constructedAndPanicDisjoint") is not True
        or final_seal.get("inputKeyCid") != terminal["inputKeyCid"]
    ):
        raise ValueError("frontier final seal testimony is absent or stale")


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
    runtime_attestation: Mapping[str, Any] | None | object = _RUNTIME_AUTO,
) -> dict[str, Any]:
    """Mint a shard partial. Never includes R_construction_panics top-level."""
    runtime, runtime_failure = _resolve_runtime_argument(runtime_attestation)
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
        if not isinstance(raw, dict)
        or (not raw.get("category") and not raw.get("instrumentFailure"))
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
            else (r or {}).get("functionsTotal") or 0
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

    if runtime is None:
        status = "unmeasured"
        unmeasured_reason = str(
            runtime_failure.get("runtimeIdentityFailure")
            or runtime_failure.get("runtimeIdentityMismatch")
            or "runtimeIdentity/v1 refused"
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
        "terminalRows": [{"file": f, "result": r} for f, r in terminals],
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
        "d3ResidencyExposure": aggregate_d3_residency_exposure(
            terminals,
            enrolled_files=assigned,
        ),
        "status": status,
        "measured": measured,
        "unmeasuredReason": unmeasured_reason,
    }
    if runtime is not None:
        body.update(runtime)
    else:
        body.update(runtime_failure)
    # Forbidden fields must never appear:
    assert "R_construction_panics" not in body
    body["partialCid"] = canonical_cid(
        {k: v for k, v in body.items() if k != "partialCid"}
    )
    return body


def aggregate_d3_residency_exposure(
    measured_rows: Sequence[tuple[str, Mapping[str, Any]]],
    *,
    enrolled_files: Sequence[str],
) -> dict[str, Any]:
    """Count D3 residency reach without changing construction behavior.

    Raw file coordinates stay beside every count.  Missing observation is not a
    miss: it is either a pre-D3 terminal or an unconfirmed audit open, and the
    two remain distinct so a partial run cannot manufacture agreement.
    """
    enrolled = list(enrolled_files)
    by_file = {file: dict(raw) for file, raw in measured_rows}
    reached: list[str] = []
    present_before: list[str] = []
    absent_before: list[str] = []
    hit: list[str] = []
    miss: list[str] = []
    audit_observed: list[str] = []
    audit_unconfirmed: list[str] = []
    presence_confirmed: list[str] = []
    presence_mismatch: list[str] = []
    reporter_seated: list[str] = []
    reporter_unseated: list[str] = []
    collector_registered: list[str] = []
    collector_empty: list[str] = []

    for file in enrolled:
        observation = by_file.get(file, {}).get("d3Residency")
        if (
            not isinstance(observation, Mapping)
            or observation.get("reached") is not True
        ):
            continue
        reached.append(file)
        before = observation.get("presentBeforeDemand")
        at_open = observation.get("presentAtAuditOpen")
        reused = observation.get("auditOpenReusedResident")
        if before is True:
            present_before.append(file)
        elif before is False:
            absent_before.append(file)
        if isinstance(at_open, bool):
            audit_observed.append(file)
        else:
            audit_unconfirmed.append(file)
        if reused is True:
            hit.append(file)
        elif reused is False and at_open is False:
            miss.append(file)
        if isinstance(before, bool) and isinstance(at_open, bool):
            if before == at_open:
                presence_confirmed.append(file)
            else:
                presence_mismatch.append(file)
        seated = observation.get("rootReporterSeatedAtAuditOpen")
        if seated is True:
            reporter_seated.append(file)
        elif seated is False:
            reporter_unseated.append(file)
        registered = observation.get("collectorRegisteredAtAuditExit")
        if registered is True:
            collector_registered.append(file)
        elif registered is False:
            collector_empty.append(file)

    reached_set = set(reached)
    not_reached = [file for file in enrolled if file not in reached_set]
    return {
        "filesEnrolled": len(enrolled),
        "d3Reached": len(reached),
        "d3NotReached": len(not_reached),
        "presentBeforeDemand": len(present_before),
        "absentBeforeDemand": len(absent_before),
        "auditOpenHit": len(hit),
        "auditOpenMiss": len(miss),
        "auditOpenObserved": len(audit_observed),
        "auditOpenUnconfirmed": len(audit_unconfirmed),
        "presenceConfirmed": len(presence_confirmed),
        "presenceMismatch": len(presence_mismatch),
        "reporterSeated": len(reporter_seated),
        "reporterUnseated": len(reporter_unseated),
        "collectorRegistered": len(collector_registered),
        "collectorEmpty": len(collector_empty),
        "hitFiles": hit,
        "missFiles": miss,
        "notReachedFiles": not_reached,
        "auditOpenUnconfirmedFiles": audit_unconfirmed,
        "presenceMismatchFiles": presence_mismatch,
        "reporterUnseatedFiles": reporter_unseated,
        "collectorEmptyFiles": collector_empty,
    }


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
        if not isinstance(raw, dict)
        or (not raw.get("category") and not raw.get("instrumentFailure"))
    )

    families: Counter[str] = Counter()
    desugar_families: Counter[str] = Counter()
    desugar_categories: Counter[str] = Counter()
    desugar_by_category_owner: Counter[str] = Counter()
    backend_defects: Counter[str] = Counter()
    cm_resolutions: Counter[str] = Counter()
    with_resolution_rows: list[dict[str, Any]] = []
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
    files_panicked = 0
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
        with_resolution_rows.extend(row.get("withResolutionRows") or [])
        unrecognized_cm_kinds.update(row.get("unrecognizedCmResolutionKinds") or {})
        ast_sites.update(row.get("astSites") or {})
        desugar_construction_panics.extend(row.get("desugarConstructionPanics") or [])
        desugar_defects.extend(row.get("desugarDefects") or [])
        desugar_designed_gaps.extend(row.get("desugarDesignedGaps") or [])

        if category == "completed":
            files_completed += 1
        else:
            files_panicked += 1
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
        "with_resolution_rows": with_resolution_rows,
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
        "files_panicked": files_panicked,
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
        "d3_residency_exposure": aggregate_d3_residency_exposure(
            measured_rows,
            enrolled_files=file_names,
        ),
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
    frontier_attestation: Mapping[str, Any] | None = None,
    runtime_attestation: Mapping[str, Any] | None | object = _RUNTIME_AUTO,
) -> dict[str, Any]:
    """Mint the sealed authoritative board body. Sole mint of the class."""
    runtime, runtime_failure = _resolve_runtime_argument(runtime_attestation)
    if runtime is None:
        return unmeasured_envelope(
            plan=plan,
            missing_shards=["runtime"],
            unmeasured_reasons={
                "runtime": str(
                    runtime_failure.get("runtimeIdentityFailure")
                    or runtime_failure.get("runtimeIdentityMismatch")
                    or "runtimeIdentity/v1 refused"
                )
            },
            measured_commit=measured_commit,
            runtime_failure=runtime_failure,
        )
    file_names = list(agg["enrolled_files"])
    families = Counter(agg["families"])
    backend_defects = Counter(agg["backend_defects"])
    construction_panics = list(agg["construction_panics"])
    defects = list(agg["defects"])
    # One meaning each — never bag-sum-as-the-residual.
    # Desugar: only panic count is residual. defects / typed-refusal / constructed-effect
    # were outcome KINDS (Exception vs SugarNotWritten vs Incomplete), not quantities
    # of unwritten work. Dropped as residual axes (T correction: two outcomes only).
    r_construction_panics = len(construction_panics)
    r_desugar_panics = len(agg["desugar_construction_panics"])
    r_backend = sum(backend_defects.values())
    cm = Counter(agg["cm_resolutions"])
    r_cm_constructed = int(cm.get("constructed", 0) + cm.get("derived-contract", 0))
    r_cm_unconstructed = int(cm.get("unconstructed", 0)) + sum(
        int(v) for k, v in cm.items() if str(k).startswith("gap:")
    )
    files_enrolled = len(file_names)
    files_terminal = int(agg["terminal_count"])
    files_completed = int(agg["files_completed"])
    files_panicked = int(
        agg.get("files_panicked") or max(0, files_terminal - files_completed)
    )
    files_missing = len(agg["missing_files"])

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
            "aggregateHash": aggregate_hash or (plan or {}).get("aggregateHash") or "",
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
        # Dual unit denominator — one name per meaning (see board-number-meanings.md).
        "denominator": {
            "files": {
                "enrolled": files_enrolled,
                "terminal": files_terminal,
                "completed": files_completed,
                "panicked": files_panicked,
                "missing": files_missing,
                "terminalRows": files_terminal,
                "corpusManifestCid": agg.get("manifest_cid"),
                "enrolledFiles": list(file_names),
                "missingFiles": list(agg["missing_files"]),
                "duplicateFiles": list(agg["duplicate_files"]),
                "malformedRows": list(agg["malformed_rows"]),
                "complete": bool(agg["files_complete"]),
            },
            "functions": dict(fn_fields["denominator_functions"]),
        },
        "filesEnrolled": files_enrolled,
        "filesTerminal": files_terminal,
        "filesCompleted": files_completed,
        "filesPanicked": files_panicked,
        "filesMissing": files_missing,
        "filesTotal": files_enrolled,
        "enrolledFiles": files_enrolled,
        "populationSize": files_enrolled,
        "functionsPopulation": fn_fields["functionsTotal"],
        "functionsEnumerated": fn_fields["functionsEnumerated"],
        "functionsUnaccounted": fn_fields["functionsUnaccounted"],
        "functionsConstructClean": fn_fields["functionsConstructClean"],
        "cleanRatioRefused": fn_fields["cleanRatioRefused"],
        "sealedFunctionFactCids": dict(fn_fields["sealedFactCids"]),
        "cleanRefuseReasons": list(agg.get("clean_refuse_reasons") or []),
        "functionsTotal": fn_fields["functionsTotal"],
        "constructionPanics": construction_panics,
        "R_construction_panics": r_construction_panics,
        "defects": defects,
        "R_defects": len(defects),
        "desugarConstructionPanics": list(agg["desugar_construction_panics"]),
        "R_desugar_construction_panics": r_desugar_panics,
        # desugarDefects / typed-refusal / constructed-effect NOT sealed as R_* —
        # those were kinds of outcome, not independent quantities of unwritten work.
        "cmResolutions": dict(sorted(cm.items(), key=lambda item: (-item[1], item[0]))),
        "R_cm_constructed": r_cm_constructed,
        "R_cm_unconstructed": r_cm_unconstructed,
        "R_cm_derived_contract": r_cm_constructed,
        "withCensus": with_census,
        "astSitePrevalence": dict(
            sorted(
                Counter(agg["ast_sites"]).items(),
                key=lambda item: (-item[1], item[0]),
            )
        ),
        "unresolvableDispatchTargets": list(agg["unresolvable_dispatch"]),
        "R_unresolvable_dispatch_targets": len(agg["unresolvable_dispatch"]),
        "R_backend_defects": r_backend,
        "backendDefects": dict(
            sorted(backend_defects.items(), key=lambda item: (-item[1], item[0]))
        ),
        "families": dict(
            sorted(families.items(), key=lambda item: (-item[1], item[0]))
        ),
        "boardNumberMeanings": {
            "files": "enrolled | terminal | completed | panicked | missing",
            "functions": "population | enumerated | clean (or clean refused)",
            "construction": "R_construction_panics = len(constructionPanics)",
            "desugar": "R_desugar_construction_panics only (constructed or panicked)",
            "cm": "R_cm_constructed | R_cm_unconstructed",
        },
        "d3ResidencyExposure": dict(agg["d3_residency_exposure"]),
        "elapsedSeconds": elapsed_seconds,
        "planCid": (plan or {}).get("planCid"),
        "perShardCids": dict(sorted((per_shard_cids or {}).items())),
        "composeSchema": COMPOSE_SCHEMA,
        **runtime,
    }
    if frontier_attestation is not None:
        body["frontierAttestation"] = dict(frontier_attestation)
        body["frontierWidth"] = len(
            frontier_attestation.get("constructionPanicKeyManifest") or []
        )
    if source_stamp is not None:
        body["sourceStamp"] = dict(source_stamp)
        # Host/load noise stays in sourceStamp; bodyCid excludes it.
    if compose_cid is not None:
        body["composeCid"] = compose_cid
    from sugar_lift_py_tests.conservation_mint import (
        ConservationFailure,
        seal_after_validation,
    )

    input_manifest, output_manifest = _frontier_manifests_for_common_seal(
        frontier_attestation
    )
    outcome = seal_after_validation(
        measured_payload=body,
        input_key_manifest=input_manifest,
        output_key_manifest=output_manifest,
        validator_stage_id=STAGE_TERMINAL_AGGREGATE_SEAL,
        validator_source_path=Path(__file__).resolve(),
        validate=lambda: _validate_frontier_attestation_for_common_seal(
            frontier_attestation,
            expected_panic_count=r_construction_panics,
        ),
    )
    if isinstance(outcome, ConservationFailure):
        failure_body = outcome.to_wire()
        failure_body.update(runtime)
        return failure_body
    body = outcome.to_wire()

    # Both seals are required: schema-local function facts and the universal
    # passed-conservation witness. Neither can substitute for the other.
    require_sealed_board_function_fields(body)
    # bodyCid over the sealed domain, including conservationWitness.
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
    instrument_failures: Sequence[Mapping[str, Any]] = (),
    d3_residency_exposure: Mapping[str, Any] | None = None,
    runtime_attestation: Mapping[str, Any] | None = None,
    runtime_failure: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Attendance testimony only. NEVER measurementClass=control-effect-recensus."""
    env: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": KIND_UNMEASURED,
        # measurementClass OMITTED — dual belt A
        "status": "unmeasured",
        "measured": False,
        "measuredCommit": measured_commit or (plan or {}).get("measuredCommit"),
        "planCid": (plan or {}).get("planCid"),
        "missingShards": list(missing_shards),
        "unmeasuredReasons": dict(unmeasured_reasons),
        "instrumentFailures": [dict(row) for row in instrument_failures],
        "denominator": {"complete": False},
    }
    if d3_residency_exposure is not None:
        env["d3ResidencyExposure"] = dict(d3_residency_exposure)
    if runtime_attestation is not None:
        env.update(dict(runtime_attestation))
    if runtime_failure is not None:
        env.update(dict(runtime_failure))
    assert "measurementClass" not in env
    assert "R_construction_panics" not in env
    assert "frontierWidth" not in env
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
    runtime_attestation: Mapping[str, Any] | None | object = _RUNTIME_AUTO,
) -> tuple[str, dict[str, Any]]:
    """Sole compose door. Returns (\"sealed\"|\"unmeasured\", body)."""
    runtime, runtime_failure = _resolve_runtime_argument(runtime_attestation)
    if runtime is None:
        return "unmeasured", unmeasured_envelope(
            plan=plan,
            missing_shards=["runtime"],
            unmeasured_reasons={
                "runtime": str(
                    runtime_failure.get("runtimeIdentityFailure")
                    or runtime_failure.get("runtimeIdentityMismatch")
                    or "runtimeIdentity/v1 refused"
                )
            },
            measured_commit=str(plan.get("measuredCommit") or ""),
            runtime_failure=runtime_failure,
        )
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

    first_partial_runtime_cid: str | None = None
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
        partial_runtime, partial_runtime_reason = _runtime_attestation_fields(p)
        if partial_runtime is None:
            missing.append(seat)
            reasons[seat] = str(partial_runtime_reason)
            continue
        if partial_runtime["requiredRuntime"] != runtime["requiredRuntime"]:
            missing.append(seat)
            reasons[seat] = (
                "requiredRuntime mismatches authenticated compose requirement: "
                f"partial={partial_runtime['requiredRuntime']} "
                f"compose={runtime['requiredRuntime']}"
            )
            continue
        partial_runtime_cid = str(partial_runtime["runtimeCid"])
        if (
            first_partial_runtime_cid is not None
            and partial_runtime_cid != first_partial_runtime_cid
        ):
            missing.append(seat)
            reasons[seat] = (
                "runtimeCid disagrees across shard partials: "
                f"first={first_partial_runtime_cid} current={partial_runtime_cid}"
            )
            continue
        if partial_runtime_cid != runtime["runtimeCid"]:
            missing.append(seat)
            reasons[seat] = (
                "runtimeCid mismatches authenticated compose runtime: "
                f"partial={partial_runtime_cid} compose={runtime['runtimeCid']}"
            )
            continue
        if first_partial_runtime_cid is None:
            first_partial_runtime_cid = partial_runtime_cid

    if missing:
        return "unmeasured", unmeasured_envelope(
            plan=plan,
            missing_shards=missing,
            unmeasured_reasons=reasons,
            measured_commit=str(plan.get("measuredCommit") or ""),
            runtime_attestation=runtime,
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
    d3_residency_exposure = aggregate_d3_residency_exposure(
        measured_rows,
        enrolled_files=enrolled,
    )
    frontier_attestation, instrument_failures = attest_frontier_rows(measured_rows)
    if instrument_failures:
        return "unmeasured", unmeasured_envelope(
            plan=plan,
            missing_shards=["compose"],
            unmeasured_reasons={
                "compose": "frontier attestation refused; see instrumentFailures"
            },
            measured_commit=str(plan.get("measuredCommit") or ""),
            instrument_failures=instrument_failures,
            d3_residency_exposure=d3_residency_exposure,
            runtime_attestation=runtime,
        )
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
            d3_residency_exposure=d3_residency_exposure,
            runtime_attestation=runtime,
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
            list(agg["with_resolution_rows"]),
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
        frontier_attestation=frontier_attestation,
        runtime_attestation=runtime,
    )
    if board.get("measurement") != "measured":
        failure = board.get("conservationFailure")
        return "unmeasured", unmeasured_envelope(
            plan=plan,
            missing_shards=["compose"],
            unmeasured_reasons={
                "compose": "common conservation mint refused the census board"
            },
            measured_commit=str(plan.get("measuredCommit") or ""),
            instrument_failures=(
                [failure]
                if isinstance(failure, Mapping)
                else [{"reason": "common conservation mint refused without diagnostic"}]
            ),
            d3_residency_exposure=d3_residency_exposure,
            runtime_attestation=runtime,
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
    runtime_attestation: Mapping[str, Any] | None | object = _RUNTIME_AUTO,
) -> tuple[str, dict[str, Any]]:
    """k=1 path: one full-bin partial + compose (serial observation, one seal door)."""
    runtime, runtime_failure = _resolve_runtime_argument(runtime_attestation)
    if runtime is None:
        return "unmeasured", unmeasured_envelope(
            plan=None,
            missing_shards=["runtime"],
            unmeasured_reasons={
                "runtime": str(
                    runtime_failure.get("runtimeIdentityFailure")
                    or runtime_failure.get("runtimeIdentityMismatch")
                    or "runtimeIdentity/v1 refused"
                )
            },
            measured_commit=measured_commit,
            runtime_failure=runtime_failure,
        )
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
        runtime_attestation=runtime,
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
        runtime_attestation=runtime,
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
    runtime, runtime_failure = resolve_executing_runtime_attestation()
    if runtime is None:
        body = unmeasured_envelope(
            plan=None,
            missing_shards=["runtime"],
            unmeasured_reasons={
                "runtime": str(
                    runtime_failure.get("runtimeIdentityFailure")
                    or runtime_failure.get("runtimeIdentityMismatch")
                    or "runtimeIdentity/v1 refused"
                )
            },
            runtime_failure=runtime_failure,
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return 1
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    partials: list[dict[str, Any]] = []
    for path in sorted(args.partials_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("kind") == KIND_PARTIAL:
            partials.append(data)
    status, body = compose_from_partials(plan, partials, runtime_attestation=runtime)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"COMPOSE status={status} out={args.out} "
        f"missing={body.get('missingShards')} bodyCid={body.get('bodyCid')}",
        flush=True,
    )
    return 0 if status == "sealed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
