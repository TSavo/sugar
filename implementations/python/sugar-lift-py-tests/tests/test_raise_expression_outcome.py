from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.factory import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    ExceptionalExitValue,
    ExceptionValue,
    GuardedValue,
    RaiseValue,
    StringValue,
)
from sugar_lift_py_tests.ir import ctor, make_var
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.raise_sugar import RaiseSugar
from sugar_lift_py_tests.sugar_body import SugarBody
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


@dataclass(frozen=True)
class _StaticFloor:
    value: object

    def desugar(self, ctx=None):
        del ctx
        return Complete(self.value)


def _raise_sugar(source: str = "raise make_error()\n") -> RaiseSugar:
    site = SourceFragment.from_source(source, "raise_expression.py").statements()[0]
    return RaiseSugar(
        exception_name="make_error",
        exception_body=None,
        cause_body=None,
        cause_site=None,
        site=site,
        build_context=ReduceContext.root(owner="raise expression test"),
    )


def _source_backed_call(value) -> CallSiteValue:
    return CallSiteValue(
        target_name="make_error",
        arg_values=(),
        parameters=(),
        term=ctor("call:make_error", []),
        body=SugarBody(_StaticFloor(value), SugarRole.TERM),
    )


def test_source_backed_call_returning_exception_constructs_raise() -> None:
    sugar = _raise_sugar()
    exception = ExceptionValue(
        "ValueError",
        (StringValue("bad"),),
        sugar.site,
    )

    outcome = sugar._constructed_raise(
        _source_backed_call(exception),
        sugar.build_context,
        "source-digest",
    )

    assert isinstance(outcome.value, RaiseValue)
    assert outcome.value.effect.exception_name == "ValueError"
    assert outcome.value.exception == exception


def test_source_backed_call_returning_qualified_native_exception_constructs() -> None:
    sugar = _raise_sugar()
    native_exception_call = CallSiteValue(
        target_name="_sqlite3.IntegrityError",
        arg_values=(StringValue("constraint"),),
        parameters=(),
        term=ctor("call:_sqlite3.IntegrityError", []),
        body=None,
    )

    outcome = sugar._constructed_raise(
        _source_backed_call(native_exception_call),
        sugar.build_context,
        "source-digest",
    )

    assert isinstance(outcome.value, RaiseValue)
    assert outcome.value.effect.exception_name == "_sqlite3.IntegrityError"
    assert outcome.value.exception is not None
    assert outcome.value.exception.arguments == (StringValue("constraint"),)


def test_exception_expression_exit_is_preserved_before_outer_raise() -> None:
    sugar = _raise_sugar()
    inner = RaiseEffect("TypeError", "helper.py:4:4", "helper-digest")

    outcome = sugar._constructed_raise(
        _source_backed_call(ExceptionalExitValue(inner)),
        sugar.build_context,
        "outer-digest",
    )

    assert isinstance(outcome.value, RaiseValue)
    assert outcome.value.effect == inner
    assert outcome.value.effect.blame == "helper.py:4:4"


def test_guarded_exception_faces_with_same_terminal_construct_one_raise() -> None:
    sugar = _raise_sugar()
    guarded = GuardedValue(
        make_var("choose_message"),
        ExceptionValue("ValueError", (StringValue("left"),), sugar.site),
        ExceptionValue("ValueError", (StringValue("right"),), sugar.site),
    )

    outcome = sugar._constructed_raise(
        guarded,
        sugar.build_context,
        "source-digest",
    )

    assert isinstance(outcome.value, RaiseValue)
    assert outcome.value.effect.exception_name == "ValueError"


def test_runtime_selected_exception_callable_stays_named_raise_panic() -> None:
    sugar = _raise_sugar("raise selected()\n")
    runtime_selected = CallSiteValue(
        target_name="selected",
        arg_values=(),
        parameters=(),
        term=ctor("call:selected", [make_var("runtime_class")]),
        body=None,
    )

    with pytest.raises(FactoryPanic) as raised:
        sugar._constructed_raise(
            runtime_selected,
            sugar.build_context,
            "source-digest",
        )

    assert raised.value.info.owner == "RaiseSugar"
    assert raised.value.info.observed == "CallSiteValue"
    assert raised.value.info.requested == "constructed exception floor"


def test_raise_expression_witness_truthful_sat_lying_unsat(tmp_path: Path) -> None:
    prefix = (
        "def make_error():\n"
        "    return ValueError('negative')\n"
        "\n"
        "def A(z):\n"
        "    if z < 0:\n"
        "        raise make_error()\n"
        "    return z\n"
        "\n"
    )
    truthful_source = tmp_path / "truthful" / "test_witness.py"
    lying_source = tmp_path / "lying" / "test_witness.py"
    truthful_source.parent.mkdir(parents=True)
    lying_source.parent.mkdir(parents=True)
    truthful_source.write_text(
        prefix + "def test_a():\n    assert A(2) == 2\n",
        encoding="utf-8",
    )
    lying_source.write_text(
        prefix + "def test_a():\n    assert A(2) == 3\n",
        encoding="utf-8",
    )

    truthful = run_source_through_real_solver(
        truthful_source.parent,
        truthful_source.read_text(encoding="utf-8"),
    )
    lying = run_source_through_real_solver(
        lying_source.parent,
        lying_source.read_text(encoding="utf-8"),
    )

    assert "RaiseSugar" in truthful.selected_sugars
    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"
