from __future__ import annotations

import json
import re
from typing import Optional

from .lift_target import LiftTarget
from .panic_record import PanicKind, PanicRecord

_FIELD = re.compile(
    r"(owner|blame|observed|requested|fix)=([^=]+?)(?=\s(?:owner|blame|observed|requested|fix)=|$)"
)


def extract_panic_records(
    target: LiftTarget, stdout: str, stderr: str
) -> list[PanicRecord]:
    records: list[PanicRecord] = []
    for line in (stdout + "\n" + stderr).splitlines():
        rpc_records = _records_from_wrapped_rpc_error(target, line)
        if rpc_records:
            records.extend(rpc_records)
            continue
        line = _panic_segment(line)
        kind = _panic_kind(line)
        if kind is None:
            continue
        fields = {key: value.strip() for key, value in _FIELD.findall(line)}
        records.append(
            PanicRecord(
                target=target.name,
                kind=kind,
                owner=fields.get("owner", "unknown"),
                blame=fields.get("blame", "unknown"),
                observed=fields.get("observed", "unknown"),
                requested=fields.get("requested", "unknown"),
                fix=fields.get("fix", "write the missing sugar or floor"),
                message=line,
            )
        )
    return records


def _records_from_wrapped_rpc_error(target: LiftTarget, line: str) -> list[PanicRecord]:
    marker = "lift plugin returned error: "
    if marker not in line:
        return []
    payload = _json_object_prefix(line.split(marker, 1)[1].strip())
    if payload is None:
        return []
    try:
        error = json.loads(payload)
    except json.JSONDecodeError:
        return []
    data = error.get("data")
    if not isinstance(data, dict):
        return []
    gaps = data.get("auditOnlyGaps")
    if isinstance(gaps, list):
        return [_record_from_gap(target, gap) for gap in gaps if isinstance(gap, dict)]
    info = data.get("info")
    message = error.get("message")
    if isinstance(info, dict) and isinstance(message, str):
        kind = _panic_kind(message)
        if kind is None:
            return []
        return [_record_from_fields(target, kind, info, message)]
    return []


def _json_object_prefix(payload: str) -> Optional[str]:
    start = payload.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(payload)):
        char = payload[idx]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return payload[start : idx + 1]
            if depth < 0:
                return None
    return None


def _record_from_gap(target: LiftTarget, gap: dict) -> PanicRecord:
    message = str(gap.get("message", ""))
    fields = gap.get("gap")
    if not isinstance(fields, dict):
        fields = {key: value.strip() for key, value in _FIELD.findall(message)}
    return _record_from_fields(
        target, _panic_kind(message) or "unexpected", fields, message
    )


def _record_from_fields(
    target: LiftTarget,
    kind: PanicKind,
    fields: dict,
    message: str,
) -> PanicRecord:
    return PanicRecord(
        target=target.name,
        kind=kind,
        owner=str(fields.get("owner", "unknown")),
        blame=str(fields.get("blame", "unknown")),
        observed=str(fields.get("observed", "unknown")),
        requested=str(fields.get("requested", "unknown")),
        fix=str(fields.get("fix", "write the missing sugar or floor")),
        message=message,
    )


def _panic_segment(line: str) -> str:
    starts = [
        idx
        for prefix in (
            "write more Sugar for this AST",
            "write more Floor for this AST",
            "write more Floor for this Construction",
            "write more Sugar for ",
            "write more Floor for ",
        )
        if (idx := line.find(prefix)) >= 0
    ]
    if not starts:
        return line
    return line[min(starts) :]


def _panic_kind(line: str) -> Optional[PanicKind]:
    if line.startswith("write more Sugar for "):
        return "sugar"
    if line.startswith("write more Floor for "):
        return "floor"
    if "panicked" in line and "write more " not in line:
        return "unexpected"
    return None
