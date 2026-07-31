"""The enum ``_ignore_`` string pipeline is owned by exact string Floors.

CPython 3.12.13 ``Lib/enum.py`` spells the path as::

    if isinstance(value, str):
        value = value.replace(',', ' ').split()

The type test may select a face, but it cannot manufacture string-method
authority.  ``StringValue`` owns the true face; every other receiver stays an
opaque call coordinate and therefore cannot become iterable by spelling.
"""

from __future__ import annotations

from sugar_lift_py_tests.floor import CallSiteValue, StringValue, SymbolicValue
from sugar_lift_py_tests.floor.array_literal import ArrayLiteral
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import ctor, make_var
from sugar_lift_py_tests.operations.iterator_operation import IteratorOperation
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.method_call_sugar import MethodCallSugar
from sugar_lift_py_tests.sugar.string_literal_sugar import StringLiteralSugar
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar


class _Site:
    def __init__(self, cid: str):
        self.cid = cid

    def seal(self):
        return type(
            "Seal",
            (),
            {"cid": self.cid, "source_cid": "cpython-enum", "start": 0, "end": 1},
        )()

    def __str__(self) -> str:
        return f"Lib/enum.py:{self.cid}"


class _FixedSugar(ConstructedTermSugar):
    def __init__(self, value, cid: str):
        self.value = value
        self.site = _Site(cid)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        return Complete(self.value)

    def to_term(self, *, owner: str):
        return self.value.to_term(owner=owner)


def _literal(value: str, cid: str) -> StringLiteralSugar:
    return StringLiteralSugar(value, _Site(cid))


def _replace_then_split(receiver: ConstructedTermSugar):
    replace = MethodCallSugar(
        receiver,
        "replace",
        (_literal(",", "comma"), _literal(" ", "space")),
        _Site("428:28"),
    )
    return MethodCallSugar(replace, "split", (), _Site("428:51")).desugar()


def test_enum_ignore_ground_string_type_face_is_already_decided() -> None:
    """The enum failure is after the type test, not missing true refinement."""
    outcome = StringValue("left,right").python_isinstance(
        "str", ctor("python:type", ()), _Site("427:19")
    )

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, TrueBoolLiteralSugar)


def test_enum_ignore_ground_string_replace_then_split_is_exact() -> None:
    """Truthful arm: ``replace`` must preserve the StringValue needed by split."""
    outcome = _replace_then_split(_literal("left,right", "value"))

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, ArrayLiteral)
    assert outcome.value.items == (StringValue("left"), StringValue("right"))


def test_enum_ignore_false_face_cannot_borrow_string_iterability() -> None:
    """Lying arm: an untyped receiver keeps both calls bodyless and loop-loud."""
    outcome = _replace_then_split(
        _FixedSugar(SymbolicValue(make_var("enum_ignore_value")), "value")
    )

    assert isinstance(outcome, Complete)
    split = outcome.value
    assert isinstance(split, CallSiteValue)
    assert split.target_name == "split"
    assert split.body is None
    replace = split.runtime_dispatch_receiver
    assert isinstance(replace, CallSiteValue)
    assert replace.target_name == "replace"
    assert replace.body is None

    try:
        IteratorOperation(
            owner="LoopRecurrenceSugar", blame="Lib/enum.py:540:15"
        ).submit(split, None)
    except ConstructionPanic as exc:
        assert "observed=CallSiteValue requested=iter_with" in str(exc)
    else:
        raise AssertionError("bodyless split acquired iterable authority")
