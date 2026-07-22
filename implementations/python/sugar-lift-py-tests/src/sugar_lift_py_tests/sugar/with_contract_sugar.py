"""`with` under a typed contract: route once; slot binding is router testimony."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field, replace

from sugar_lift_py_tests.outcome import Complete, Outcome
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
        from sugar_lift_py_tests.floor.block_value import BlockValue
        from sugar_lift_py_tests.floor.inv_value import InvValue
        from sugar_lift_py_tests.outcome import Incomplete
        from sugar_lift_py_tests.sugar.function_universe_sugar import reduce_statements

        del ctx

        entries, _falls, _ft = reduce_statements(self.body)
        # Single match authority — route once, including optional slot binding.
        routed = route(
            tuple(entries),
            self.contract,
            slot_id=self.slot_id,
            site=self.site,
        )

        sited = tuple(
            replace(e, site=self.site)
            if isinstance(e, InvValue) and e.site is None
            else e
            for e in routed.entries
        )

        can_fall_through = not any(isinstance(e, Incomplete) for e in sited)
        return Complete(BlockValue(sited, can_fall_through=can_fall_through))
