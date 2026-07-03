from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.factory.factory_audit_row import FactoryAuditRow
from sugar_lift_py_tests.factory.factory_gap_info import FactoryGapInfo
from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.sugar import truthy_assertion_sugar as truthy_module
from sugar_lift_py_tests.sugar.truthy_assertion_sugar import (
    Degraded,
    Projected,
    TruthProjectionDegradation,
    TruthyAssertionSugar,
    _projectable_truth_body,
)
from sugar_lift_py_tests.sugar_body import SugarBody


ROOT = Path(__file__).resolve().parents[1]


class _GapBuildContext:
    import_aliases = {}
    from_imports = {}
    name_resolver = {}
    external_bridge_sink = None

    def build_body(self, node, role):
        info = FactoryGapInfo(
            owner="test",
            blame="test_truthy.py:1:4",
            observed="Name",
            requested="truthy term body",
            fix="write more Floor for truthy body",
            gap_kind="Floor",
            gap_locus="construction",
        )
        raise FactoryGap(
            info,
            FactoryAuditRow(
                role="TERM",
                status="floor-gap",
                observed="Name",
                blame="test_truthy.py:1:4",
                selected=None,
                candidates=[],
                message=info.message,
            ),
        )


class _BodyBuildContext:
    import_aliases = {}
    from_imports = {}
    name_resolver = {}
    external_bridge_sink = None

    def __init__(self, body: SugarBody) -> None:
        self.body = body

    def build_body(self, node, role):
        return self.body


class _DummySugar:
    pass


def _truthy_assert_site() -> SourceFragment:
    site = SourceFragment.from_source(
        "def test_flag(flag):\n    assert flag\n", "test_truthy.py"
    )
    return next(frag for frag in site.walk() if frag.observed == "Assert")


def test_truthy_assertion_lifts_name_fact() -> None:
    report = build_literal_call_report(
        source=("def test_flag(flag):\n" "    assert flag\n"),
        filename="test_truthy.py",
        memento_file="test_truthy.py",
    )

    assert report is not None
    contract = report.payload.ir[0]
    assert contract.source_warrants[0].role == "python.truthy-assertion-sugar"
    assert contract.inv == {
        "kind": "atomic",
        "name": "py.truthy",
        "args": [{"kind": "var", "name": "flag"}],
    }
    assert [row.selected for row in report.payload.factory_walk] == [
        "TruthyAssertionSugar"
    ]
    assert report.payload.factory_walk[0].requested_role == "AssertionSurface"


def test_truthy_prebuild_gap_is_recorded_on_the_sugar() -> None:
    stmt = _truthy_assert_site()

    sugar = TruthyAssertionSugar.build(stmt, _GapBuildContext())

    assert sugar.term_body is None
    assert sugar.degraded_reason == "write more Floor for truthy body"


def test_truthy_projection_degraded_arm_names_crime_owner_shape_replacement() -> None:
    result = _projectable_truth_body(_truthy_assert_site(), _GapBuildContext())

    assert isinstance(result, Degraded)
    assert not isinstance(result, tuple)
    assert result.reason == TruthProjectionDegradation(
        crime="truthy projection degraded before term-body construction",
        owner="TruthyAssertionSugar",
        shape="FactoryGap(owner=test, observed=Name, requested=truthy term body)",
        replacement="write more Floor for truthy body",
        audit_reason="write more Floor for truthy body",
    )


def test_truthy_projection_projected_arm_carries_body_without_reason() -> None:
    body = SugarBody(_DummySugar(), SugarRole.TERM)
    result = _projectable_truth_body(_truthy_assert_site(), _BodyBuildContext(body))

    assert isinstance(result, Projected)
    assert not isinstance(result, tuple)
    assert result.body is body


def test_truthy_build_rejects_legacy_tuple_projection(monkeypatch) -> None:
    monkeypatch.setattr(
        truthy_module,
        "_projectable_truth_body",
        lambda site, ctx: (None, "legacy tuple"),
    )

    with pytest.raises(TypeError) as raised:
        TruthyAssertionSugar.build(_truthy_assert_site(), _GapBuildContext())

    assert str(raised.value) == (
        "truthy projection result must be Projected | Degraded: "
        "owner=TruthyAssertionSugar shape=tuple "
        "replacement=return Projected(body) or Degraded(reason)"
    )


def test_truthy_projection_missing_arm_is_a_pyright_error(tmp_path: Path) -> None:
    planted = tmp_path / "planted_truth_projection.py"
    planted.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "",
                "from dataclasses import dataclass",
                "from typing import Never, NoReturn",
                "",
                "from sugar_lift_py_tests.sugar.truthy_assertion_sugar import (",
                "    Degraded,",
                "    Projected,",
                "    TruthProjectionDegradation,",
                ")",
                "from sugar_lift_py_tests.sugar_body import SugarBody",
                "",
                "@dataclass(frozen=True)",
                "class Pending:",
                "    reason: str",
                "",
                "Projection = Projected | Degraded | Pending",
                "",
                "def consume(result: Projection) -> str:",
                "    if isinstance(result, Projected):",
                "        return type(result.body).__name__",
                "    if isinstance(result, Degraded):",
                "        return result.reason.audit_reason",
                "    return _unhandled(result)",
                "",
                "def _unhandled(result: Never) -> NoReturn:",
                "    raise TypeError(type(result).__name__)",
                "",
                "def make_reason() -> TruthProjectionDegradation:",
                "    return TruthProjectionDegradation(",
                "        crime='planted',",
                "        owner='test',",
                "        shape='Pending',",
                "        replacement='handle Pending',",
                "        audit_reason='planted',",
                "    )",
                "",
                "def make_projected(body: SugarBody) -> Projected:",
                "    return Projected(body)",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{ROOT / 'src'}{os.pathsep}{env.get('PYTHONPATH', '')}"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pyright",
            "--project",
            str(ROOT / "pyrightconfig.json"),
            "--outputjson",
            str(planted),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    diagnostics = "\n".join(
        item["message"] for item in payload.get("generalDiagnostics", ())
    )
    assert "Pending" in diagnostics
    assert "Never" in diagnostics


def test_truthy_assertion_lifts_attribute_fact() -> None:
    report = build_literal_call_report(
        source=("def test_shape(arr):\n" "    assert arr.shape\n"),
        filename="test_truthy.py",
        memento_file="test_truthy.py",
    )

    assert report is not None
    assert report.payload.ir[0].inv == {
        "kind": "atomic",
        "name": "py.truthy",
        "args": [
            {
                "kind": "ctor",
                "name": "py.attr",
                "args": [
                    {"kind": "var", "name": "arr"},
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "String"},
                        "value": "shape",
                    },
                ],
            }
        ],
    }


def test_truthy_assertion_lifts_subscript_fact() -> None:
    report = build_literal_call_report(
        source=("def test_first(values):\n" "    assert values[0]\n"),
        filename="test_truthy.py",
        memento_file="test_truthy.py",
    )

    assert report is not None
    assert report.payload.ir[0].inv == {
        "kind": "atomic",
        "name": "py.truthy",
        "args": [
            {
                "kind": "ctor",
                "name": "py.subscript",
                "args": [
                    {"kind": "var", "name": "values"},
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "Int"},
                        "value": 0,
                    },
                ],
            }
        ],
    }


def test_truthy_assertion_lifts_binop_fact() -> None:
    report = build_literal_call_report(
        source=("def test_total(total):\n" "    assert total + 1\n"),
        filename="test_truthy.py",
        memento_file="test_truthy.py",
    )

    assert report is not None
    assert report.payload.ir[0].inv == {
        "kind": "atomic",
        "name": "py.truthy",
        "args": [
            {
                "kind": "ctor",
                "name": "+",
                "args": [
                    {"kind": "var", "name": "total"},
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "Int"},
                        "value": 1,
                    },
                ],
            }
        ],
    }


def test_truthy_assertion_lifts_xor_binop_fact() -> None:
    report = build_literal_call_report(
        source=(
            "def test_dtype(native_repr, native_dtype, typelessdata):\n"
            "    assert ('dtype' in native_repr) ^ (native_dtype in typelessdata)\n"
        ),
        filename="test_arrayprint.py",
        memento_file="test_arrayprint.py",
    )

    assert report is not None
    assert report.payload.ir[0].inv == {
        "kind": "atomic",
        "name": "py.truthy",
        "args": [
            {
                "kind": "ctor",
                "name": "^",
                "args": [
                    {
                        "kind": "ctor",
                        "name": "py.compare:In",
                        "args": [
                            {
                                "kind": "const",
                                "sort": {
                                    "kind": "primitive",
                                    "name": "String",
                                },
                                "value": "dtype",
                            },
                            {"kind": "var", "name": "native_repr"},
                        ],
                    },
                    {
                        "kind": "ctor",
                        "name": "py.compare:In",
                        "args": [
                            {"kind": "var", "name": "native_dtype"},
                            {"kind": "var", "name": "typelessdata"},
                        ],
                    },
                ],
            }
        ],
    }


def test_truthy_assertion_dispatches_bound_local_object_bool_dunder() -> None:
    report = build_literal_call_report(
        source=(
            "class Truthy:\n"
            "    def __bool__(self):\n"
            "        return True\n"
            "\n"
            "def test_truthy_object():\n"
            "    x = Truthy()\n"
            "    assert x\n"
        ),
        filename="test_truthy_bound_object.py",
        memento_file="test_truthy_bound_object.py",
    )

    assert report is not None
    contract = report.payload.ir[0]
    assert contract.source_warrants[0].role == "python.truthy-assertion-sugar"
    assert contract.inv == _bool_eq(True, True)


def test_truthy_assertion_dispatches_constructor_bound_attribute_object_bool_dunder() -> (
    None
):
    report = build_literal_call_report(
        source=(
            "class Flag:\n"
            "    def __bool__(self):\n"
            "        return True\n"
            "\n"
            "class Box:\n"
            "    def __init__(self, flag):\n"
            "        self.flag = flag\n"
            "\n"
            "def test_box_flag_truthy():\n"
            "    x = Box(Flag())\n"
            "    assert x.flag\n"
        ),
        filename="test_truthy_attribute_object.py",
        memento_file="test_truthy_attribute_object.py",
    )

    assert report is not None
    assert report.payload.ir[0].inv == _bool_eq(True, True)


def test_truthy_assertion_uses_len_fallback_after_missing_bool_dunder() -> None:
    sat = build_literal_call_report(
        source=_sized_truthiness_source(size=1),
        filename="test_truthy_len_sat.py",
        memento_file="test_truthy_len_sat.py",
    )
    unsat = build_literal_call_report(
        source=_sized_truthiness_source(size=0),
        filename="test_truthy_len_unsat.py",
        memento_file="test_truthy_len_unsat.py",
    )

    assert sat is not None
    assert unsat is not None
    sat_inv = sat.payload.ir[0].inv
    unsat_inv = unsat.payload.ir[0].inv
    assert sat_inv == _int_ne(1, 0)
    assert unsat_inv == _int_ne(0, 0)


def test_truthy_assertion_keeps_external_call_truth_as_symbolic_py_truthy() -> None:
    report = build_literal_call_report(
        source=("def test_external(value):\n" "    assert external_call(value)\n"),
        filename="test_truthy_external_call.py",
        memento_file="test_truthy_external_call.py",
    )

    assert report is not None
    assert report.payload.ir[0].inv == {
        "kind": "atomic",
        "name": "py.truthy",
        "args": [
            {
                "kind": "ctor",
                "name": "call:external_call",
                "args": [{"kind": "var", "name": "value"}],
            }
        ],
    }


def test_truthy_assertion_without_bool_or_len_is_a_named_floor_gap() -> None:
    with pytest.raises(FactoryGap) as raised:
        build_literal_call_report(
            source=(
                "class Empty:\n"
                "    pass\n"
                "\n"
                "def test_empty():\n"
                "    x = Empty()\n"
                "    assert x\n"
            ),
            filename="test_truthy_missing_dunders.py",
            memento_file="test_truthy_missing_dunders.py",
        )

    assert raised.value.info == {
        "owner": "TruthyAssertionSugar",
        "blame": "test_truthy_missing_dunders.py:6:4",
        "observed": "Empty.__len__",
        "requested": "constructor-bound method",
        "fix": ("define `__len__` on `Empty` or add the floor that owns this method"),
        "gap_kind": "Constructor",
        "gap_locus": "construction",
    }


def _sized_truthiness_source(*, size: int) -> str:
    return (
        "class Sized:\n"
        "    def __init__(self, n):\n"
        "        self.n = n\n"
        "\n"
        "    def __len__(self):\n"
        "        return self.n\n"
        "\n"
        "def test_sized_truthy():\n"
        f"    x = Sized({size})\n"
        "    assert x\n"
    )


def _bool_eq(actual: bool, expected: bool) -> dict:
    return {
        "kind": "atomic",
        "name": "=",
        "args": [_bool_const(actual), _bool_const(expected)],
    }


def _bool_const(value: bool) -> dict:
    return {
        "kind": "const",
        "sort": {"kind": "primitive", "name": "Bool"},
        "value": value,
    }


def _int_ne(actual: int, expected: int) -> dict:
    return {
        "kind": "atomic",
        "name": "≠",
        "args": [_int_const(actual), _int_const(expected)],
    }


def _int_const(value: int) -> dict:
    return {
        "kind": "const",
        "sort": {"kind": "primitive", "name": "Int"},
        "value": value,
    }
