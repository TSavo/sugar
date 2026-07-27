"""UnaryOp and BoolOp exceptional-exit producer laws.

The corpus witnesses are pandas 3.0.3 source, while the discrimination twins
exercise the native floors directly.  No assertion-manager spelling grants an
operator an exception it cannot establish from source.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from sugar_lift_py_tests.effect.expectation_not_met_effect import (
    ExpectationNotMetEffect,
)
from sugar_lift_py_tests.floor import RaiseValue, SymbolicValue, TermValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import atomic, make_var, not_
from sugar_lift_py_tests.outcome import Complete, ExitSet, Halted
from sugar_lift_py_tests.outcome.exit_set import false_guard, true_guard
from sugar_lift_py_tests.sugar.bool_op_sugar import BoolOpSugar
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.name_sugar import NameSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_py_tests.temporal import TemporalContext
from sugar_lift_py_tests.context import ReduceContext

CORPUS = Path(
    "/Users/tsavo/sugar-defect-drain/.venv/lib/python3.14/site-packages/pandas"
)
UNARY_SITE = CORPUS / "tests/extension/base/ops.py"
BOOLOP_SITE = CORPUS / "tests/generic/test_generic.py"
DEMAND_TABLE_KEY = (
    "blake3-512:0ce7c645a7525f1fe5189b808162b49d3fc3ba3d898bfb3d5086e0f295b8b8d"
    "263fe7f530a6aa34adb125615a21e69fdee249e0314bf199b8f43580375153ab0"
)
MANIFEST_CID = "sha256:a223a4499d0909f22190748b4aca9144e35a58fec31e84cb924e2c25fd3c03d0"
UNARY_SOURCE_CID = (
    "blake3-512:e67b3f17a16e69f16ea8d1e0b19eff3f27f8acb8beac1dcb923066ad5901c039"
    "a6949846351444d20ec05e193006125a7781fe4ef2503e0f8eb6bfebffbc7fca"
)
BOOLOP_SOURCE_CID = (
    "blake3-512:851b7839bb2cdb42bcb34227ea39b4c84e8324ca164a5875283b934ede5935cb4"
    "ce94ecaf08a4e83d608f9c9a676760892b1be24f953f9a1999175d479a8075c"
)


class _Site:
    filename = "pandas-producer-twin.py"
    line = 1
    col = 0
    source = "operator"
    unit = type("_Unit", (), {"source": "~value\n"})()


def test_verified_pandas_303_reproducers_are_content_pinned() -> None:
    assert hashlib.sha256(UNARY_SITE.read_bytes()).hexdigest() == (
        "bd98339ca8660c94faf9afdd8900d382a27c88c7f179a71f2a165b278d2bb66e"
    )
    assert hashlib.sha256(BOOLOP_SITE.read_bytes()).hexdigest() == (
        "cbc5383e8e1545537baedca85a6c62a487d3bea6942bb56e5e0c7479dd2f188d"
    )
    assert (
        "with pytest.raises(TypeError):\n                ~ser" in UNARY_SITE.read_text()
    )
    source = BOOLOP_SITE.read_text()
    assert (
        "with pytest.raises(ValueError, match=msg):\n            obj1 and obj2"
        in source
    )
    assert (
        "with pytest.raises(ValueError, match=msg):\n            obj1 or obj2" in source
    )


def test_shared_table_authenticates_unary_and_complete_boolop_family(tmp_path) -> None:
    root = Path(__file__).resolve().parents[4]
    output = tmp_path / "python-demand-table.json"
    pulled = subprocess.run(
        [
            str(root / "bin/sugarbin"),
            "artifact",
            "pull",
            "--kind",
            "python-demand-table",
            "--content-key",
            DEMAND_TABLE_KEY,
            "--output",
            str(output),
            "--runtime",
            "cpython-3.12.13",
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert pulled.returncode == 0, pulled.stderr
    table = json.loads(output.read_text(encoding="utf-8"))
    assert table["contentKey"] == DEMAND_TABLE_KEY
    assert table["authentication"]["python"] == "cpython-3.12.13"
    assert table["authentication"]["authenticatedCorpusManifestCid"] == MANIFEST_CID
    assert table["authentication"]["pandas"] == "3.0.3"
    assert table["identity"]["fileCount"] == 1421
    sites = {
        (row["useSite"]["sourceCid"], row["useSite"]["startLine"])
        for row in table["rows"]
        if row.get("kind") == "context-manager-demand"
        and row.get("gapKind") is None
        and row.get("targetSymbol") == "pytest.raises"
    }
    assert (UNARY_SOURCE_CID, 257) in sites
    assert {(BOOLOP_SOURCE_CID, 151), (BOOLOP_SOURCE_CID, 153)} <= sites


def test_unary_invert_unknown_operand_is_named_undecided() -> None:
    with pytest.raises(ConstructionPanic) as caught:
        SymbolicValue(make_var("ser")).bitwise_invert(_Site())

    assert caught.value.info.owner == "bitwise_invert"
    assert caught.value.info.observed == "SymbolicValue"
    assert "TypeError" not in str(caught.value.info)


def test_unary_invert_concrete_integer_truthful_twin_folds() -> None:
    outcome = TermValue(3).bitwise_invert(_Site())
    assert outcome == Complete(TermValue(-4))


def test_unary_invert_concrete_bool_truthful_twin_folds() -> None:
    outcome = TermValue(True).bitwise_invert(_Site())
    assert outcome == Complete(TermValue(-2))


def test_unary_invert_concrete_float_lying_twin_has_typed_effect() -> None:
    outcome = TermValue(3.5).bitwise_invert(_Site())
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, RaiseValue)
    assert outcome.value.effect.exception_name == "TypeError"


class _EffectSugar:
    def __init__(self, effect):
        self.effect = effect

    def desugar(self, ctx=None):
        from sugar_lift_py_tests.outcome import Incomplete

        return Incomplete(self.effect)


def _boolop(kind: str, left, right, *, temporal=None):
    return BoolOpSugar(kind, (left, right), _Site()).desugar(
        ReduceContext(temporal or TemporalContext.empty())
    )


def test_and_false_short_circuits_rhs_effect_truthful_twin() -> None:
    result = _boolop(
        "And",
        FalseBoolLiteralSugar(_Site()),
        _EffectSugar(ExpectationNotMetEffect("rhs")),
    )
    assert result == Complete(result.value)
    assert result.value.formula == false_guard()


def test_or_true_short_circuits_rhs_effect_truthful_twin() -> None:
    result = _boolop(
        "Or",
        TrueBoolLiteralSugar(_Site()),
        _EffectSugar(ExpectationNotMetEffect("rhs")),
    )
    assert result == Complete(result.value)
    assert result.value.formula == true_guard()


@pytest.mark.parametrize(
    ("kind", "rhs_guard"),
    (
        ("And", atomic("py.truthy", [make_var("left")])),
        ("Or", not_(atomic("py.truthy", [make_var("left")]))),
    ),
)
def test_undecided_left_makes_rhs_effect_conditional(kind, rhs_guard) -> None:
    temporal = TemporalContext.empty().bind_value(
        "left", SymbolicValue(make_var("left_truth"))
    )
    outcome = _boolop(
        kind,
        NameSugar("left", _Site()),
        _EffectSugar(ExpectationNotMetEffect("rhs")),
        temporal=temporal,
    )

    assert isinstance(outcome, ExitSet)
    halted = [edge for edge in outcome.exits if isinstance(edge, Halted)]
    assert len(halted) == 1
    assert halted[0].guard == rhs_guard
