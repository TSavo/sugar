"""Resource ``with``: enter once, body ExitSet, exit on every outgoing face.

Not the assertion-manager path (``WithContractSugar`` / membrane Expects and
Suppresses). This sugar is the enter/exit transformation:

1. Evaluate enter once.
2. Enter halt exits before the body and never invokes exit.
3. Bind ``as`` from the enter-result coordinate (when constructed).
4. Reduce the body to a guarded ExitSet.
5. Run exit over every body exit (``ExitSet.and_exit``).
6. Exit halt supersedes; exit false restores; exit true consumes;
   unproved suppression stays open residual under its guard.

Admission rule: a manager is admitted only when enter and exit are
constructed, or unresolved parts remain explicitly red. ``NeverSuppresses``
is disposition (never consume body halt), not permission to skip the exit
call — exit can itself halt and must be constructed.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import Callable

from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class WithResourceSugar(Sugar):
    """Resource with under a constructed enter/exit pair + exit disposition.

    ``enter`` / ``exit_call`` are zero-arg callables producing ExitSet — the
    constructed enter/exit behaviours (or explicit red Incomplete residuals).
    ``suppresses`` decides completed-exit disposition for a body halt; default
    never suppresses (``NeverSuppresses``). ``open_suppression`` when set marks
    runtime-selected / unproved halt faces instead of guessing.
    """

    body: tuple
    enter: Callable[[], object]  # () -> ExitSet
    exit_call: Callable[[], object]  # () -> ExitSet
    suppresses: Callable[[object, object], bool] | None = None
    open_suppression: Callable[[object], object] | None = None
    site: object = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        # Resource path is not yet a green source surface (open stays
        # RuntimeSelected). Witness is structural via unit twins.
        return _call_pair(
            name="with_resource_never_suppresses_structure",
            owner_sugar="WithResourceSugar",
            truthful=(
                "def A(z):\n"
                "    with contextlib.suppress(KeyError):\n"
                "        raise KeyError\n"
                "    return z\n\n"
                "def test_a():\n"
                "    assert A(5) == 5\n"
            ),
            lying=(
                "def A(z):\n"
                "    with contextlib.suppress(KeyError):\n"
                "        raise KeyError\n"
                "    return z\n\n"
                "def test_a():\n"
                "    assert A(5) == 6\n"
            ),
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted
        from sugar_lift_py_tests.sugar.exit_set_routing import (
            exitset_to_outcome,
            promote_raise_halts,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            _ReducedBlock,
            reduce_block_to_exitset,
        )

        del ctx

        enter_es = self.enter()
        if not isinstance(enter_es, ExitSet):
            raise TypeError(
                f"WithResourceSugar.enter must return ExitSet, got {type(enter_es).__name__}"
            )

        def _exit() -> ExitSet:
            result = self.exit_call()
            if not isinstance(result, ExitSet):
                raise TypeError(
                    "WithResourceSugar.exit_call must return ExitSet, "
                    f"got {type(result).__name__}"
                )
            return result

        # Body/exit only when enter completes. Reduce body once if any face
        # completes; never construct body or exit under pure enter-halt.
        needs_body = any(isinstance(e, Completed) for e in enter_es.exits)
        body_es = (
            promote_raise_halts(reduce_block_to_exitset(self.body))
            if needs_body
            else None
        )

        parts: list = []
        for enter_exit in enter_es.exits:
            if isinstance(enter_exit, Halted):
                # Enter halt: no body, no exit.
                parts.append(ExitSet((enter_exit,)))
                continue
            # Enter completed: body under enter guard, then exit on every face.
            assert body_es is not None
            after_body = body_es.guarded(enter_exit.guard)
            after_exit = after_body.and_exit(
                _exit,
                suppresses=self.suppresses,
                open_suppression=self.open_suppression,
            )
            parts.append(after_exit)

        if not parts:
            routed = ExitSet.completed(
                _ReducedBlock(entries=(), can_fall_through=True, fall_through=())
            )
        else:
            routed = parts[0]
            for part in parts[1:]:
                routed = routed.union(part)

        return exitset_to_outcome(routed)


def never_suppresses_disposition(_effect: object, _exit_value: object) -> bool:
    """``NeverSuppresses``: completed exit never consumes the body halt."""
    return False


def suppresses_named(*exception_names: str) -> Callable[[object, object], bool]:
    """Completed exit suppresses only named raise effects (proven subset)."""

    names = frozenset(exception_names)

    def _decide(effect: object, _exit_value: object) -> bool:
        name = getattr(effect, "exception_name", None)
        return name in names

    return _decide


def open_suppression_residual(effect: object) -> object:
    """Keep the body effect as open residual — do not invent suppress/restore.

    Used when exit disposition is runtime-selected. The residual is the same
    effect under the face guard; callers that need a distinct marker can wrap.
    """
    return effect
