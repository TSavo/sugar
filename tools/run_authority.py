#!/usr/bin/env python3
"""RunAuthority — durable testimony of what a sugarbin run actually consumed.

THE ARTIFACT MUST PROVE WHAT IT CONSUMED. A run that cannot show its task
ownership, its image selection and its preflight plan cannot produce a
bankable measurement.

``bin/sugarbin`` recognises a managed task only when the dispatched argv
literally begins with a registered task command. A showcase measurement
wrapped in ``bash -lc '<script>'`` therefore matched nothing, was treated as
an allowed ad-hoc command, selected the ordinary capability image, installed
no managed precondition plan and enrolled no profiled closure artifacts. The
run still produced a receipt, and that receipt was indistinguishable from a
managed one. Recognition by spelling made an unauthenticated environment
invisible and therefore bankable.

This module does not change what ``brun`` may execute. Ad-hoc diagnostics stay
executable; their *consequence* becomes visible. Every bx run carries
``run-authority/v1`` testimony describing the authority it actually ran under,
and measurement consumers classify from that testimony rather than from
silence.

    RunAuthority = ManagedRunAuthority | UnmanagedRunAuthority

Three states, three distinct names, never two:

  MANAGED     a declared task owns the dispatched command; the task's image
              and its precondition plan are named in the testimony.
  UNMANAGED   the command ran ad-hoc. Explicitly marked, durable, and
              UNMEASURED BY CONSTRUCTION downstream.
  refused     absent, malformed/conflicting, or *lying* testimony is none of
              the above and is refused under its own name.

The lying arm is the one that matters. Absence is the easy case; a genuinely
ad-hoc run that records itself as managed is the dangerous one. An affirmative
managed claim is corroborated by re-deriving ownership: the claimed task must
be declared, and its declared command must be a prefix of the argv the run
actually dispatched. Spelling is a *necessary condition on an affirmative
claim*, which is sound; spelling as the sole detector of a negative is the
defect this module closes.

One door: ``build_run_authority`` constructs, ``authenticate_run_authority``
admits. There is no other way to obtain a ``ManagedRunAuthority``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence, Union

RUN_AUTHORITY_SCHEMA = "run-authority/v1"
"""Schema tag every carrier must spell exactly."""

RUN_AUTHORITY_ENV = "SUGAR_BX_RUN_AUTHORITY"
"""Environment variable through which the transport hands testimony to the payload."""

AUTHORITY_MANAGED = "managed"
AUTHORITY_UNMANAGED = "unmanaged"

REFUSAL_ABSENT = "RunAuthorityAbsentV1"
"""No testimony at all. Silence is not unmanaged."""

REFUSAL_MALFORMED = "RunAuthorityMalformedV1"
"""Testimony carried but unreadable, or self-conflicting field presence."""

REFUSAL_UNDECLARED_TASK = "RunAuthorityUndeclaredTaskV1"
"""A managed claim naming a task the contract does not declare."""

REFUSAL_UNOWNED_COMMAND = "RunAuthorityUnownedCommandV1"
"""THE LYING ARM: a managed claim whose task does not own the dispatched argv."""

REFUSAL_UNPLANNED_TASK = "RunAuthorityUnplannedTaskV1"
"""A declared task that installed no precondition plan. Honest, but unbankable."""

REFUSAL_UNMEASURED_BY_CONSTRUCTION = "UnmanagedRunUnmeasuredByConstructionV1"
"""An UNMANAGED run cannot be minted into a measured artifact."""


class RunAuthorityRefusal(TypeError):
    """Refused run-authority testimony. Carries its refusal name in the text."""


def _refuse(name: str, detail: str) -> RunAuthorityRefusal:
    return RunAuthorityRefusal(f"{name}: {detail}")


def plan_cid(payload: Any) -> str:
    """Content address of a precondition plan, canonical-JSON keyed."""
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"blake2b-256:{hashlib.blake2b(raw, digest_size=32).hexdigest()}"


_MANAGED_SEAL = object()
_UNMANAGED_SEAL = object()


@dataclass(frozen=True, slots=True)
class ManagedRunAuthority:
    """A run a declared task owned, with its image and precondition plan named.

    Sealed: obtainable only from ``authenticate_run_authority``. Holding one is
    itself the proof that ownership was re-derived, so downstream consumers
    have no guard to forget and no guard to remove.
    """

    task: str
    image: str
    preflight_protocol: str
    precondition_plan_cid: str | None
    command: tuple[str, ...]
    _seal: object

    def __post_init__(self) -> None:
        if self._seal is not _MANAGED_SEAL:
            raise _refuse(
                REFUSAL_MALFORMED,
                "ManagedRunAuthority is sealed: use authenticate_run_authority(...)",
            )

    def is_managed(self) -> bool:
        return True

    def as_json(self) -> dict[str, Any]:
        return {
            "schema": RUN_AUTHORITY_SCHEMA,
            "authority": AUTHORITY_MANAGED,
            "task": self.task,
            "image": self.image,
            "preflightProtocol": self.preflight_protocol,
            "preconditionPlanCid": self.precondition_plan_cid,
            "command": list(self.command),
        }


@dataclass(frozen=True, slots=True)
class UnmanagedRunAuthority:
    """A run that executed ad-hoc. Legitimate, durable, and explicitly marked.

    This is not a degraded managed run and not an absent one. It is its own
    state, and it is the state from which no measured artifact is constructible.
    """

    command: tuple[str, ...]
    image: str
    _seal: object

    def __post_init__(self) -> None:
        if self._seal is not _UNMANAGED_SEAL:
            raise _refuse(
                REFUSAL_MALFORMED,
                "UnmanagedRunAuthority is sealed: use authenticate_run_authority(...)",
            )

    def is_managed(self) -> bool:
        return False

    def as_json(self) -> dict[str, Any]:
        return {
            "schema": RUN_AUTHORITY_SCHEMA,
            "authority": AUTHORITY_UNMANAGED,
            "task": None,
            "image": self.image,
            "preflightProtocol": None,
            "preconditionPlanCid": None,
            "command": list(self.command),
        }


RunAuthority = Union[ManagedRunAuthority, UnmanagedRunAuthority]


def build_run_authority(
    command: Sequence[str],
    *,
    image: str,
    task: str | None = None,
    preflight_protocol: str | None = None,
    precondition_plan: Any = None,
) -> dict[str, Any]:
    """Producer side: the canonical testimony a run carries.

    ``task is None`` produces UNMANAGED testimony. A named task produces
    MANAGED testimony and requires both a preflight protocol and a precondition
    plan, so a managed claim can never be half-evidenced at the source.
    """
    argv = [str(item) for item in command]
    if not argv:
        raise _refuse(REFUSAL_MALFORMED, "a run carries the argv it dispatched")
    if not isinstance(image, str) or not image.strip():
        raise _refuse(REFUSAL_MALFORMED, "a run names the image it selected")
    if task is None:
        return {
            "schema": RUN_AUTHORITY_SCHEMA,
            "authority": AUTHORITY_UNMANAGED,
            "task": None,
            "image": image.strip(),
            "preflightProtocol": None,
            "preconditionPlanCid": None,
            "command": argv,
        }
    if not isinstance(preflight_protocol, str) or not preflight_protocol.strip():
        raise _refuse(
            REFUSAL_MALFORMED,
            f"managed task {task!r} must name the preflight protocol it installed",
        )
    # A declared task that declares no command closure genuinely installs no
    # precondition plan. That is an honest state, not a lie, so the transport
    # records it faithfully as a null plan. It is the *measurement* door that
    # refuses it, because a run with no plan cannot prove what it consumed.
    return {
        "schema": RUN_AUTHORITY_SCHEMA,
        "authority": AUTHORITY_MANAGED,
        "task": task,
        "image": image.strip(),
        "preflightProtocol": preflight_protocol.strip(),
        "preconditionPlanCid": None if precondition_plan is None else plan_cid(precondition_plan),
        "command": argv,
    }


def stamp_run_authority(body: dict[str, Any], environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Producer door: copy the transport's testimony into a report body.

    Every measurement producer stamps through here rather than each spelling
    ``runAuthority`` for itself, so there is one carrier name and no producer
    can accidentally invent a second one. When the transport supplied nothing
    the body carries nothing, and the consumer reads that as
    ``RunAuthorityAbsentV1`` — fail-closed, because silence is exactly the
    state that made the original defect bankable.
    """
    import os

    raw = (environ if environ is not None else os.environ).get(RUN_AUTHORITY_ENV)
    if raw:
        body["runAuthority"] = json.loads(raw)
    return body


def _default_task_command_resolver(task: str) -> Sequence[str] | None:
    """Resolve a declared task's command from the build contract."""
    import importlib.util
    import sys
    from pathlib import Path

    contract_path = Path(__file__).resolve().parent / "sugar-build" / "contract.py"
    spec = importlib.util.spec_from_file_location("sugar_build_contract", contract_path)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging accident
        return None
    module = sys.modules.get("sugar_build_contract")
    if module is None:
        module = importlib.util.module_from_spec(spec)
        sys.modules["sugar_build_contract"] = module
        spec.loader.exec_module(module)
    try:
        return module.resolve_task(task)["command"]
    except Exception:
        return None


def _require_str_field(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _refuse(
            REFUSAL_MALFORMED,
            f"field {key!r} must be a non-empty string; got {value!r}",
        )
    return value.strip()


def _require_absent_field(payload: Mapping[str, Any], key: str, authority: str) -> None:
    if payload.get(key) is not None:
        raise _refuse(
            REFUSAL_MALFORMED,
            f"{authority} testimony must not carry {key!r}; got {payload.get(key)!r}",
        )


def authenticate_run_authority(
    testimony: Any,
    *,
    task_command_resolver: Callable[[str], Sequence[str] | None] | None = None,
) -> RunAuthority:
    """Admit run-authority testimony, or refuse it under its own name.

    Absent, malformed/conflicting, undeclared-task and unowned-command are four
    distinct refusals. A tooth that only proves "something refused" would still
    pass with its own guard removed, so each carries a name of its own.
    """
    if testimony is None:
        raise _refuse(
            REFUSAL_ABSENT,
            "run produced no run-authority testimony; silence is not unmanaged",
        )
    if isinstance(testimony, (str, bytes)):
        try:
            testimony = json.loads(testimony)
        except ValueError as error:
            raise _refuse(
                REFUSAL_MALFORMED, f"run-authority testimony is not JSON: {error}"
            ) from error
    if not isinstance(testimony, Mapping):
        raise _refuse(
            REFUSAL_MALFORMED,
            f"run-authority testimony must be an object; got {type(testimony).__name__}",
        )
    schema = testimony.get("schema")
    if schema != RUN_AUTHORITY_SCHEMA:
        raise _refuse(
            REFUSAL_MALFORMED,
            f"unsupported run-authority schema {schema!r}; expected {RUN_AUTHORITY_SCHEMA}",
        )
    command = testimony.get("command")
    if (
        not isinstance(command, Sequence)
        or isinstance(command, (str, bytes))
        or not command
        or any(not isinstance(item, str) or not item for item in command)
    ):
        raise _refuse(
            REFUSAL_MALFORMED,
            f"run-authority command must be a non-empty array of strings; got {command!r}",
        )
    argv = tuple(command)
    image = _require_str_field(testimony, "image")
    authority = testimony.get("authority")

    if authority == AUTHORITY_UNMANAGED:
        for key in ("task", "preflightProtocol", "preconditionPlanCid"):
            _require_absent_field(testimony, key, AUTHORITY_UNMANAGED)
        return UnmanagedRunAuthority(argv, image, _UNMANAGED_SEAL)

    if authority != AUTHORITY_MANAGED:
        raise _refuse(
            REFUSAL_MALFORMED,
            f"run-authority authority must be {AUTHORITY_MANAGED!r} or "
            f"{AUTHORITY_UNMANAGED!r}; got {authority!r}",
        )

    task = _require_str_field(testimony, "task")
    preflight_protocol = _require_str_field(testimony, "preflightProtocol")
    precondition_plan_cid = testimony.get("preconditionPlanCid")
    if precondition_plan_cid is not None and (
        not isinstance(precondition_plan_cid, str) or not precondition_plan_cid.strip()
    ):
        raise _refuse(
            REFUSAL_MALFORMED,
            f"field 'preconditionPlanCid' must be a non-empty string or null; "
            f"got {precondition_plan_cid!r}",
        )

    resolver = task_command_resolver or _default_task_command_resolver
    declared = resolver(task)
    if declared is None:
        raise _refuse(
            REFUSAL_UNDECLARED_TASK,
            f"managed claim names task {task!r}, which the build contract does not declare",
        )
    declared_argv = [str(item) for item in declared]
    if not declared_argv or list(argv[: len(declared_argv)]) != declared_argv:
        raise _refuse(
            REFUSAL_UNOWNED_COMMAND,
            f"managed claim names task {task!r} whose declared command "
            f"{declared_argv!r} does not own the dispatched command {list(argv)!r}",
        )
    return ManagedRunAuthority(
        task,
        image,
        preflight_protocol,
        precondition_plan_cid,
        argv,
        _MANAGED_SEAL,
    )


def require_managed_run_authority(
    testimony: Any,
    *,
    task_command_resolver: Callable[[str], Sequence[str] | None] | None = None,
) -> ManagedRunAuthority:
    """Admit testimony and demand it be MANAGED.

    An UNMANAGED run is a legitimate run and a refused *measurement*. This is
    the single door through which a measured artifact obtains its authority, so
    a measurement derived from an ad-hoc command is not flagged — it is
    unconstructible.
    """
    authority = authenticate_run_authority(
        testimony, task_command_resolver=task_command_resolver
    )
    if not authority.is_managed():
        raise _refuse(
            REFUSAL_UNMEASURED_BY_CONSTRUCTION,
            f"command {list(authority.command)!r} ran ad-hoc under no declared task; "
            "an unmanaged run cannot select the task capability image, cannot install "
            "a managed precondition plan, and cannot enrol profiled closure artifacts, "
            "so nothing it produced is a measurement",
        )
    if authority.precondition_plan_cid is None:
        raise _refuse(
            REFUSAL_UNPLANNED_TASK,
            f"task {authority.task!r} declares no command closure, so its run installed "
            "no managed precondition plan and cannot show the preconditions it consumed",
        )
    return authority
