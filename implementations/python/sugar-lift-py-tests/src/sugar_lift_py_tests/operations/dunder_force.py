from __future__ import annotations

from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.floor import FloorValue
from sugar_lift_py_tests.floor.call_site_value import force_floor
from sugar_lift_py_tests.outcome import Incomplete


def force_dunder_floor_or_runtime_effect(
    value: FloorValue,
    ctx,
    *,
    owner: str,
    project_callsite: bool = False,
):
    try:
        return force_floor(
            value,
            ctx,
            owner=owner,
            project_callsite=project_callsite,
        )
    except TypeError as exc:
        if _is_factory_reduction_typeerror(exc):
            raise
        return Incomplete(
            RuntimeEffect(
                f"{owner} reduced to a runtime effect or opaque callsite: {exc}"
            )
        )


def _is_factory_reduction_typeerror(exc: TypeError) -> bool:
    message = str(exc)
    return message.startswith("write more ") and " for this " in message
