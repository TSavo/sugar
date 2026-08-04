#!/usr/bin/env python3
"""Producer-owned wire for exact showcase terminal identities.

The writer is deliberately additive: producers may call it before the showcase
consumer supplies an output path.  Once supplied, the path accepts exactly one
validated terminal identity.  A later observation cannot replace the first
terminal.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import NoReturn


TERMINAL_WITNESS_ENV = "SHOWCASE_TERMINAL_WITNESS"
TERMINAL_IDENTITY_SCHEMA_VERSION = 1
_REQUIRED_FIELDS = ("schemaVersion", "kind", "owner")
_OPTIONAL_FIELDS = ("coordinate", "observed", "requested", "entrance")
_ALLOWED_FIELDS = frozenset((*_REQUIRED_FIELDS, *_OPTIONAL_FIELDS))


class TerminalIdentityRefusal(ValueError):
    """The producer could not publish an exact terminal identity."""


def _refuse(reason: str) -> NoReturn:
    raise TerminalIdentityRefusal(reason)


def validate_terminal_identity(raw: Mapping[str, object]) -> dict[str, object]:
    """Return the canonical raw identity or refuse a lossy/malformed value."""

    unsupported = sorted(set(raw) - _ALLOWED_FIELDS)
    if unsupported:
        _refuse(f"unsupported fields: {', '.join(unsupported)}")

    missing = [field for field in _REQUIRED_FIELDS if field not in raw]
    if missing:
        _refuse(f"missing required fields: {', '.join(missing)}")

    if raw["schemaVersion"] != TERMINAL_IDENTITY_SCHEMA_VERSION:
        _refuse(
            "schemaVersion must be "
            f"{TERMINAL_IDENTITY_SCHEMA_VERSION}, got {raw['schemaVersion']!r}"
        )

    for field in ("kind", "owner"):
        value = raw[field]
        if not isinstance(value, str) or not value.strip():
            _refuse(f"terminal identity requires nonempty {field}")

    for field in _OPTIONAL_FIELDS:
        if field not in raw:
            continue
        value = raw[field]
        if not isinstance(value, str) or not value.strip():
            _refuse(f"terminal identity requires nonempty {field} when present")

    # Preserve raw producer testimony.  Fixed field order makes the bytes
    # deterministic without normalizing any identity-bearing string.
    return {
        field: raw[field]
        for field in (*_REQUIRED_FIELDS, *_OPTIONAL_FIELDS)
        if field in raw
    }


def _json_objects(text: str) -> Sequence[object]:
    decoder = json.JSONDecoder()
    objects: list[object] = []
    for offset, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, _end = decoder.raw_decode(text[offset:])
        except ValueError:
            continue
        objects.append(value)
    return objects


def _rpc_error_payload(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, dict):
        return None
    nested = value.get("error")
    if isinstance(nested, dict):
        return nested
    if "code" in value and "message" in value:
        return value
    return None


def _canonical_coordinate(value: str, repo_root: Path) -> str:
    prefix = str(repo_root.resolve()) + os.sep
    return value[len(prefix) :] if value.startswith(prefix) else value


def identity_from_rpc_text(
    text: str,
    *,
    repo_root: Path,
    entrance: str,
) -> dict[str, object]:
    """Project one structured RPC terminal selected by its showcase producer.

    The caller owns *which* failing command is the showcase terminal.  This
    function only projects the structured error returned by that command; it
    never classifies prose or overlapping scoreboard counters.
    """

    error: Mapping[str, object] | None = None
    diagnostic: Mapping[str, object] | None = None
    data: Mapping[str, object] | None = None
    for value in _json_objects(text):
        candidate = _rpc_error_payload(value)
        if candidate is None:
            continue
        candidate_data = candidate.get("data")
        if not isinstance(candidate_data, dict):
            continue
        candidate_diagnostic = candidate_data.get("diagnostic")
        if isinstance(candidate_diagnostic, dict):
            error = candidate
            data = candidate_data
            diagnostic = candidate_diagnostic
            break
        if error is None:
            error = candidate
            data = candidate_data

    if error is None or data is None:
        _refuse("selected command emitted no structured RPC error")
    if diagnostic is None:
        _refuse("structured RPC error lacks diagnostic owner")

    kind = data.get("exception_type")
    owner = diagnostic.get("owner")
    identity: dict[str, object] = {
        "schemaVersion": TERMINAL_IDENTITY_SCHEMA_VERSION,
        "kind": kind,
        "owner": owner,
        "entrance": entrance,
    }
    blame = diagnostic.get("blame")
    if isinstance(blame, str) and blame.strip():
        identity["coordinate"] = _canonical_coordinate(blame, repo_root)
    for field in ("observed", "requested"):
        value = diagnostic.get(field)
        if isinstance(value, str) and value.strip():
            identity[field] = value
    return validate_terminal_identity(identity)


def _publish_once(output: Path, identity: Mapping[str, object]) -> None:
    if not output.is_absolute():
        _refuse(f"{TERMINAL_WITNESS_ENV} must be an absolute path: {output}")
    if not output.parent.is_dir():
        _refuse(f"terminal witness parent does not exist: {output.parent}")

    payload = json.dumps(identity, sort_keys=False, separators=(",", ":")) + "\n"
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{output.name}.",
            suffix=".tmp",
            dir=output.parent,
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            # A hard link installs the complete bytes atomically and, unlike
            # os.replace(), refuses if another terminal already owns the path.
            os.link(temporary_path, output)
        except FileExistsError:
            _refuse(f"terminal witness already exists: {output}")
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def write_from_environment(raw: Mapping[str, object]) -> bool:
    """Validate and optionally publish one terminal identity.

    Returns ``False`` only when no consumer has supplied an output path.  An
    invalid producer identity refuses even in that additive/no-consumer mode.
    """

    identity = validate_terminal_identity(raw)
    output_value = os.environ.get(TERMINAL_WITNESS_ENV)
    if output_value is None:
        return False
    if not output_value:
        _refuse(f"{TERMINAL_WITNESS_ENV} must not be empty")
    _publish_once(Path(output_value), identity)
    return True


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish one exact showcase terminal identity"
    )
    parser.add_argument("--kind")
    parser.add_argument("--owner")
    parser.add_argument("--coordinate")
    parser.add_argument("--observed")
    parser.add_argument("--requested")
    parser.add_argument("--entrance")
    parser.add_argument("--rpc-diagnostic", type=Path)
    parser.add_argument("--repo-root", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.rpc_diagnostic is not None:
            if arguments.kind is not None or arguments.owner is not None:
                _refuse("RPC projection cannot also accept authored kind/owner")
            if arguments.repo_root is None or arguments.entrance is None:
                _refuse("RPC projection requires --repo-root and --entrance")
            identity = identity_from_rpc_text(
                arguments.rpc_diagnostic.read_text(
                    encoding="utf-8", errors="replace"
                ),
                repo_root=arguments.repo_root,
                entrance=arguments.entrance,
            )
        else:
            identity = {
                "schemaVersion": TERMINAL_IDENTITY_SCHEMA_VERSION,
                "kind": arguments.kind,
                "owner": arguments.owner,
            }
            for field in _OPTIONAL_FIELDS:
                value = getattr(arguments, field)
                if value is not None:
                    identity[field] = value
        write_from_environment(identity)
    except (OSError, TerminalIdentityRefusal) as error:
        _parser().exit(2, f"showcase-terminal-identity: REFUSED: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
