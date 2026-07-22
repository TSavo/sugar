"""Resource ``with``: tree-owned enter/exit sugars + typed disposition.

Not the assertion-manager path (``WithContractSugar``). Not callback injection.

Structure:

1. ``enter`` / ``exit`` are **constructed sugars** (tree ``manager.__enter__()``
   / ``manager.__exit__(...)`` method-coordinate nodes, sugar()'d once).
2. ``disposition`` is a **typed contract** (``NeverSuppresses``,
   ``ExitSuppressionContract``, ``RuntimeSelected``, or membrane
   ``Suppresses``) — never a Python decision function.
3. Enter halt → no body, no exit.
4. Enter complete → body ExitSet → ``and_exit(exit_es, disposition=...)``.
5. Enter-result ``as`` is a tree ``ObservationRef`` (``ENTER_RESULT``), not a
   floor object stuffed into the sugar.

Admission: managers stay loud (``RuntimeSelectedContextManager``) until enter
and exit are constructed or unresolved parts remain explicitly red.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class WithResourceSugar(Sugar):
    """Resource with: enter sugar, exit sugar, body, typed disposition."""

    enter: Sugar
    exit: Sugar
    body: tuple
    disposition: object  # NeverSuppresses | ExitSuppressionContract | RuntimeSelected | Suppresses
    enter_slot_id: str | None = None
    site: object = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        # Resource path is not yet a green source surface (open stays
        # RuntimeSelected). Structural witness reuses membrane suppress green.
        return _call_pair(
            name="with_resource_structure",
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
            sugar_outcome_to_exitset,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            _ReducedBlock,
            reduce_block_to_exitset,
        )

        del ctx

        enter_es = sugar_outcome_to_exitset(self.enter.desugar())
        needs_body = any(isinstance(e, Completed) for e in enter_es.exits)

        body_es = (
            promote_raise_halts(reduce_block_to_exitset(self.body))
            if needs_body
            else None
        )
        # Exit sugar materializes only when enter completed (body path).
        exit_es = (
            sugar_outcome_to_exitset(self.exit.desugar()) if needs_body else None
        )

        parts: list = []
        for enter_exit in enter_es.exits:
            if isinstance(enter_exit, Halted):
                parts.append(ExitSet((enter_exit,)))
                continue
            assert body_es is not None and exit_es is not None
            after_body = body_es.guarded(enter_exit.guard)
            after_exit = after_body.and_exit(
                exit_es,
                disposition=self.disposition,
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
