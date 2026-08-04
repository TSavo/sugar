#!/usr/bin/env python3
"""Classify rebuild-lock publication without discarding operating-system facts."""

from __future__ import annotations

import argparse
import errno
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
import stat


@dataclass(frozen=True)
class LockStateResult:
    state: str
    path: str
    errno_name: str | None = None
    errno_number: int | None = None
    detail: str | None = None
    mode: str | None = None
    uid: int | None = None
    gid: int | None = None


def _refused(path: Path, error: OSError) -> LockStateResult:
    number = error.errno
    return LockStateResult(
        state="create-refused",
        path=str(path),
        errno_name=errno.errorcode.get(number, "UNKNOWN") if number else "UNKNOWN",
        errno_number=number,
        detail=str(error),
    )


def _mkdir_shared(path: Path) -> None:
    previous = os.umask(0)
    try:
        os.mkdir(path, 0o777)
    finally:
        os.umask(previous)


def create_lock_directory(path: Path) -> LockStateResult:
    """Atomically acquire *path*, distinguishing EEXIST from create refusal."""

    try:
        _mkdir_shared(path)
    except FileExistsError as error:
        if path.is_dir():
            return LockStateResult(state="contended", path=str(path))
        if not path.exists():
            # The EEXIST winner lawfully released between mkdir and observation.
            return LockStateResult(state="released", path=str(path))
        return _refused(
            path,
            NotADirectoryError(
                errno.ENOTDIR,
                "existing rebuild-lock path is not a directory",
                str(path),
            ),
        )
    except OSError as error:
        return _refused(path, error)
    return LockStateResult(state="acquired", path=str(path), mode="0777")


def publish_lock_parent(path: Path) -> LockStateResult:
    """Create and authenticate the cross-identity rebuild-lock namespace."""

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        return _refused(path, error)
    try:
        _mkdir_shared(path)
    except FileExistsError:
        pass
    except OSError as error:
        return _refused(path, error)

    try:
        metadata = path.stat()
    except OSError as error:
        return _refused(path, error)
    if not stat.S_ISDIR(metadata.st_mode):
        return _refused(
            path,
            NotADirectoryError(
                errno.ENOTDIR,
                "rebuild-lock parent is not a directory",
                str(path),
            ),
        )

    mode = stat.S_IMODE(metadata.st_mode)
    testimony = {
        "mode": f"{mode:04o}",
        "uid": metadata.st_uid,
        "gid": metadata.st_gid,
    }
    if mode != 0o777 or not os.access(path, os.W_OK | os.X_OK):
        return LockStateResult(
            state="unshareable",
            path=str(path),
            detail="rebuild-lock parent must be writable across host/container identities",
            **testimony,
        )
    return LockStateResult(state="ready", path=str(path), **testimony)


def _emit(result: LockStateResult) -> None:
    body = {key: value for key, value in asdict(result).items() if value is not None}
    print(f"{result.state}\t{json.dumps(body, sort_keys=True, separators=(',', ':'))}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("create", "publish-parent"))
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    if args.operation == "create":
        _emit(create_lock_directory(args.path))
    else:
        _emit(publish_lock_parent(args.path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
