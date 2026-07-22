"""Explicit record testimony for manager, enter-result, and exit-face auth.

Coordinates are pure; authentication is InvValue facts on the record.
Exit-face bindings supply guarded testimony for parametric
``ExitTypeRef(X)`` / ``ExitValueRef(X)`` / ``ExitTracebackRef(X)`` —
never by constructing new sugars at desugar time.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ManagerBinding:
    """Slot M is the once-evaluated manager expression result."""

    slot_id: str
    manager_value: object  # FloorValue

    def to_facts(self, site=None) -> tuple:
        from sugar_lift_py_tests.floor.inv_value import InvValue
        from sugar_lift_py_tests.ir import atomic, eq, str_const

        slot = str_const(self.slot_id)
        term = self.manager_value.to_term(owner="ManagerBinding")
        return (
            InvValue(
                eq(atomic("manager_slot_value", [slot]), term),
                site=site,
            ),
        )


@dataclass(frozen=True)
class EnterResultBinding:
    """Slot E is authenticated by the completed ``__enter__`` result."""

    slot_id: str
    enter_value: object  # FloorValue

    def to_facts(self, site=None) -> tuple:
        from sugar_lift_py_tests.floor.inv_value import InvValue
        from sugar_lift_py_tests.ir import atomic, eq, str_const

        slot = str_const(self.slot_id)
        term = self.enter_value.to_term(owner="EnterResultBinding")
        return (
            InvValue(
                eq(atomic("enter_result_value", [slot]), term),
                site=site,
            ),
        )


@dataclass(frozen=True)
class ExitFaceBinding:
    """Guarded testimony for parametric exit-arg coordinates under face X.

    - completed: type/value/tb bound to None
    - raised: type open or named; value = raise occurrence; tb open
    - open: all three open residuals
    """

    face_id: str
    kind: str  # "completed" | "raised" | "open"
    exception_name: str | None = None
    occurrence: str | None = None

    @classmethod
    def from_body_exit(cls, face_id: str, body_exit) -> "ExitFaceBinding":
        from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
        from sugar_lift_py_tests.outcome.exit_set import Completed, Halted

        if isinstance(body_exit, Completed):
            return cls(face_id=face_id, kind="completed")
        if isinstance(body_exit, Halted) and isinstance(
            body_exit.effect, RaiseEffect
        ):
            effect = body_exit.effect
            occurrence = (
                getattr(effect, "occurrence_id", None)
                or getattr(effect, "occurrence", None)
                or getattr(effect, "blame", None)
                or "unknown-raise"
            )
            return cls(
                face_id=face_id,
                kind="raised",
                exception_name=effect.exception_name,
                occurrence=str(occurrence),
            )
        return cls(face_id=face_id, kind="open")

    def to_facts(self, site=None, guard=None) -> tuple:
        from sugar_lift_py_tests.floor.inv_value import InvValue
        from sugar_lift_py_tests.ir import atomic, ctor, eq, str_const
        from sugar_lift_py_tests.outcome.exit_set import true_guard

        face = str_const(self.face_id)
        none = str_const("None")
        open_type = ctor("python:open_exit_arg", [str_const("exc_type")])
        open_tb = ctor("python:open_exit_arg", [str_const("traceback")])
        open_val = ctor("python:open_exit_arg", [str_const("exc_val")])

        if self.kind == "completed":
            rows = (
                eq(atomic("exit_type", [face]), none),
                eq(atomic("exit_value", [face]), none),
                eq(atomic("exit_traceback", [face]), none),
            )
        elif self.kind == "raised":
            type_term = (
                str_const(self.exception_name)
                if self.exception_name
                else open_type
            )
            value_term = ctor(
                "python:raise_effect_occurrence",
                [str_const(self.occurrence or "unknown-raise")],
            )
            rows = (
                eq(atomic("exit_type", [face]), type_term),
                eq(atomic("exit_value", [face]), value_term),
                eq(atomic("exit_traceback", [face]), open_tb),
            )
        else:
            rows = (
                eq(atomic("exit_type", [face]), open_type),
                eq(atomic("exit_value", [face]), open_val),
                eq(atomic("exit_traceback", [face]), open_tb),
            )

        facts = tuple(InvValue(row, site=site) for row in rows)
        if guard is not None and guard != true_guard():
            facts = tuple(f.guarded(guard) for f in facts)
        return facts


def prepend_facts_to_exitset(exits, facts: tuple):
    """Attach binding facts to every completed exit's entry list."""
    from dataclasses import replace

    from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

    if not facts:
        return exits
    out = []
    for exit_ in exits.exits:
        if isinstance(exit_, Halted):
            # Face bindings for halt faces still ride as companion completed
            # residue under the same guard so testimony is not dropped.
            out.append(exit_)
            if facts:
                out.append(
                    Completed(
                        exit_.guard,
                        _ReducedBlock(
                            entries=facts,
                            can_fall_through=False,
                            fall_through=(),
                        ),
                    )
                )
            continue
        value = exit_.value
        if isinstance(value, _ReducedBlock):
            out.append(
                Completed(
                    exit_.guard,
                    replace(value, entries=(*facts, *value.entries)),
                )
            )
        else:
            out.append(
                Completed(
                    exit_.guard,
                    _ReducedBlock(
                        entries=(*facts,),
                        can_fall_through=True,
                        fall_through=(),
                    ),
                )
            )
    return ExitSet(tuple(out)).normalize()
