from __future__ import annotations

import ast
import copy
import json
from pathlib import Path
import runpy

import pytest

from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.effect.runtime_effect import RuntimeEffect
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.panic import SourceTreePanic
from sugar_source_tree.tree import SourceFile


FIXTURES = Path(__file__).parent / "fixtures" / "object_field_flow"
MATRIX = json.loads((FIXTURES / "verdict_matrix.json").read_text())
POSITIVE_IDS = {
    "store-then-read",
    "distinct-objects",
    "authenticated-alias",
    "version-flow",
    "distinct-version-flow",
}
LOUD_IDS = {"symbolic-receiver", "opaque-mutation", "opaque-alias"}
FORBIDDEN_MECHANISM_CALLS = {"getattr", "setattr", "hasattr", "id", "type", "isinstance"}


def _functions(path: Path):
    return {function.name: function for function in SourceFile(path_source(path)).functions()}


def _outcome_or_panic(path: Path, function_name: str):
    try:
        return _functions(path)[function_name].sugar().desugar()
    except (ConstructionPanic, SourceTreePanic) as panic:
        return panic


def _is_typed_loud(result) -> bool:
    if isinstance(result, (ConstructionPanic, Incomplete, SourceTreePanic)):
        return True
    value = getattr(result, "value", None)
    record = getattr(value, "record", None)
    statements = getattr(record, "statements", ())
    return any(
        isinstance(statement, RuntimeEffect)
        or (
            isinstance(statement, Incomplete)
            and isinstance(statement.effect, RuntimeEffect)
        )
        for statement in statements
    )


class _RoleNormalizer(ast.NodeTransformer):
    def __init__(self):
        self.names: dict[str, str] = {}
        self.attrs: dict[str, str] = {}

    def _name(self, spelling: str) -> str:
        return self.names.setdefault(spelling, f"name{len(self.names)}")

    def visit_FunctionDef(self, node):
        node.name = "function"
        return self.generic_visit(node)

    def visit_arg(self, node):
        node.arg = self._name(node.arg)
        return self.generic_visit(node)

    def visit_Name(self, node):
        node.id = self._name(node.id)
        return self.generic_visit(node)

    def visit_Attribute(self, node):
        node.attr = self.attrs.setdefault(node.attr, f"field{len(self.attrs)}")
        return self.generic_visit(node)


def _normalized_function(module: ast.Module, name: str) -> str:
    function = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    normalized = _RoleNormalizer().visit(copy.deepcopy(function))
    return ast.dump(ast.fix_missing_locations(normalized), include_attributes=False)


def test_verdict_matrix_is_closed_and_names_every_required_invariant():
    assert MATRIX["schema"] == "object-field-flow-acceptance-v1"
    cases = MATRIX["cases"]
    assert {case["id"] for case in cases} == POSITIVE_IDS | LOUD_IDS
    assert len(cases) == 8
    requirements = {item for case in cases for item in case["requires"]}
    assert {
        "content-addressed-object-identity",
        "construction-occurrence-discrimination",
        "no-spelling-identity",
        "authenticated-alias-equivalence",
        "immutable-field-version-chain",
        "read-snapshot-stability",
        "no-cross-object-version-collision",
        "single-temporal-binding-model",
        "no-symbolic-receiver-identity",
        "opaque-call-invalidates-field-knowledge",
        "alias-requires-construction-testimony",
        "no-fabricated-state",
    } <= requirements


@pytest.mark.parametrize(
    "case",
    [case for case in MATRIX["cases"] if case["id"] in POSITIVE_IDS],
    ids=lambda case: case["id"],
)
def test_python_reference_discriminates_truthful_and_lying_twins(case):
    namespace = runpy.run_path(FIXTURES / case["file"])
    for names in (case["canonical"], case["renamed"]):
        namespace[names["truthful"]]()
        with pytest.raises(AssertionError):
            namespace[names["lying"]]()


@pytest.mark.parametrize("case", MATRIX["cases"], ids=lambda case: case["id"])
def test_fixtures_are_renamed_structural_twins_without_name_or_vendor_authority(case):
    path = FIXTURES / case["file"]
    source = path.read_text()
    module = ast.parse(source, filename=str(path))
    assert not any(
        isinstance(node, (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal))
        for node in ast.walk(module)
    )
    called_names = {
        node.func.id
        for node in ast.walk(module)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert called_names.isdisjoint(FORBIDDEN_MECHANISM_CALLS)
    assert not any(
        isinstance(node, ast.Constant) and isinstance(node.value, str)
        for node in ast.walk(module)
    )

    canonical = case["canonical"]
    renamed = case["renamed"]
    if isinstance(canonical, dict):
        for verdict in ("truthful", "lying"):
            assert _normalized_function(module, canonical[verdict]) == _normalized_function(
                module, renamed[verdict]
            )
    else:
        assert _normalized_function(module, canonical) == _normalized_function(module, renamed)


@pytest.mark.parametrize(
    "case",
    [case for case in MATRIX["cases"] if case["id"] in POSITIVE_IDS],
    ids=lambda case: case["id"],
)
@pytest.mark.xfail(
    strict=True,
    reason="acceptance red: construction-authoritative object/place identity is not implemented",
)
def test_positive_object_field_flow_acceptance_is_not_typed_loud(case):
    path = FIXTURES / case["file"]
    for names in (case["canonical"], case["renamed"]):
        for function_name in names.values():
            result = _outcome_or_panic(path, function_name)
            assert not _is_typed_loud(result), result


@pytest.mark.parametrize(
    "case",
    [case for case in MATRIX["cases"] if case["id"] in LOUD_IDS],
    ids=lambda case: case["id"],
)
def test_unauthenticated_object_field_flow_stays_typed_loud(case):
    path = FIXTURES / case["file"]
    for function_name in (case["canonical"], case["renamed"]):
        result = _outcome_or_panic(path, function_name)
        assert _is_typed_loud(result), result
