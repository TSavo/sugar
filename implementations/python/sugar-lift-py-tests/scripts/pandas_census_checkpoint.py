"""Durable, manifest-bound checkpoints for pandas corpus floors."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence, TypeVar

from pandas_floor_summary import corpus_cid


SCHEMA = "pandas-census-checkpoint-row-v1"


class CheckpointError(ValueError):
    """The durable journal does not conserve the declared corpus."""


class Checkpoint:
    def __init__(self, *, floor: str, files: Sequence[str], path: Path) -> None:
        ordered = tuple(sorted(str(file) for file in files))
        if not ordered:
            raise CheckpointError("checkpoint requires a non-empty corpus manifest")
        if len(set(ordered)) != len(ordered):
            raise CheckpointError("corpus manifest contains duplicate files")
        self.floor = floor
        self.files = ordered
        self.manifest_cid = corpus_cid(ordered)
        self.path = path
        self._by_file: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        raw = self.path.read_bytes()
        if raw and not raw.endswith(b"\n"):
            # A process can die after beginning the one in-flight append. Only
            # that torn tail is discarded; every newline-terminated row stays.
            end = raw.rfind(b"\n") + 1
            with self.path.open("r+b") as stream:
                stream.truncate(end)
                stream.flush()
                os.fsync(stream.fileno())
            raw = raw[:end]
        for line_number, encoded in enumerate(raw.splitlines(), start=1):
            try:
                row = json.loads(encoded)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise CheckpointError(
                    f"malformed checkpoint row at line {line_number}"
                ) from error
            self._validate_row(row, line_number=line_number)
            file = str(row["file"])
            if file in self._by_file:
                raise CheckpointError(f"duplicate checkpoint row for {file}")
            self._by_file[file] = row

    def _validate_row(self, row: object, *, line_number: int | None = None) -> None:
        where = f" at line {line_number}" if line_number is not None else ""
        if not isinstance(row, dict) or row.get("schema") != SCHEMA:
            raise CheckpointError(f"invalid checkpoint schema{where}")
        if row.get("floor") != self.floor:
            raise CheckpointError(f"checkpoint floor mismatch{where}")
        if row.get("corpusManifestCid") != self.manifest_cid:
            raise CheckpointError(f"checkpoint manifest CID mismatch{where}")
        file = row.get("file")
        if not isinstance(file, str) or file not in self.files:
            raise CheckpointError(f"checkpoint names unknown file{where}: {file!r}")
        if not isinstance(row.get("result"), dict):
            raise CheckpointError(f"checkpoint result is not an object{where}")

    def pending_files(self) -> tuple[str, ...]:
        return tuple(file for file in self.files if file not in self._by_file)

    def append(self, file: str, result: Mapping[str, Any]) -> dict[str, Any]:
        if file in self._by_file:
            raise CheckpointError(f"duplicate checkpoint row for {file}")
        row: dict[str, Any] = {
            "schema": SCHEMA,
            "floor": self.floor,
            "corpusManifestCid": self.manifest_cid,
            "file": file,
            "result": dict(result),
        }
        self._validate_row(row)
        encoded = (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644
        )
        try:
            view = memoryview(encoded)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("checkpoint append made no progress")
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        self._by_file[file] = row
        return row

    def rows(self) -> list[dict[str, Any]]:
        return [self._by_file[file] for file in self.files if file in self._by_file]


def run_pending(
    checkpoint: Checkpoint,
    worker: Callable[[str], Mapping[str, Any]],
    *,
    workers: int,
) -> list[dict[str, Any]]:
    pending = checkpoint.pending_files()
    if not pending:
        return checkpoint.rows()
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {executor.submit(worker, file): file for file in pending}
        for future in as_completed(futures):
            file = futures[future]
            checkpoint.append(file, future.result())
    return checkpoint.rows()


T = TypeVar("T")


def checkpointed_path_results(
    *,
    floor: str,
    paths: Sequence[Path],
    root: Path,
    checkpoint_path: Path,
    worker: Callable[[Path], T],
    serialize: Callable[[T], Mapping[str, Any]],
    deserialize: Callable[[str, Mapping[str, Any]], T],
    workers: int,
) -> tuple[T, ...]:
    """Run absent paths and return one typed result for every manifest file."""
    by_rel = {
        path.resolve().relative_to(root.resolve()).as_posix(): path
        for path in sorted(paths)
    }
    checkpoint = Checkpoint(
        floor=floor, files=tuple(by_rel), path=checkpoint_path
    )
    rows = run_pending(
        checkpoint,
        lambda rel: serialize(worker(by_rel[rel])),
        workers=workers,
    )
    if len(rows) != len(by_rel):
        raise CheckpointError(
            f"incomplete {floor} checkpoint: {len(rows)}/{len(by_rel)} rows"
        )
    return tuple(
        deserialize(str(row["file"]), row["result"])
        for row in rows
    )
