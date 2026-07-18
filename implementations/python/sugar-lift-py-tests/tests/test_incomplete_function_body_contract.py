from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from sugar_lift_py_tests.effect import CoverageGapEffect
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory import sugar_constructors
from sugar_lift_py_tests.outcome import Incomplete

_KIT = Path(__file__).resolve().parents[1]
_SCANNER_PATH = _KIT / "scripts" / "factory_zero_tolerance.py"
_SPEC = importlib.util.spec_from_file_location("factory_zero_tolerance", _SCANNER_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_SCANNER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SCANNER)


def test_factory_has_only_sugar_or_factory_panic_construction_results() -> None:
    offenders = _SCANNER.scan_factory(_KIT / "src" / "sugar_lift_py_tests" / "factory")
    third_result_sites = tuple(
        row for row in offenders if row.kind == "non-contract-third-result"
    )

    assert third_result_sites == ()


def test_incomplete_control_flow_body_is_the_factory_panic_arm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incomplete = Incomplete(
        CoverageGapEffect(
            boundary="function-body",
            reason="body reduction needs an owning sugar",
        )
    )

    class IncompleteBody:
        def reduce(self, ctx):
            del ctx
            return incomplete

    class BodyContext:
        def build_body(self, site, role):
            del site, role
            return IncompleteBody()

    body_ctx = BodyContext()
    monkeypatch.setattr(
        sugar_constructors,
        "_ctx_with_formal_binds",
        lambda site, ctx: body_ctx,
    )
    site = SimpleNamespace(
        observed="FunctionDef",
        blame="owner.py:3:0",
        node=SimpleNamespace(body=[SimpleNamespace(lineno=3, col_offset=4)]),
        function_params=lambda: (),
    )

    with pytest.raises(FactoryPanic) as raised:
        sugar_constructors.build_control_flow_body_sugar(site, object())

    assert raised.value.info.owner == "ControlFlowBodySugar"
    assert raised.value.info.observed == "CoverageGapEffect"
    assert raised.value.info.requested == "complete function-body Sugar reduction"
