from __future__ import annotations

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.function_universe_sugar import reduce_block_to_exitset
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar


class _CaptureContext(Sugar):
    def __init__(self, seen: list[object]):
        self.seen = seen

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        self.seen.append(ctx)
        return Complete(TrueBoolLiteralSugar(site="capture"))


def test_explicit_reduction_context_reaches_first_statement_unchanged() -> None:
    explicit = ReduceContext.root(owner="explicit-context-twin")
    seen: list[object] = []

    reduce_block_to_exitset((_CaptureContext(seen),), explicit)

    assert seen == [explicit]
    assert seen[0] is explicit


def test_none_entry_is_normalized_before_first_statement() -> None:
    seen: list[object] = []

    reduce_block_to_exitset((_CaptureContext(seen),), None)

    assert len(seen) == 1
    assert isinstance(seen[0], ReduceContext)
