from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarCatalog
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.floor import ObjectValue, ReceiverFieldStoreValue, TermValue
from sugar_lift_py_tests.outcome import Complete, Completed
from sugar_lift_py_tests.sugar.function_universe_sugar import reduce_block_to_exitset
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class _StoreReceiverField(Sugar):
    receiver: ObjectValue
    value: TermValue

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        return Complete(ReceiverFieldStoreValue(self.receiver, "payload", self.value))


@dataclass(frozen=True)
class _ReadReceiverField(Sugar):
    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        return ctx.temporal.value_for("self").attribute("payload", "test")


def test_receiver_field_store_rebinds_the_same_receiver_for_the_tail():
    """A completed ``self.x = value`` owns the later ``self.x`` projection."""
    receiver = ObjectValue("Renamed", (), identity="receiver-1")
    stored = TermValue(17)
    context = FactoryBuildContext(
        "test.py",
        SugarCatalog(),
        temporal=FactoryBuildContext("test.py", SugarCatalog())
        .temporal.bind_value("self", receiver),
    )

    exits = reduce_block_to_exitset(
        (_StoreReceiverField(receiver, stored), _ReadReceiverField()), context
    ).exits

    assert len(exits) == 1
    assert isinstance(exits[0], Completed)
    assert exits[0].value.entries[-1] is stored
