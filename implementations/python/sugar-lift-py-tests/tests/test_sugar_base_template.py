from __future__ import annotations

import importlib
import inspect
import json
import os
import pkgutil
import subprocess
import sys
from dataclasses import dataclass, fields
from pathlib import Path
from typing import get_args

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome
from sugar_lift_py_tests.sugar.add_sugar import AddSugar
from sugar_lift_py_tests.sugar.bitwise_op_sugar import BitwiseOpSugar
from sugar_lift_py_tests.sugar.map_sugar import MapSugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar, registered_claims
from sugar_lift_py_tests.sugar_body import SugarBody

ROOT = Path(__file__).resolve().parents[1]
PY_TESTS = ROOT


EFFECT_CONSUMER_OVERRIDES: dict[str, str] = {
    "BlockSugar": "folds statement effects through block control-flow composition",
    "DictCompSugar": "binds comprehension variables while reducing element bodies",
    "ListCompSugar": "binds comprehension variables while reducing element bodies",
    "SetCompSugar": "binds comprehension variables while reducing element bodies",
    "TrySugar": "routes Incomplete raise-like effects through handlers/finally",
}

MANUAL_COMPLETE_VALUE_FORCES: dict[str, tuple[str, ...]] = {
    "BuilderCtorSugar": ("items",),
    "ToListSugar": ("receiver",),
}


@dataclass(frozen=True)
class _IncompleteChild:
    effect: RuntimeEffect

    def desugar(self, ctx) -> Outcome:
        del ctx
        return Incomplete(self.effect)


@dataclass(frozen=True)
class _CompleteChild:
    value: object

    def desugar(self, ctx) -> Outcome:
        del ctx
        return Complete(self.value)


@dataclass(frozen=True)
class _TemplateProbeSugar(Sugar):
    operand: SugarBody
    build_called: list[str]
    template_operand_names = ("operand",)

    def _build(self, ctx, *, operand):
        del ctx, operand
        self.build_called.append("called")
        return Complete(_CompleteProbeValue())


@dataclass(frozen=True)
class _CompleteProbeValue:
    pass


def test_sugar_template_method_propagates_incomplete_before_build() -> None:
    effect = RuntimeEffect("template probe effect")
    build_called: list[str] = []
    sugar = _TemplateProbeSugar(
        operand=SugarBody(
            sugar=_IncompleteChild(effect),
            role=SugarRole.TERM,
        ),
        build_called=build_called,
    )

    outcome = sugar.desugar(None)

    assert outcome == Incomplete(effect)
    assert build_called == []


def test_registered_sugars_do_not_override_desugar_outside_named_hook() -> None:
    _import_all_sugar_modules()
    desugar_overrides: list[str] = []
    hook_overrides: dict[str, str] = {}

    for claim in registered_claims():
        cls = claim.build.__self__
        if "desugar" in cls.__dict__:
            desugar_overrides.append(claim.name)
        if "_desugar_with_effects" in cls.__dict__:
            hook_overrides[claim.name] = EFFECT_CONSUMER_OVERRIDES.get(
                claim.name,
                "<missing reason>",
            )

    assert desugar_overrides == []
    assert hook_overrides == EFFECT_CONSUMER_OVERRIDES


def test_registered_sugars_do_not_force_body_operands_outside_template() -> None:
    _import_all_sugar_modules()
    forced_operands: dict[str, tuple[str, ...]] = {}

    for claim in registered_claims():
        cls = claim.build.__self__
        if not dataclass_is_concrete(cls):
            continue
        try:
            source = inspect.getsource(cls)
        except OSError:
            source = ""
        forced = tuple(
            field.name
            for field in fields(cls)
            if _annotation_mentions_sugar_body(field.type)
            and _source_forces_sugar_body(source, field.name)
            and field.name not in (getattr(cls, "template_operand_names", None) or ())
        )
        if forced:
            forced_operands[claim.name] = forced

    assert forced_operands == MANUAL_COMPLETE_VALUE_FORCES


def test_unmigrated_sugar_missing_build_is_a_pyright_error(tmp_path: Path) -> None:
    planted = tmp_path / "planted_missing_build.py"
    planted.write_text(
        "\n".join(
            (
                "from dataclasses import dataclass",
                "from sugar_lift_py_tests.sugar.sugar_base import Sugar",
                "",
                "@dataclass(frozen=True)",
                "class PlantedSugar(Sugar):",
                "    pass",
                "",
                "PlantedSugar().desugar(None)",
                "",
            )
        ),
        encoding="utf-8",
    )

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
        env={**os.environ, "PYTHONPATH": _with_src_on_pythonpath()},
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
    assert "PlantedSugar" in diagnostics
    assert "_build" in diagnostics


def test_add_sugar_receiver_incomplete_emits_typed_effect_without_local_patch() -> None:
    effect = RuntimeEffect(
        "write more Sugar for this AST: owner=python.factory "
        "observed=call-builtin:slice requested=term"
    )
    sugar = AddSugar(
        receiver=SugarBody(_IncompleteChild(effect), SugarRole.TERM),
        operand=SugarBody(_CompleteChild(TermValue(1)), SugarRole.TERM),
        blame="pandas/tests/internals/test_internals.py:1179:29",
    )

    assert "_desugar_with_effects" not in AddSugar.__dict__
    assert sugar.desugar(None) == Incomplete(effect)


def test_map_sugar_receiver_incomplete_emits_typed_effect_from_template() -> None:
    effect = RuntimeEffect(
        "write more Sugar for this AST: owner=python.factory "
        "observed=call-local:typ requested=term"
    )
    sugar = MapSugar(
        receiver=SugarBody(_IncompleteChild(effect), SugarRole.TERM),
        mapper=SugarBody(_CompleteChild(TermValue(1)), SugarRole.TERM),
        blame="pandas/tests/base/test_conversion.py:127:12",
    )

    assert "_desugar_with_effects" not in MapSugar.__dict__
    assert sugar.desugar(None) == Incomplete(effect)


def test_bitwise_op_sugar_left_incomplete_emits_typed_effect_from_template() -> None:
    effect = RuntimeEffect(
        "write more Sugar for this AST: owner=python.factory "
        "observed=call-method:notna requested=term"
    )
    sugar = BitwiseOpSugar(
        operator="&",
        left=SugarBody(_IncompleteChild(effect), SugarRole.TERM),
        right=SugarBody(_CompleteChild(TermValue(1)), SugarRole.TERM),
        blame="pandas/tests/test_sorting.py:300:20",
    )

    assert "_desugar_with_effects" not in BitwiseOpSugar.__dict__
    assert sugar.desugar(None) == Incomplete(effect)


def test_bitwise_op_sugar_right_incomplete_emits_typed_effect_from_template() -> None:
    effect = RuntimeEffect(
        "write more Sugar for this AST: owner=python.factory "
        "observed=call-method:notna requested=term"
    )
    sugar = BitwiseOpSugar(
        operator="&",
        left=SugarBody(_CompleteChild(TermValue(1)), SugarRole.TERM),
        right=SugarBody(_IncompleteChild(effect), SugarRole.TERM),
        blame="pandas/tests/test_sorting.py:300:20",
    )

    assert "_desugar_with_effects" not in BitwiseOpSugar.__dict__
    assert sugar.desugar(None) == Incomplete(effect)


def _import_all_sugar_modules() -> None:
    import sugar_lift_py_tests.sugar as sugar_package

    prefix = sugar_package.__name__ + "."
    for module_info in pkgutil.iter_modules(sugar_package.__path__, prefix):
        if module_info.ispkg:
            continue
        importlib.import_module(module_info.name)


def dataclass_is_concrete(cls: type) -> bool:
    return hasattr(cls, "__dataclass_fields__")


def _annotation_mentions_sugar_body(annotation: object) -> bool:
    if annotation is SugarBody:
        return True
    if isinstance(annotation, str):
        return "SugarBody" in annotation
    return any(_annotation_mentions_sugar_body(arg) for arg in get_args(annotation))


def _source_forces_sugar_body(source: str, field_name: str) -> bool:
    needle = f"complete_value(self.{field_name}.reduce("
    return needle in source


def _run_lift_rpc(project: Path) -> dict:
    env = {
        **os.environ,
        "PYTHONPATH": str(PY_TESTS / "src"),
    }
    request = "\n".join(
        json.dumps(message)
        for message in [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "lift",
                "params": {"workspace_root": str(project), "source_paths": ["."]},
            },
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": {}},
        ]
    )

    completed = subprocess.run(
        [sys.executable, "-m", "sugar_lift_py_tests.lift_rpc", "--rpc"],
        input=request + "\n",
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert completed.returncode == 0, completed.stderr
    responses = [
        json.loads(line) for line in completed.stdout.splitlines() if line.strip()
    ]
    response = next(item for item in responses if item.get("id") == 2)
    assert "error" not in response, response
    return response["result"]


def _with_src_on_pythonpath() -> str:
    return os.pathsep.join((str(ROOT / "src"), os.environ.get("PYTHONPATH", "")))
