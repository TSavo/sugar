from __future__ import annotations

import re
from typing import Optional

from .lift_target import LiftTarget
from .panic_record import PanicKind, PanicRecord


_FIELD = re.compile(r"(owner|blame|observed|requested|fix)=([^=]+?)(?=\s(?:owner|blame|observed|requested|fix)=|$)")


def extract_panic_records(target: LiftTarget, stdout: str, stderr: str) -> list[PanicRecord]:
    records: list[PanicRecord] = []
    for line in (stdout + "\n" + stderr).splitlines():
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


def _panic_kind(line: str) -> Optional[PanicKind]:
    if line.startswith("write more Sugar for this AST"):
        return "sugar"
    if line.startswith("write more Floor for this AST") or line.startswith("write more Floor for this construction"):
        return "floor"
    if "panicked" in line and "write more " not in line:
        return "unexpected"
    return None
