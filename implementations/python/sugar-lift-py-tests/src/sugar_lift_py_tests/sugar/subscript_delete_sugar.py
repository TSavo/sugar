from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import ArrayLiteral, BoundVar, FloorValue, SupportValue
from sugar_lift_py_tests.operations import DelItemOperation, perform_operation
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import inert_statement_return_witness
from sugar_lift_py_tests.sugar.witnesses import SugarWitnessPair, WitnessSource
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class _CompletedFloorBody:
    value: FloorValue

    def desugar(self, ctx) -> Outcome:
        del ctx
        return Complete(self.value)


@dataclass(frozen=True)
class SubscriptDeleteSugar(Sugar, role=SugarRole.STATEMENT):
    receiver: SugarBody
    receiver_name: str | None
    index: SugarBody
    blame: str

    def __post_init__(self) -> None:
        if not isinstance(self.receiver, SugarBody):
            raise TypeError("SubscriptDeleteSugar receiver must be factory-built")
        if not isinstance(self.index, SugarBody):
            raise TypeError("SubscriptDeleteSugar index must be factory-built")

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Delete":
            return False
        targets = site.delete_targets()
        return len(targets) == 1 and targets[0].observed == "Subscript"

    @classmethod
    def witnesses(cls) -> tuple[SugarWitnessPair, SugarWitnessPair]:
        prefix = (
            "def A(z):\n"
            "    xs = [1, 2, 3]\n"
            "    del xs[1]\n"
            "    return xs[1]\n"
            "\n"
        )
        return (
            SugarWitnessPair(
                name="subscript_delete_post_state_read",
                owner_sugar=cls.__name__,
                family="subscript-mutation",
                truthful=WitnessSource(
                    source=prefix + "def test_a():\n    assert A(0) == 3\n",
                    expected="sat",
                ),
                lying=WitnessSource(
                    source=prefix + "def test_a():\n    assert A(0) == 2\n",
                    expected="unsat",
                ),
            ),
            inert_statement_return_witness(
                name="subscript_delete_dunder_return",
                owner_sugar=cls.__name__,
                prefix=(
                    "class C:\n"
                    "    def __delitem__(self, index):\n"
                    "        return None\n"
                    "\n"
                ),
                statement="c = C()\ndel c[0]",
            ),
        )

    @classmethod
    def build(cls, site, ctx) -> "SubscriptDeleteSugar":
        targets = site.delete_targets()
        if len(targets) != 1 or targets[0].observed != "Subscript":
            raise TypeError("SubscriptDeleteSugar claim built a non-subscript delete")
        target = targets[0]
        return cls(
            receiver=ctx.build_body(target.subscript_receiver(), SugarRole.TERM),
            receiver_name=(
                target.subscript_receiver().name_id()
                if target.subscript_receiver().observed == "Name"
                else None
            ),
            index=ctx.build_body(target.subscript_index(), SugarRole.TERM),
            blame=site.blame,
        )

    def _build(self, ctx) -> Outcome:
        receiver_outcome = self.receiver.reduce(ctx)
        if isinstance(receiver_outcome, Incomplete):
            return receiver_outcome
        index_outcome = self.index.reduce(ctx)
        if isinstance(index_outcome, Incomplete):
            return index_outcome

        mutation = perform_operation(
            owner="SubscriptDeleteSugar",
            blame=self.blame,
            receiver=complete_value(
                receiver_outcome, owner="SubscriptDeleteSugar receiver"
            ),
            operation=DelItemOperation(
                index=complete_value(index_outcome, owner="SubscriptDeleteSugar index"),
                owner="SubscriptDeleteSugar",
                blame=self.blame,
            ),
            ctx=ctx,
        )
        if isinstance(mutation, Incomplete):
            return mutation
        mutated = complete_value(mutation, owner="SubscriptDeleteSugar mutation")
        if isinstance(mutated, ArrayLiteral) and self.receiver_name is not None:
            return Complete(
                BoundVar(
                    self.receiver_name,
                    SugarBody(_CompletedFloorBody(mutated), SugarRole.TERM),
                    scope=ctx,
                )
            )
        return Complete(SupportValue())
