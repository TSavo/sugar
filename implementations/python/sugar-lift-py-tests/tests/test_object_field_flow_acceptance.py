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
from sugar_source_tree.binding_provenance import BindingProvenanceGap
from sugar_source_tree.binding_state import SubstitutionTraceBuilderV1
from sugar_source_tree.nodes import _SUBSTITUTION_TRACE_BUILDER
from sugar_source_tree.backend import Child, Children, Leaf, materialize
from sugar_source_tree.shadow import ShadowNode, _handle_of
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


def _object_states(path: Path, function_name: str):
    function = _functions(path)[function_name]
    owner = function.fragment.seal().cid
    substituted = function.substitute(
        {_SUBSTITUTION_TRACE_BUILDER: SubstitutionTraceBuilderV1(owner)}
    )
    return [
        node for node in substituted.walk() if node.kind == "ObjectPlaceStateV1"
    ]


def test_object_and_field_versions_reresolve_and_distinct_objects_do_not_collide():
    first = _object_states(FIXTURES / "version_flow.py", "truthful")
    second = _object_states(FIXTURES / "version_flow.py", "truthful")
    assert first and second
    assert first[-1].object_identity_cid == second[-1].object_identity_cid
    assert first[-1].version_cids == second[-1].version_cids
    first[-1].validate_identity()
    second[-1].validate_identity()

    distinct = _object_states(FIXTURES / "distinct_version_flow.py", "truthful")
    identities = {state.object_identity_cid for state in distinct}
    coordinates = {state.object_coordinate.cid for state in distinct}
    assert len(identities) == 2
    assert len(coordinates) == 2


def test_a_type_name_does_not_admit_a_lying_object_identity():
    state = _object_states(FIXTURES / "store_then_read.py", "truthful")[0]
    forged = _forge_state(state, object_identity_cid="blake3-512:stale")
    with pytest.raises(BindingProvenanceGap, match="object place identity CID mismatch"):
        forged.validate_identity()


def test_unmatched_field_version_is_loud_before_projection():
    state = next(
        state
        for state in _object_states(FIXTURES / "store_then_read.py", "truthful")
        if state.selectors
    )
    forged = _forge_state(
        state,
        version_cids=("blake3-512:stale", *state.version_cids[1:]),
    )
    with pytest.raises(BindingProvenanceGap, match="field version CID mismatch"):
        forged.field(state.selectors[0])


def test_branch_join_projects_both_authenticated_field_faces(tmp_path):
    path = tmp_path / "both_faces.py"
    path.write_text(
        "class Vessel:\n    pass\n\n"
        "def both_faces():\n"
        "    flag = True\n"
        "    item = Vessel()\n"
        "    if flag:\n"
        "        item.payload = 3\n"
        "    else:\n"
        "        item.payload = 8\n"
        "    return item.payload\n"
    )
    function = _functions(path)["both_faces"]
    substituted = function.substitute(
        {
            _SUBSTITUTION_TRACE_BUILDER: SubstitutionTraceBuilderV1(
                function.fragment.seal().cid
            )
        }
    )
    returned = next(node for node in substituted.walk() if node.kind == "Return")
    assert returned.value.kind == "IfExp"
    assert returned.value.body.kind == "ConstructedValueProjectionV1"
    assert returned.value.body.base.kind == "Constant"
    assert returned.value.orelse.kind == "ConstructedValueProjectionV1"
    assert returned.value.orelse.base.kind == "Constant"


def test_branch_join_with_one_unproved_field_face_stays_loud(tmp_path):
    path = tmp_path / "missing_face.py"
    path.write_text(
        "class Vessel:\n    pass\n\n"
        "def missing_face():\n"
        "    flag = True\n"
        "    item = Vessel()\n"
        "    if flag:\n"
        "        item.payload = 3\n"
        "    return item.payload\n"
    )
    function = _functions(path)["missing_face"]
    substituted = function.substitute(
        {
            _SUBSTITUTION_TRACE_BUILDER: SubstitutionTraceBuilderV1(
                function.fragment.seal().cid
            )
        }
    )
    returned = next(node for node in substituted.walk() if node.kind == "Return")
    assert returned.value.kind == "Attribute"


@pytest.mark.parametrize(
    ("class_name", "left_name", "right_name", "field"),
    [("Vessel", "left", "right", "payload"), ("Capsule", "first", "second", "marker")],
)
def test_opaque_call_invalidates_only_the_exposed_object(
    tmp_path, class_name, left_name, right_name, field
):
    path = tmp_path / f"selective_{class_name}.py"
    path.write_text(
        f"class {class_name}:\n    pass\n\n"
        f"def boundary(mutator):\n"
        f"    {left_name} = {class_name}()\n"
        f"    {right_name} = {class_name}()\n"
        f"    {left_name}.{field} = 7\n"
        f"    {right_name}.{field} = 11\n"
        f"    mutator({left_name})\n"
        f"    observed = {left_name}.{field}\n"
        f"    return {right_name}.{field}\n"
    )
    function = _functions(path)["boundary"]
    substituted = function.substitute(
        {_SUBSTITUTION_TRACE_BUILDER: SubstitutionTraceBuilderV1(function.fragment.seal().cid)}
    )
    returned = next(node for node in substituted.walk() if node.kind == "Return")
    assert returned.value.kind == "ConstructedValueProjectionV1"
    states = [node for node in substituted.walk() if node.kind == "ObjectPlaceStateV1"]
    by_identity = {state.object_identity_cid: state for state in states}
    assert len({state.object_identity_cid for state in states}) == 2
    assert any(state.invalidated_by_opaque_call for state in by_identity.values())
    assert any(not state.invalidated_by_opaque_call for state in by_identity.values())


def test_opaque_result_mints_occurrence_identity_without_fields():
    path = FIXTURES / "opaque_alias.py"
    function = _functions(path)["read_through_opaque_alias"]
    substituted = function.substitute(
        {_SUBSTITUTION_TRACE_BUILDER: SubstitutionTraceBuilderV1(function.fragment.seal().cid)}
    )
    states = [node for node in substituted.walk() if node.kind == "OpaqueObjectStateV1"]
    assert states
    wire = states[-1].object_coordinate.wire()
    assert wire["kind"] == "opaque-object-coordinate"
    assert not ({"fields", "behavior", "class", "type"} & set(wire))


def test_unknown_place_selector_kind_is_typed_loud():
    from sugar_lift_py_tests.floor.place_assign_value import PlaceAssignValue
    from sugar_lift_py_tests.floor import TermValue

    malformed = PlaceAssignValue(TermValue(1), "future-selector", 0, TermValue(2))
    with pytest.raises(ValueError, match="unknown place selector kind"):
        malformed.to_term(owner="lying-selector")


@pytest.mark.parametrize(
    "member",
    [
        "def __setattr__(self, name, value):\n        pass",
        "@property\n    def payload(self):\n        return 1",
    ],
    ids=("dynamic-setattr", "descriptor"),
)
def test_custom_dispatch_stays_loud_without_constructed_behavior(tmp_path, member):
    path = tmp_path / "dispatch.py"
    path.write_text(
        "class Vessel:\n    "
        + member
        + "\n\ndef boundary():\n    item = Vessel()\n"
        "    item.payload = 7\n    return item.payload\n"
    )
    assert _is_typed_loud(_outcome_or_panic(path, "boundary"))


def test_non_admitted_class_call_keeps_ordinary_call_construction(tmp_path):
    path = tmp_path / "decorated_class.py"
    path.write_text(
        "def decorate(cls):\n"
        "    return cls\n\n"
        "@decorate\n"
        "class Row:\n"
        "    pass\n\n"
        "def boundary():\n"
        "    return Row('path', 7)\n"
    )

    # Object identity admission must not install a constructor-binding path on
    # an ordinary call whose allocation behavior is not constructed.
    _outcome_or_panic(path, "boundary")


def test_custom_setitem_receiver_stays_loud(tmp_path):
    path = tmp_path / "setitem.py"
    path.write_text(
        "class Vessel:\n"
        "    def __setitem__(self, key, value):\n"
        "        pass\n\n"
        "def boundary():\n"
        "    item = Vessel()\n"
        "    item[0] = 7\n"
        "    return item[0]\n"
    )
    assert _is_typed_loud(_outcome_or_panic(path, "boundary"))


def test_plain_object_without_setitem_stays_loud(tmp_path):
    path = tmp_path / "plain_object_subscript.py"
    path.write_text(
        "class Vessel:\n    pass\n\n"
        "def boundary():\n"
        "    item = Vessel()\n"
        "    item[0] = 7\n"
        "    return item[0]\n"
    )
    assert _is_typed_loud(_outcome_or_panic(path, "boundary"))


def test_out_of_range_list_store_stays_loud(tmp_path):
    path = tmp_path / "out_of_range_list.py"
    path.write_text(
        "def boundary():\n"
        "    item = []\n"
        "    item[0] = 7\n"
        "    return item[0]\n"
    )
    assert _is_typed_loud(_outcome_or_panic(path, "boundary"))


def test_object_occurrence_constructs_once_then_projects_testimony(monkeypatch):
    from sugar_source_tree.nodes import Call

    original = Call._construct_sugar
    constructions = 0

    def counted(self):
        nonlocal constructions
        constructions += 1
        return original(self)

    monkeypatch.setattr(Call, "_construct_sugar", counted)
    outcome = _outcome_or_panic(FIXTURES / "store_then_read.py", "truthful")
    assert not _is_typed_loud(outcome)
    assert constructions == 1


def test_stored_expression_constructs_once_then_projects_testimony(
    tmp_path, monkeypatch
):
    from sugar_source_tree.nodes import BinOp

    path = tmp_path / "stored_call_once.py"
    path.write_text(
        "class Vessel:\n    pass\n\n"
        "def boundary():\n"
        "    item = Vessel()\n"
        "    item.payload = 3 + 4\n"
        "    return item.payload\n"
    )
    original = BinOp._construct_sugar
    constructions = 0

    def counted(self):
        nonlocal constructions
        constructions += 1
        return original(self)

    monkeypatch.setattr(BinOp, "_construct_sugar", counted)
    outcome = _outcome_or_panic(path, "boundary")
    assert not _is_typed_loud(outcome)
    assert constructions == 1


def _forge_state(state, **overrides):
    values = {
        "object_coordinate": state.object_coordinate,
        "class_definition_cid": state.class_definition_cid,
        "construction_testimony": state.construction_testimony,
        "constructed_value": state.constructed_value,
        "object_identity_cid": state.object_identity_cid,
        "base": state.base,
        "selectors": state.selectors,
        "values": state.values,
        "value_testimonies": state.value_testimonies,
        "version_cids": state.version_cids,
        "version_records": state.version_records,
        "prior_version_cids": state.prior_version_cids,
        "store_occurrence_cids": state.store_occurrence_cids,
        "invalidated_by_opaque_call": state.invalidated_by_opaque_call,
    }
    values.update(overrides)
    return materialize(
        state.unit,
        ShadowNode(
            "ObjectPlaceStateV1",
            state.span,
            (
                ("object_coordinate", Leaf(values["object_coordinate"])),
                ("class_definition_cid", Leaf(values["class_definition_cid"])),
                ("construction_testimony", Leaf(values["construction_testimony"])),
                ("constructed_value", Leaf(values["constructed_value"])),
                ("object_identity_cid", Leaf(values["object_identity_cid"])),
                ("base", Child(_handle_of(values["base"]))),
                ("selectors", Leaf(values["selectors"])),
                (
                    "values",
                    Children(tuple(_handle_of(item) for item in values["values"])),
                ),
                ("value_testimonies", Leaf(values["value_testimonies"])),
                ("version_cids", Leaf(values["version_cids"])),
                ("version_records", Leaf(values["version_records"])),
                ("prior_version_cids", Leaf(values["prior_version_cids"])),
                ("store_occurrence_cids", Leaf(values["store_occurrence_cids"])),
                ("invalidated_by_opaque_call", Leaf(values["invalidated_by_opaque_call"])),
            ),
        ),
        state.reporter,
    )
