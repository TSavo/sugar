from __future__ import annotations

import ast
import copy
import json
from pathlib import Path
import runpy

import pytest

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.effect.runtime_effect import RuntimeEffect
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_source_tree.panic import SourceTreePanic
from sugar_source_tree.binding_provenance import BindingProvenanceGap
from sugar_source_tree.binding_state import SubstitutionTraceBuilderV1
from sugar_source_tree.nodes import _SUBSTITUTION_TRACE_BUILDER
from sugar_source_tree.backend import Child, Leaf, materialize
from sugar_source_tree.shadow import ShadowNode, _handle_of

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
FORBIDDEN_MECHANISM_CALLS = {
    "getattr",
    "setattr",
    "hasattr",
    "id",
    "type",
    "isinstance",
}


def _functions(path: Path):
    # Construction opens through the one door: a tree opened bare has no
    # construction context, and every Call that consults it refuses by name
    # (``BareConstructionDoor``).
    return {
        function.name: function
        for function in open_source_file_for_construction(
            path, root=path.parent
        ).functions()
    }


def _outcome_or_panic(path: Path, function_name: str):
    try:
        return _functions(path)[function_name].sugar().desugar()
    except (ConstructionPanic, SourceTreePanic) as panic:
        return panic


def _is_typed_loud(result) -> bool:
    if isinstance(result, (ConstructionPanic, SourceTreePanic)):
        return True
    if isinstance(result, ExitSet) and result.exits and result.halts() == result.exits:
        return True
    value = result.completed_value() if isinstance(result, ExitSet) else None
    record = getattr(value, "record", None)
    statements = getattr(record, "statements", ())
    return any(
        isinstance(statement, RuntimeEffect)
        or (
            isinstance(statement, ExitSet)
            and statement.halts() == statement.exits
            and any(isinstance(halt.effect, RuntimeEffect) for halt in statement.halts())
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
            assert _normalized_function(
                module, canonical[verdict]
            ) == _normalized_function(module, renamed[verdict])
    else:
        assert _normalized_function(module, canonical) == _normalized_function(
            module, renamed
        )


@pytest.mark.parametrize(
    "case",
    [case for case in MATRIX["cases"] if case["id"] in POSITIVE_IDS],
    ids=lambda case: case["id"],
)
def test_positive_object_field_flow_acceptance_is_not_typed_loud(case):
    """The truthful twin is answered, never loud.  The lying twin's assert
    fails in Python on every run (``test_python_reference_discriminates_
    truthful_and_lying_twins``): where the lift decides the reads it states
    exactly that -- every arm a named ``AssertionError`` -- which is the
    answer, not loudness; where it does not decide them it is answered as
    the truthful twin is: the assert's undecided test either fails on a face
    of its own, or -- a symbolic predicate -- is stated as the fact the
    prover refutes (``PredicateValue.stated``: an ``InvValue``; the lift
    invents no failing arm for it, ``AssertSugar``).  Never a completion
    with the assert gone: that would be the lying claim decided true."""
    path = FIXTURES / case["file"]
    for names in (case["canonical"], case["renamed"]):
        truthful = _outcome_or_panic(path, names["truthful"])
        assert not _is_typed_loud(truthful), truthful
        lying = _outcome_or_panic(path, names["lying"])
        assert _decided_assertion_failure(lying) or not _is_typed_loud(lying), lying
        if isinstance(lying, ExitSet):
            assert lying.halts() or all(
                _states_its_assert(exit_.value)
                for exit_ in lying.exits
                if exit_ not in lying.halts()
            ), lying


def _states_its_assert(value) -> bool:
    """A completed function universe whose record states a fact (``invs``):
    the lying twin's undecided assert, stated for the prover to refute."""
    invs = getattr(value, "invs", None)
    return callable(invs) and bool(invs())


def _decided_assertion_failure(result) -> bool:
    """Every arm of ``result`` halts with a named ``AssertionError``."""
    return (
        isinstance(result, ExitSet)
        and bool(result.exits)
        and result.halts() == result.exits
        and all(
            getattr(halt.effect, "exception_name", None) == "AssertionError"
            for halt in result.halts()
        )
    )


@pytest.mark.parametrize(
    "case",
    [case for case in MATRIX["cases"] if case["id"] in LOUD_IDS],
    ids=lambda case: case["id"],
)
def test_unauthenticated_object_field_flow_stays_typed_loud(case):
    path = FIXTURES / case["file"]
    for function_name in (case["canonical"], case["renamed"]):
        result = _outcome_or_panic(path, function_name)
        assert _claims_no_field_value(result), result


def _returned_values(result) -> list:
    """Every value a completed arm of ``result`` returns, guarded or not."""
    from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
    from sugar_lift_py_tests.floor.return_value import ReturnValue
    from sugar_lift_py_tests.outcome import Completed

    values = []
    for exit_ in result.exits:
        if not isinstance(exit_, Completed):
            continue
        record = getattr(exit_.value, "record", exit_.value)
        values.extend(
            entry.value
            for entry in getattr(record, "statements", ())
            if isinstance(entry, (ReturnValue, GuardedReturn))
        )
    return values


def _claims_no_field_value(result) -> bool:
    """The read of a field no construction authenticates is answered with
    no value for it: refused by name or typed loud (``_is_typed_loud``); an
    undischarged demand waiting on the caller's actual
    (``NativeOperationExitCarrierV1``: a formal receiver, a formal key --
    never a completion); or completed arms that each return an undecided
    value -- never the stored constant, which an opaque call or an opaque
    alias may have changed (``mutator(item)``, ``alias_factory(original)``)."""
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.floor.named_expression_value import peel_walrus_binds

    if _is_typed_loud(result) or isinstance(result, NativeOperationExitCarrierV1):
        return True
    if not isinstance(result, ExitSet):
        return False
    returned = _returned_values(result)
    return bool(returned) and not any(
        isinstance(peel_walrus_binds(value)[1], TermValue) for value in returned
    )


def _object_states(path: Path, function_name: str):
    function = _functions(path)[function_name]
    owner = function.fragment.seal().cid
    substituted = function.substitute(
        {_SUBSTITUTION_TRACE_BUILDER: SubstitutionTraceBuilderV1(owner)}
    )
    return [node for node in substituted.walk() if node.kind == "ObjectPlaceStateV1"]


def test_object_identities_reresolve_and_distinct_objects_do_not_collide():
    # An object place keeps no field versions of its own: a field store on it
    # is the one receiver field store, read through the receiver's post-state.
    first = _object_states(FIXTURES / "version_flow.py", "truthful")
    second = _object_states(FIXTURES / "version_flow.py", "truthful")
    assert first and second
    assert first[-1].object_identity_cid == second[-1].object_identity_cid
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
    with pytest.raises(
        BindingProvenanceGap, match="object place identity CID mismatch"
    ):
        forged.validate_identity()


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
    # The read is of the object as each arm's store left it: the one receiver
    # field store's post-state (``ReceiverFieldStoreState``), never a field
    # kept on the object place.  Each face holds its arm's store, read through
    # that store's key; the stored constant is only the object it denotes.
    assert returned.value.kind == "Attribute"
    faces = [
        node
        for node in returned.value.walk()
        if node.kind == "ReceiverFieldStoreState"
    ]
    assert len(faces) == 2
    for face in faces:
        assert face.attr == "payload"
        assert face.value.kind == "EvaluationRef"
        assert face.value.place is True
        assert face.value.of.kind == "Constant"
    assert faces[0].value.evaluation != faces[1].value.evaluation


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
def test_opaque_call_leaves_every_object_of_a_reachable_class_undecided(
    tmp_path, class_name, left_name, right_name, field
):
    """``mutator(left)`` runs code the caller does not follow.  That code
    reaches ``left``'s class -- ``type(left)``, and the module global the
    class statement bound -- and may bind a data descriptor for the field on
    it (``Vessel.payload = property(lambda self: 0)``), which wins over the
    instance ``__dict__`` for ``right`` too (``object.__getattribute__``).
    So ``right.payload`` after the call is not decided to be the 11 its
    store left: both reads after the call are the object as the call left
    it (``ReceiverAfterCall``, the one exposure rule
    ``container_mutation._ambient_targets``), which the value decides at
    reduce.  The two objects keep distinct identities."""
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
        {
            _SUBSTITUTION_TRACE_BUILDER: SubstitutionTraceBuilderV1(
                function.fragment.seal().cid
            )
        }
    )
    from sugar_source_tree.container_mutation import _identity

    returned = next(node for node in substituted.walk() if node.kind == "Return")
    # The other object's read is not decided to be the 11 its store left:
    # the call may have changed its class.  ``right = Vessel()`` is the
    # class's coordinate and edge (#7757 step 6, #8738), so ``right`` is a
    # class call's result, and a store on it leaves the object after code
    # the read does not see (#8746): the read is undecided at reduce, until
    # the post-call object state (step 7) and dispatch on a class call's
    # result (step 8) decide it at prove.  (It was read through
    # ``ReceiverAfterCall`` at substitution while ``Vessel()`` was applied at
    # lift.)
    assert returned.value.kind == "Attribute"
    assert _claims_no_field_value(_outcome_or_panic(path, "boundary"))
    states = [node for node in substituted.walk() if node.kind == "ObjectPlaceStateV1"]
    assert len({state.object_identity_cid for state in states}) == 2
    # The exposed object's name is rebound by the one exposure rule
    # (``container_mutation.havoc_after``): its later read is its value after
    # the call, which the value decides at reduce.  No place has its own
    # invalidation.
    observed = next(
        node
        for node in substituted.walk()
        if node.kind == "Assign" and getattr(node.targets[0], "id", None) == "observed"
    )
    assert observed.value.kind == "Attribute"
    assert _identity(observed.value.value).kind == "ReceiverAfterCall"


def test_opaque_result_mints_occurrence_identity_without_fields():
    path = FIXTURES / "opaque_alias.py"
    function = _functions(path)["read_through_opaque_alias"]
    substituted = function.substitute(
        {
            _SUBSTITUTION_TRACE_BUILDER: SubstitutionTraceBuilderV1(
                function.fragment.seal().cid
            )
        }
    )
    states = [node for node in substituted.walk() if node.kind == "OpaqueObjectStateV1"]
    assert states
    wire = states[-1].object_coordinate.wire()
    assert wire["kind"] == "opaque-object-coordinate"
    assert not ({"fields", "behavior", "class", "type"} & set(wire))


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
        "class Vessel:\n    " + member + "\n\ndef boundary():\n    item = Vessel()\n"
        "    item.payload = 7\n    return item.payload\n"
    )
    # Was typed loud while ``Vessel()`` was applied at lift and its namespace
    # read off the instance.  ``item`` is a class call's result (#8738): the
    # store leaves the object after code the read does not see (#8746), so
    # the read is undecided -- never the 7 the custom dispatch may not have
    # stored -- until dispatch on a class call's result (step 8).
    assert _claims_no_field_value(_outcome_or_panic(path, "boundary"))


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


def test_recursive_allocation_occurrence_stays_opaque_without_recursing(tmp_path):
    path = tmp_path / "recursive_allocation.py"
    path.write_text(
        "class Vessel:\n"
        "    def clone(self):\n"
        "        item = Vessel()\n"
        "        return item\n"
    )

    _outcome_or_panic(path, "clone")


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
    # Was typed loud; today undecided, never 7, until step 8 dispatches the
    # source ``__setitem__`` on a class call's result
    # (``_item_store_on_a_class_call_result``).
    assert _claims_no_field_value(_outcome_or_panic(path, "boundary"))


def test_custom_getitem_receiver_stays_loud(tmp_path):
    path = tmp_path / "getitem.py"
    path.write_text(
        "class Vessel:\n"
        "    def __getitem__(self, key):\n"
        "        return 7\n\n"
        "def boundary():\n"
        "    item = Vessel()\n"
        "    item[0] = 7\n"
        "    return item[0]\n"
    )
    # Was typed loud; today undecided until step 8 dispatches the source
    # ``__getitem__`` on a class call's result (where Python's 7 is decided).
    assert _claims_no_field_value(_outcome_or_panic(path, "boundary"))


def _item_store_on_a_class_call_result(outcome) -> None:
    """An item store on ``item = Vessel()`` as the lift states it today.

    ``Vessel()`` is the class's coordinate and edge (#7757 step 6, #8738):
    ``item`` is a class call's result, whose class namespace the lift no
    longer reads off an instance made by applying the constructor.  Which
    ``__setitem__`` (or none, CPython's ``TypeError``) the store runs is
    dispatch on a class call's result, decided at prove (step 8, not
    merged).  Until then the store is undecided: the outcome keeps a halt
    for the raise Python takes (or waits on a formal as its own proof states
    it), and never completes with the stored item read back."""
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )

    assert isinstance(outcome, (ExitSet, NativeOperationExitCarrierV1)), outcome
    if isinstance(outcome, ExitSet):
        assert outcome.halts(), outcome
    assert _claims_no_field_value(outcome), outcome


def _item_assignment_type_error(path: Path, source: str) -> None:
    """``item[k] = v`` on an instance of a class no class of whose MRO binds
    ``__setitem__`` (``object`` does not): CPython raises ``TypeError``
    ("'Vessel' object does not support item assignment") at the first store,
    and nothing after it runs.  The lift decided it here while ``Vessel()``
    was applied at lift (every arm a ``TypeError``); today it is undecided
    until step 8 (``_item_store_on_a_class_call_result``), never a
    completion that stores the item on the instance."""
    path.write_text(source)
    native: dict = {}
    exec(compile(source, str(path), "exec"), native)
    with pytest.raises(TypeError, match="does not support item assignment"):
        native["boundary"]()

    _item_store_on_a_class_call_result(_outcome_or_panic(path, "boundary"))


def test_plain_object_subscript_store_then_read_uses_same_field_map(tmp_path):
    _item_assignment_type_error(
        tmp_path / "plain_object_subscript.py",
        "class Vessel:\n    pass\n\n"
        "def boundary():\n"
        "    item = Vessel()\n"
        "    item[0] = 7\n"
        "    return item[0]\n",
    )


def test_subscript_aliases_share_identity_and_immutable_versions(tmp_path):
    _item_assignment_type_error(
        tmp_path / "subscript_alias_versions.py",
        "class Vessel:\n    pass\n\n"
        "def boundary():\n"
        "    item = Vessel()\n"
        "    alias = item\n"
        "    item[0] = 7\n"
        "    first = alias[0]\n"
        "    alias[0] = 11\n"
        "    return item[0]\n",
    )


def test_distinct_constructed_subscript_keys_do_not_collide(tmp_path):
    _item_assignment_type_error(
        tmp_path / "distinct_subscript_keys.py",
        "class Vessel:\n    pass\n\n"
        "def boundary():\n"
        "    item = Vessel()\n"
        "    item[0] = 7\n"
        "    item[1] = 11\n"
        "    return item[0]\n",
    )


def _formal_key_type_error(path: Path, statement: str, message: str) -> None:
    """``statement`` over ``item[key]`` on an instance whose type binds no
    item method: CPython raises ``TypeError`` whatever ``key`` is.  The lift
    halted with it at once while ``Vessel()`` was applied at lift
    (``receiver_lacks_item_method``); ``item`` is now a class call's result
    and the item method is dispatch at prove (step 8), so today the
    operation is undecided (``_item_store_on_a_class_call_result``)."""
    source = (
        "class Vessel:\n    pass\n\n"
        "def boundary(key):\n"
        "    item = Vessel()\n"
        f"    {statement}\n"
        "    return 0\n"
    )
    path.write_text(source)
    native: dict = {}
    exec(compile(source, str(path), "exec"), native)
    for key in (0, "k", None):
        with pytest.raises(TypeError, match=message):
            native["boundary"](key)

    outcome = _outcome_or_panic(path, "boundary")
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )

    # Undecided until step 8: a halt kept for the raise, or the operation
    # waiting on the formal ``key`` as its own proof states it; never a
    # completion with the raise gone.
    assert isinstance(outcome, (ExitSet, NativeOperationExitCarrierV1)), outcome
    if isinstance(outcome, ExitSet):
        assert outcome.halts(), outcome


def test_symbolic_subscript_key_store_raises_type_error_at_once(tmp_path):
    _formal_key_type_error(
        tmp_path / "symbolic_subscript_key.py",
        "item[key] = 7",
        "does not support item assignment",
    )


def test_symbolic_subscript_key_delete_raises_type_error_at_once(tmp_path):
    _formal_key_type_error(
        tmp_path / "symbolic_subscript_key_delete.py",
        "del item[key]",
        # CPython 3.12 spells it "doesn't support", 3.13 "does not support".
        "support item deletion",
    )


def test_symbolic_subscript_key_read_raises_type_error_at_once(tmp_path):
    _formal_key_type_error(
        tmp_path / "symbolic_subscript_key_read.py",
        "item[key]",
        "not subscriptable",
    )


def test_unhashable_subscript_key_stays_typed_loud(tmp_path):
    path = tmp_path / "unhashable_subscript_key.py"
    path.write_text(
        "class Vessel:\n    pass\n\n"
        "def boundary():\n"
        "    item = Vessel()\n"
        "    item[[]] = 7\n"
        "    return item[[]]\n"
    )
    # Was typed loud; a class call's result's ``__setitem__`` may accept a
    # list key, so today the store is undecided until step 8, never 7 read
    # back (``_item_store_on_a_class_call_result``).
    _item_store_on_a_class_call_result(_outcome_or_panic(path, "boundary"))


def test_out_of_range_list_store_stays_loud(tmp_path):
    path = tmp_path / "out_of_range_list.py"
    path.write_text(
        "def boundary():\n" "    item = []\n" "    item[0] = 7\n" "    return item[0]\n"
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
        "construction_testimony": state.construction_testimony,
        "object_identity_cid": state.object_identity_cid,
        "base": state.base,
    }
    values.update(overrides)
    return materialize(
        state.unit,
        ShadowNode(
            "ObjectPlaceStateV1",
            state.span,
            (
                ("object_coordinate", Leaf(values["object_coordinate"])),
                ("construction_testimony", Leaf(values["construction_testimony"])),
                ("object_identity_cid", Leaf(values["object_identity_cid"])),
                ("base", Child(_handle_of(values["base"]))),
                ("evaluation", Leaf(state.evaluation)),
                ("name", Leaf(state.name)),
            ),
        ),
        state.reporter,
    )
