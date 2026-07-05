from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import BoundVar, FloorValue, ObjectValue
from sugar_lift_py_tests.operations import AttributeDeleteOperation, perform_operation
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import SugarWitnessPair, WitnessSource
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class _CompletedFloorBody:
    value: FloorValue

    def desugar(self, ctx) -> Outcome:
        del ctx
        return Complete(self.value)


@dataclass(frozen=True)
class AttributeDeleteSugar(Sugar, role=SugarRole.STATEMENT):
    receiver: SugarBody
    receiver_name: str | None
    name: str
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Delete":
            return False
        targets = site.delete_targets()
        return len(targets) == 1 and targets[0].observed == "Attribute"

    @classmethod
    def witnesses(cls) -> SugarWitnessPair:
        prefix = (
            "class Box:\n"
            "    value = 0\n"
            "\n"
            "def A(z):\n"
            "    obj = Box()\n"
            "    obj.value = 2\n"
            "    del obj.value\n"
            "    return obj.value\n"
            "\n"
        )
        return SugarWitnessPair(
            name="attribute_delete_post_state_read",
            owner_sugar=cls.__name__,
            family="attribute-mutation",
            truthful=WitnessSource(
                source=prefix + "def test_a():\n    assert A(0) == 0\n",
                expected="sat",
            ),
            lying=WitnessSource(
                source=prefix + "def test_a():\n    assert A(0) == 2\n",
                expected="unsat",
            ),
        )

    @classmethod
    def build(cls, site, ctx) -> "AttributeDeleteSugar":
        target = site.delete_targets()[0]
        receiver = target.attr_receiver()
        return cls(
            receiver=ctx.build_body(receiver, SugarRole.TERM),
            receiver_name=receiver.name_id() if receiver.observed == "Name" else None,
            name=target.attr_name(),
            blame=site.blame,
        )

    def desugar(self, ctx) -> Outcome:
        receiver_outcome = self.receiver.reduce(ctx)
        if isinstance(receiver_outcome, Incomplete):
            return receiver_outcome
        receiver = complete_value(
            receiver_outcome, owner="AttributeDeleteSugar receiver"
        )
        mutation = perform_operation(
            owner="AttributeDeleteSugar",
            blame=self.blame,
            receiver=receiver,
            operation=AttributeDeleteOperation(
                name=self.name,
                owner="AttributeDeleteSugar",
                blame=self.blame,
            ),
            ctx=ctx,
        )
        if isinstance(mutation, Incomplete):
            return mutation
        mutated = complete_value(mutation, owner="AttributeDeleteSugar mutation")
        if isinstance(mutated, ObjectValue) and self.receiver_name is not None:
            return Complete(
                BoundVar(
                    self.receiver_name,
                    SugarBody(_CompletedFloorBody(mutated), SugarRole.TERM),
                    scope=ctx,
                )
            )
        return mutation
