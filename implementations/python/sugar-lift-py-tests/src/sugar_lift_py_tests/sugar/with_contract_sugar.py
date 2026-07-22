"""`with` under a typed contract: route over ExitSet faces, not a linear list.

Path:

    body -> reduce_block_to_exitset
         -> promote guarded raises to Halted
         -> route contract over each Halted / Completed exit
         -> preserve unmatched Completed exits
         -> authenticate slots only on matched guarded exits
         -> normalize
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class WithContractSugar(Sugar):
    contract: object
    body: tuple
    site: object = dataclass_field(compare=False, default=None)
    slot_id: str | None = None

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A(z):\n"
            "    with pytest.raises(ValueError):\n"
            "        raise ValueError\n"
            "    return z\n\n"
        )
        return _call_pair(
            name="with_expects_raise",
            owner_sugar="WithContractSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.effect_router import route
        from sugar_lift_py_tests.outcome import Incomplete
        from sugar_lift_py_tests.outcome.exit_set import ExitSet, Halted
        from sugar_lift_py_tests.sugar.exit_set_routing import (
            exitset_to_outcome,
            promote_raise_halts,
            routed_entries_to_exitset,
            site_inv_values,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            _ReducedBlock,
            reduce_block_to_exitset,
        )

        del ctx

        body_es = promote_raise_halts(reduce_block_to_exitset(self.body))
        parts: list = []
        for exit_ in body_es.exits:
            if isinstance(exit_, Halted):
                # One face, one observed halt — route under that guard only.
                entries = (Incomplete(exit_.effect),)
                routed = route(
                    entries,
                    self.contract,
                    slot_id=self.slot_id,
                    site=self.site,
                )
                sited = site_inv_values(routed.entries, self.site)
                parts.append(routed_entries_to_exitset(sited, exit_.guard))
                continue

            state = exit_.value
            if isinstance(state, _ReducedBlock):
                entries = state.entries
                prior = state
            else:
                entries = ()
                prior = None
            routed = route(
                tuple(entries),
                self.contract,
                slot_id=self.slot_id,
                site=self.site,
            )
            sited = site_inv_values(routed.entries, self.site)
            parts.append(
                routed_entries_to_exitset(sited, exit_.guard, prior_state=prior)
            )

        if not parts:
            routed_es = ExitSet.completed(
                _ReducedBlock(entries=(), can_fall_through=True, fall_through=())
            )
        else:
            routed_es = parts[0]
            for part in parts[1:]:
                routed_es = routed_es.union(part)

        return exitset_to_outcome(routed_es)
