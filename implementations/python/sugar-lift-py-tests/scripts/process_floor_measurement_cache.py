#!/usr/bin/env python3
"""Content-addressed cache for supervised process-floor terminal rows.

Ontology: a measurement over identical content is the same value. Recomputing
it is waste, not caution.

Key (everything that can change the answer — put it in, never omit):

    tip
    × corpusManifestCid
    × axis
    × fileContentCid
    × demandTableCid
    × fileTimeoutMs

Stored row carries the full key. A hit is accepted only when the stored key
equals the lookup key field-for-field (verifiable, not assumed).

Only deterministic process outcomes are stored:

    completed | typed-gap | bare-exception

timeout and native-crash are host-load / signal sensitive — never banked as
if they were pure content measurements. Cache MISS is indistinguishable from
having no cache: full honest lift.

Not the board.
"""

from __future__ import annotations

# Not the board.
SCOREBOARD_AUTHORITY = False

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "process-floor-terminal-cache-row-v1"
# Shared axis for the three process floors (native / bare / timeout): they
# classify the same supervised-enum FileTerminal; one CA body serves all three.
DEFAULT_AXIS = "supervised_enum_terminal"

# Host-sensitive categories are measured, never banked.
CACHEABLE_CATEGORIES = frozenset({"completed", "typed-gap", "bare-exception"})

_HEX = re.compile(r"^[0-9a-f]+$")


def _blake3_512(data: bytes) -> str:
    """Self-identifying content address; blake3 when present, else sha256."""
    try:
        import blake3

        digest = blake3.blake3(data).digest(length=64)
        return "blake3-512:" + digest.hex()
    except Exception:  # noqa: BLE001 — teeth/tests may lack the wheel
        return "sha256:" + hashlib.sha256(data).hexdigest()


def file_content_cid(path: Path) -> str:
    return _blake3_512(path.read_bytes())


def demand_table_cid(demand_table_path: Path | None) -> str:
    if demand_table_path is None:
        return "demand:local-derivation"
    return _blake3_512(Path(demand_table_path).read_bytes())


def resolve_measurement_tip() -> str:
    """Tip identity that can change the lift implementation."""
    for key in ("SUGAR_MEASUREMENT_TIP", "GITHUB_SHA"):
        value = os.environ.get(key)
        if value and value.strip():
            return value.strip()
    return "unpinned"


def resolve_cache_root() -> Path | None:
    """Durable store root, or None to disable the cache.

    Prefer explicit ``SUGAR_PROCESS_FLOOR_CACHE_DIR``. In GitHub Actions default
    to a workspace-local dir so the three process floors in one job share hits.
    """
    explicit = os.environ.get("SUGAR_PROCESS_FLOOR_CACHE_DIR")
    if explicit is not None:
        text = explicit.strip()
        if text in {"", "0", "off", "none", "disabled"}:
            return None
        return Path(text).expanduser().resolve()
    workspace = os.environ.get("GITHUB_WORKSPACE")
    if workspace:
        return Path(workspace).resolve() / ".cache" / "process-floor-terminals"
    return None


def corpus_manifest_cid_for_paths(root: Path, paths: list[Path]) -> str:
    """Content-address population by relative path + per-file content cid."""
    root = root.resolve()
    rows: list[dict[str, str]] = []
    for path in sorted(paths, key=lambda p: p.resolve().as_posix()):
        rel = path.resolve().relative_to(root).as_posix()
        rows.append({"path": rel, "contentCid": file_content_cid(path)})
    preimage = json.dumps(
        {"kind": "process-floor-corpus-manifest", "files": rows},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _blake3_512(preimage)


@dataclass(frozen=True)
class MeasurementKey:
    tip: str
    corpus_manifest_cid: str
    axis: str
    file_content_cid: str
    demand_table_cid: str
    file_timeout_ms: int

    def to_json(self) -> dict[str, object]:
        return {
            "tip": self.tip,
            "corpusManifestCid": self.corpus_manifest_cid,
            "axis": self.axis,
            "fileContentCid": self.file_content_cid,
            "demandTableCid": self.demand_table_cid,
            "fileTimeoutMs": self.file_timeout_ms,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "MeasurementKey":
        return cls(
            tip=str(data["tip"]),
            corpus_manifest_cid=str(data["corpusManifestCid"]),
            axis=str(data["axis"]),
            file_content_cid=str(data["fileContentCid"]),
            demand_table_cid=str(data["demandTableCid"]),
            file_timeout_ms=int(data["fileTimeoutMs"]),
        )

    def storage_id(self) -> str:
        """Path-safe content address of the key itself."""
        raw = json.dumps(self.to_json(), sort_keys=True, separators=(",", ":"))
        return _blake3_512(raw.encode("utf-8")).split(":", 1)[-1]


class CacheRefuse(ValueError):
    """Stored row is present but not a valid hit for this key."""


class ProcessFloorTerminalCache:
    """Filesystem shelf of verified terminal rows keyed by MeasurementKey."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _path_for(self, key: MeasurementKey) -> Path:
        sid = key.storage_id()
        return self.root / key.axis / key.tip / sid[:2] / f"{sid}.json"

    def lookup(self, key: MeasurementKey) -> dict[str, Any] | None:
        """Return terminal payload if a verified hit exists; else None (miss).

        Corrupted / key-mismatched rows raise CacheRefuse so callers never
        treat garbage as a hit.
        """
        path = self._path_for(key)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise CacheRefuse(f"unreadable cache row {path}: {error}") from error
        if not isinstance(data, dict) or data.get("schema") != SCHEMA:
            raise CacheRefuse(f"invalid schema in {path}")
        try:
            stored_key = MeasurementKey.from_json(data["key"])
        except (KeyError, TypeError, ValueError) as error:
            raise CacheRefuse(f"cache row missing key in {path}: {error}") from error
        if stored_key != key:
            raise CacheRefuse(
                f"cache key mismatch in {path}: stored={stored_key.to_json()!r} "
                f"lookup={key.to_json()!r}"
            )
        terminal = data.get("terminal")
        if not isinstance(terminal, dict):
            raise CacheRefuse(f"cache row missing terminal in {path}")
        category = str(terminal.get("category") or "")
        if category not in CACHEABLE_CATEGORIES:
            raise CacheRefuse(
                f"refusing non-cacheable category {category!r} in {path}"
            )
        return dict(terminal)

    def store(self, key: MeasurementKey, terminal: Mapping[str, Any]) -> Path | None:
        """Persist a completed measurement. Returns path, or None if not cacheable."""
        category = str(terminal.get("category") or "")
        if category not in CACHEABLE_CATEGORIES:
            return None
        row = {
            "schema": SCHEMA,
            "key": key.to_json(),
            "terminal": dict(terminal),
        }
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = (
            json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            + "\n"
        )
        # Atomic replace so readers never see a torn write.
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(path)
        return path


def terminal_to_payload(
    *,
    file: str,
    category: str,
    returncode: int | None,
    signal_name: str | None,
    stderr_tail: str,
    terminal: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Serialize FileTerminal fields for the shelf (no worker_restarts — ephemeral)."""
    return {
        "file": file,
        "category": category,
        "returncode": returncode,
        "signal_name": signal_name,
        "stderr_tail": stderr_tail,
        "terminal": dict(terminal) if isinstance(terminal, Mapping) else None,
    }


def payload_to_file_terminal(payload: Mapping[str, Any], *, worker_restarts: int = 0):
    """Rehydrate FileTerminal from a verified cache payload."""
    # Local import avoids circular import at module load.
    from _supervised_enum_supervisor import FileTerminal

    term = payload.get("terminal")
    return FileTerminal(
        file=str(payload["file"]),
        category=str(payload["category"]),
        returncode=payload.get("returncode"),
        signal_name=payload.get("signal_name"),
        stderr_tail=str(payload.get("stderr_tail") or ""),
        terminal=dict(term) if isinstance(term, Mapping) else None,
        worker_restarts=worker_restarts,
    )
