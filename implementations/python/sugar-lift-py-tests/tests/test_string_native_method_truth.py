from sugar_source_tree.spans import LineColSpan

from sugar_lift_py_tests.floor import CallSiteValue, StringValue, SymbolicValue
from sugar_lift_py_tests.ir import atomic
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.method_call_sugar import MethodCallSugar
from sugar_lift_py_tests.sugar.string_literal_sugar import StringLiteralSugar
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar


_SOURCE_CID = "blake3-512:" + "5" * 128
_COLUMNS: dict[str, int] = {}


class _Site:
    """A source-fragment stand-in that carries a real coordinate.

    An occurrence names its site by its ``SourceFragmentCoordinateV1``
    (#7808): a source CID plus a line/column span, one span per site name.
    """

    def __init__(self, cid):
        self.cid = cid
        column = _COLUMNS.setdefault(cid, len(_COLUMNS))
        self.source_cid = _SOURCE_CID
        self.line_col_span = LineColSpan(1, column, 1, column + 1)

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
        return ExitSet.completed(self.value)

    def to_term(self, *, owner):
        return self.value.to_term(owner=owner)


def test_string_receiver_owns_startswith_boolean_return() -> None:
    outcome = MethodCallSugar(
        StringLiteralSugar("_member_", _Site("receiver")),
        "startswith",
        (StringLiteralSugar("_", _Site("prefix")),),
        _Site("call"),
    ).desugar()

    assert isinstance(outcome.completed_value(), TrueBoolLiteralSugar)


def test_string_receiver_owns_endswith_boolean_return() -> None:
    outcome = MethodCallSugar(
        StringLiteralSugar("_member_", _Site("receiver")),
        "endswith",
        (StringLiteralSugar("_", _Site("suffix")),),
        _Site("call"),
    ).desugar()

    assert isinstance(outcome.completed_value(), TrueBoolLiteralSugar)


def test_symbolic_receiver_cannot_borrow_native_string_return_type() -> None:
    outcome = MethodCallSugar(
        _FixedSugar(SymbolicValue(atomic("receiver", [])), "receiver"),
        "startswith",
        (StringLiteralSugar("_", _Site("prefix")),),
        _Site("call"),
    ).desugar()

    assert isinstance(outcome.completed_value(), CallSiteValue)


def test_string_receiver_with_undecided_prefix_stays_untyped() -> None:
    outcome = MethodCallSugar(
        StringLiteralSugar("_member_", _Site("receiver")),
        "startswith",
        (_FixedSugar(SymbolicValue(atomic("prefix", [])), "prefix"),),
        _Site("call"),
    ).desugar()

    # ``str.startswith`` raises TypeError for a prefix that is not a str or
    # tuple: over an undecided prefix the call may raise, never total.
    from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted

    assert isinstance(outcome, ExitSet)
    (completed,) = [face for face in outcome.exits if isinstance(face, Completed)]
    assert isinstance(completed.value, CallSiteValue)
    assert any(isinstance(face, Halted) for face in outcome.exits)
