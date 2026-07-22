"""`with <manager> [as <name>]: <body>` under a TYPED contract -- #5994 wiring.

The node consults the recognition membrane (never a vendor name); the membrane
issues a typed contract; this sugar reduces the body as a block and hands the
outcome to the ONE effect router shared with Try. The contract decides:

- ``Expects(matcher)``: the obligation `observed_effect matches expected` --
  a matching halt is EVIDENCE, consumed into a ground-true fact; a completed
  body (no hiding coordinates) is the lying twin; a wrong effect states the
  mismatch AND keeps the effect; unresolved call coordinates retain an opaque
  obligation, never an absence claim.
- ``Suppresses(matcher)``: permission -- a matching halt is consumed silently;
  absence is fine; a non-matching effect propagates.

``as <Name>`` stays LOUD at the node: the honest binding is the routed
observed-effect witness (the payload of the matched Halted exit), produced at
route time, never a substitute-time ``E()`` stand-in. It lands with the shared
exit-set witness mechanism, not here.

Loud at the node: unauthenticated managers, any as-target, multiple managers,
resource expansion (step 4).
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field, replace

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class WithContractSugar(Sugar):
    contract: object  # Expects | Suppresses (the node guards kind)
    body: tuple  # the body statements' sugars, in source order
    site: object = dataclass_field(compare=False, default=None)
    # Preallocated by tree substitute for `as` (ObservationRef slot); None if no as.
    slot_id: str | None = None

    @classmethod
    def witnesses(cls):
        # The obligation discriminates: a body that halts with the expected
        # exception discharges; asserting the wrong function outcome lies.
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
        from sugar_lift_py_tests.floor.block_value import BlockValue
        from sugar_lift_py_tests.floor.inv_value import InvValue
        from sugar_lift_py_tests.sugar.function_universe_sugar import reduce_statements

        from sugar_lift_py_tests.effect_auth import authenticate_slot
        from sugar_lift_py_tests.effect_router import _matching_effect
        from sugar_lift_py_tests.outcome import Incomplete

        entries, _falls, _ft = reduce_statements(self.body)
        body_entries = tuple(entries)

        # Authenticate the preallocated as-slot with the matched halt payload
        # before/as we route (body already sugared with ObservationRef).
        if self.slot_id is not None:
            from sugar_lift_py_tests.context_manager_contract import Expects

            if isinstance(self.contract, Expects):
                matching = _matching_effect(body_entries, self.contract.matcher)
                if matching is not None:
                    _index, entry, _obs = matching
                    if isinstance(entry, Incomplete):
                        authenticate_slot(self.slot_id, entry.effect)

        routed = route(body_entries, self.contract)

        # The router's facts carry no site; the mint demands one. Re-seat each
        # stated fact on this with's fragment (the locus that stated it).
        sited = tuple(
            replace(e, site=self.site)
            if isinstance(e, InvValue) and e.site is None
            else e
            for e in routed.entries
        )

        # A consumed halt completes the with: fall-through is restored exactly
        # when no red testimony survives the routing.
        can_fall_through = not any(isinstance(e, Incomplete) for e in sited)
        return Complete(BlockValue(sited, can_fall_through=can_fall_through))
