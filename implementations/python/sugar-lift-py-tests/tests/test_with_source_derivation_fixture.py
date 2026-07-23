from __future__ import annotations

import ast
import importlib
import json
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "with_source_derivation"
EXPECTED_CASES = {
    "normal",
    "raised_unsuppressed",
    "raised_suppressed",
    "exit_fails",
    "enter_fails",
    "returns_from_body",
    "breaks_from_body",
    "continues_from_body",
    "manager_evaluated_once",
    "protocol_resource",
    "protocol_resource_does_not_suppress",
    "lying_claim_does_not_suppress",
    "opaque_native",
}


@pytest.fixture
def fixture_modules(monkeypatch):
    monkeypatch.syspath_prepend(str(FIXTURES))
    for name in (
        "consumer_cases",
        "arbitrary_manager_module",
        "arbitrary_native_module",
    ):
        sys.modules.pop(name, None)
    managers = importlib.import_module("arbitrary_manager_module")
    consumers = importlib.import_module("consumer_cases")
    managers.reset_observations()
    return managers, consumers


def test_truth_set_is_complete_and_contains_no_vendor_enrollment():
    manifest = json.loads((FIXTURES / "cases.json").read_text())
    assert manifest["schemaVersion"] == 1
    assert {case["function"] for case in manifest["cases"]} == EXPECTED_CASES
    assert {case["semanticVerb"] for case in manifest["cases"]} == {
        "EffectBoundary",
        "ProtocolResource",
        "Gap",
    }
    assert manifest["expectedContracts"] == {
        "arbitrary_manager_module.some_manager": {
            "semanticVerb": "EffectBoundary",
            "mode": "Expects",
            "effectKind": "Raise",
            "expectedTypeOperand": {"kind": "formal-argument", "position": 0},
            "binding": "observation-slot",
            "exitDisposition": "matching-effect-only",
        },
        "arbitrary_manager_module.some_resource": {
            "semanticVerb": "ProtocolResource",
            "enter": "total-result-projection",
            "exit": "total",
            "exitDisposition": "NeverSuppresses",
            "binding": "simple-name",
        },
        "arbitrary_manager_module.lying_manager": {
            "semanticVerb": "ProtocolResource",
            "enter": "total-result-projection",
            "exit": "total",
            "exitDisposition": "NeverSuppresses",
            "claimMustBeIgnored": "LyingGuard.claimed_suppression",
        },
        "arbitrary_native_module.some_manager": {
            "semanticVerb": "Gap",
            "gapKind": "source-unavailable",
        },
    }

    consumer = ast.parse((FIXTURES / "consumer_cases.py").read_text())
    imports = [node for node in consumer.body if isinstance(node, ast.Import)]
    assert [(alias.name, alias.asname) for node in imports for alias in node.names] == [
        ("arbitrary_manager_module", "m"),
        ("arbitrary_native_module", "n"),
    ]
    with_functions = {
        node.name
        for node in consumer.body
        if isinstance(node, ast.FunctionDef)
        and any(isinstance(child, ast.With) for child in ast.walk(node))
    }
    assert with_functions == EXPECTED_CASES

    fixture_text = "\n".join(path.read_text() for path in sorted(FIXTURES.glob("*.py")))
    for forbidden in (
        "pytest",
        "pandas",
        "vendor",
        "provider",
        "enrollment",
        "catalog",
    ):
        assert forbidden not in fixture_text


def test_effect_boundary_normal_completion_is_expectation_not_met(fixture_modules):
    managers, consumers = fixture_modules
    with pytest.raises(managers.ExpectationNotMet):
        consumers.normal()


def test_effect_boundary_matching_and_nonmatching_effects(fixture_modules):
    managers, consumers = fixture_modules
    consumers.raised_suppressed()
    with pytest.raises(managers.OtherError):
        consumers.raised_unsuppressed()


def test_exit_failure_supersedes_body_failure(fixture_modules):
    managers, consumers = fixture_modules
    with pytest.raises(managers.ExitFailure) as raised:
        consumers.exit_fails()
    assert isinstance(raised.value.__context__, managers.ExpectedError)


def test_enter_failure_skips_body(fixture_modules):
    managers, consumers = fixture_modules
    body_observation = []
    with pytest.raises(managers.EnterFailure):
        consumers.enter_fails(body_observation)
    assert body_observation == []
    assert [event[0] for event in managers.events] == ["manager", "enter"]


@pytest.mark.parametrize(
    "function_name",
    ["returns_from_body", "breaks_from_body", "continues_from_body"],
)
def test_exit_runs_on_non_exception_control_transfer(fixture_modules, function_name):
    managers, consumers = fixture_modules
    with pytest.raises(managers.ExpectationNotMet):
        getattr(consumers, function_name)()
    assert [event[0] for event in managers.events] == ["manager", "enter", "exit"]
    assert managers.events[-1][1:] == (None, None, None)


def test_manager_expression_is_evaluated_once(fixture_modules):
    managers, consumers = fixture_modules
    consumers.manager_evaluated_once()
    assert managers.manager_evaluations == 1
    assert [event[0] for event in managers.events] == ["manager", "enter", "exit"]


def test_protocol_resource_returns_enter_value_and_never_suppresses(fixture_modules):
    managers, consumers = fixture_modules
    resource = consumers.protocol_resource()
    assert resource.label == "resource-value"
    with pytest.raises(managers.OtherError):
        consumers.protocol_resource_does_not_suppress()
    assert [event[0] for event in managers.events] == [
        "resource-manager",
        "resource-enter",
        "resource-exit",
        "resource-manager",
        "resource-enter",
        "resource-exit",
    ]


def test_lying_suppression_claim_cannot_override_source(fixture_modules):
    managers, consumers = fixture_modules
    assert managers.LyingGuard.claimed_suppression is True
    with pytest.raises(managers.ExpectedError):
        consumers.lying_claim_does_not_suppress()
    assert managers.events[-1][0] == "lying-exit"


def test_opaque_native_manager_remains_typed_loud():
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_source_tree.panic import SugarNotWritten
    from sugar_source_tree.tree import SourceFile

    source = SourceFile(path_source(str(FIXTURES / "consumer_cases.py")))
    function = next(item for item in source.functions() if item.name == "opaque_native")
    with pytest.raises(SugarNotWritten) as caught:
        function.sugar()
    assert type(caught.value).__name__ == "RuntimeSelectedContextManager"
