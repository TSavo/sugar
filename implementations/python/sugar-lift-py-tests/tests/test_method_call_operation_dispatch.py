from dataclasses import dataclass, field

from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.floor.opaque_op_callsite import OpaqueOpCallsite
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.method_call_sugar import MethodCallSugar
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar


@dataclass(frozen=True)
class _FloorSugar(ConstructedTermSugar):
    value: object
    site: object = field(compare=False)

    def desugar(self, ctx=None):
        return Complete(self.value)

    def to_term(self, *, owner: str):
        return self.value.to_term(owner=owner)

    @classmethod
    def witnesses(cls):
        return ()


def test_symbolic_string_compatible_method_uses_floor_owned_dispatch():
    receiver = SymbolicValue(make_var("name"))
    pattern = SymbolicValue(make_var("pattern"))
    sugar = MethodCallSugar(
        _FloorSugar(receiver, "receiver"),
        "startswith",
        (_FloorSugar(pattern, "pattern"),),
        "call-site",
    )

    outcome = sugar.desugar(None)

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, OpaqueOpCallsite)
    assert outcome.value.callee == "startswith"
    assert outcome.value.arg is receiver
    assert outcome.value.extra_args == (pattern,)
    assert isinstance(outcome.value.truth("truth-site"), Complete)
