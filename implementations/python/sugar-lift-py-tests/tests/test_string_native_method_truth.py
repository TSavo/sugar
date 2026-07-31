from sugar_lift_py_tests.floor import CallSiteValue, StringValue, SymbolicValue
from sugar_lift_py_tests.ir import atomic
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.method_call_sugar import MethodCallSugar
from sugar_lift_py_tests.sugar.string_literal_sugar import StringLiteralSugar
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar


class _Site:
    def __init__(self, cid):
        self.cid = cid

    def seal(self):
        return type(
            "Seal",
            (),
            {
                "cid": self.cid,
                "source_cid": "source",
                "start": 0,
                "end": 1,
            },
        )()


class _FixedSugar(ConstructedTermSugar):
    def __init__(self, value, cid):
        self.value = value
        self.site = _Site(cid)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        return Complete(self.value)

    def to_term(self, *, owner):
        return self.value.to_term(owner=owner)


def test_string_receiver_owns_startswith_boolean_return() -> None:
    outcome = MethodCallSugar(
        StringLiteralSugar("_member_", _Site("receiver")),
        "startswith",
        (StringLiteralSugar("_", _Site("prefix")),),
        _Site("call"),
    ).desugar()

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, TrueBoolLiteralSugar)


def test_string_receiver_owns_endswith_boolean_return() -> None:
    outcome = MethodCallSugar(
        StringLiteralSugar("_member_", _Site("receiver")),
        "endswith",
        (StringLiteralSugar("_", _Site("suffix")),),
        _Site("call"),
    ).desugar()

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, TrueBoolLiteralSugar)


def test_symbolic_receiver_cannot_borrow_native_string_return_type() -> None:
    outcome = MethodCallSugar(
        _FixedSugar(SymbolicValue(atomic("receiver", [])), "receiver"),
        "startswith",
        (StringLiteralSugar("_", _Site("prefix")),),
        _Site("call"),
    ).desugar()

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, CallSiteValue)


def test_string_receiver_with_undecided_prefix_stays_untyped() -> None:
    outcome = MethodCallSugar(
        StringLiteralSugar("_member_", _Site("receiver")),
        "startswith",
        (_FixedSugar(SymbolicValue(atomic("prefix", [])), "prefix"),),
        _Site("call"),
    ).desugar()

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, CallSiteValue)
