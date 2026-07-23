"""Cut C: ordinary authenticated Python factory construction.

The constructor consumes only Cut A graph objects and already-constructed
actuals. Unsupported control flow or opaque calls produce typed gaps; no host
module is imported or executed.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
import inspect
import json
from typing import Any, Literal

from sugar_lift_py_tests.floor import (
    DictValue,
    FloorValue,
    NoneValue,
    ObjectField,
    ObjectValue,
    StringValue,
    SymbolicValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.ir import ctor, encode_jcs, str_const, term_to_value
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

from .canonical import cid_of_json
from .dependency_artifact import DependencyArtifactGraph, ResolvedPythonObjectV1


@dataclass(frozen=True)
class FormalParameterCoordinateV1:
    definition_cid: str
    parameter_index: int
    formal_name: str
    passing: str


@dataclass(frozen=True)
class FormalActualBindingV1:
    coordinate: FormalParameterCoordinateV1
    formal_name: str
    actual: FloorValue = field(compare=False)
    provenance: Literal["actual", "default", "variadic"]


@dataclass(frozen=True)
class ConstructedCallFrameV1:
    definition_name: str
    definition_cid: str
    formal_actual_cid: str


@dataclass(frozen=True)
class ConstructedManagerBehaviorV1:
    resolved_object_cid: str
    manager_construction_cid: str
    receiver_state: ObjectValue = field(compare=False)
    receiver_state_cid: str
    formal_actuals: tuple[FormalActualBindingV1, ...] = field(compare=False)
    call_frames: tuple[ConstructedCallFrameV1, ...]

    def __post_init__(self) -> None:
        if cid_of_json(_object_value(self.receiver_state)) != self.receiver_state_cid:
            raise ValueError("receiver state CID does not match constructed fields")
        if cid_of_json(self._construction_preimage()) != self.manager_construction_cid:
            raise ValueError("manager construction CID does not match its preimage")

    def _construction_preimage(self) -> dict[str, Any]:
        return {
            "kind": "python-manager-construction",
            "schemaVersion": "1",
            "resolvedObjectCid": self.resolved_object_cid,
            "receiverStateCid": self.receiver_state_cid,
            "formalActuals": [_binding_value(item) for item in self.formal_actuals],
            "callFrames": [frame.__dict__ for frame in self.call_frames],
        }

    def to_value(self) -> dict[str, Any]:
        return {
            "kind": "constructed-manager-behavior",
            "schemaVersion": "1",
            "resolvedObjectCid": self.resolved_object_cid,
            "managerConstructionCid": self.manager_construction_cid,
            "receiverStateCid": self.receiver_state_cid,
            "callFrames": [frame.__dict__ for frame in self.call_frames],
            "formalActuals": [_binding_value(item) for item in self.formal_actuals],
        }


@dataclass(frozen=True)
class ManagerConstructionGapV1:
    kind: Literal[
        "artifact-mismatch",
        "definition-missing",
        "call-binding",
        "unsupported-source",
        "opaque-call-target",
        "non-manager-result",
    ]
    resolved_object_cid: str
    detail: str


class _Gap(Exception):
    def __init__(self, kind: str, detail: str):
        self.kind = kind
        self.detail = detail


@dataclass(frozen=True)
class _Definition:
    node: ast.FunctionDef | ast.ClassDef
    source_cid: str

    @property
    def cid(self) -> str:
        return cid_of_json(
            {
                "sourceCid": self.source_cid,
                "name": self.node.name,
                "line": self.node.lineno,
                "column": self.node.col_offset,
                "endLine": self.node.end_lineno,
                "endColumn": self.node.end_col_offset,
            }
        )


@dataclass(frozen=True)
class _Invocation:
    value: FloorValue
    bindings: tuple[FormalActualBindingV1, ...]
    frames: tuple[ConstructedCallFrameV1, ...]


def construct_manager_behavior(
    resolved: ResolvedPythonObjectV1,
    *,
    graph: DependencyArtifactGraph,
    positional_actuals: tuple[FloorValue, ...],
    keyword_actuals: tuple[tuple[str, FloorValue], ...] = (),
) -> ConstructedManagerBehaviorV1 | ManagerConstructionGapV1:
    if graph.distribution_artifact_cid != resolved.distribution_artifact_cid:
        return ManagerConstructionGapV1(
            "artifact-mismatch", resolved.cid, "artifact CID"
        )
    module = graph.modules.get(resolved.module_name)
    if module is None or module.source_cid != resolved.source_cid:
        return ManagerConstructionGapV1("artifact-mismatch", resolved.cid, "source CID")
    tree = ast.parse(module.source, filename=module.source_seat)
    definitions = {
        node.name: _Definition(node, module.source_cid)
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.ClassDef))
    }
    definition = definitions.get(resolved.definition.name)
    if definition is None or definition.cid != _coordinate_cid(resolved):
        return ManagerConstructionGapV1(
            "definition-missing", resolved.cid, "coordinate"
        )
    try:
        invocation = _invoke(
            definition, positional_actuals, keyword_actuals, definitions
        )
    except _Gap as gap:
        return ManagerConstructionGapV1(gap.kind, resolved.cid, gap.detail)
    if not isinstance(invocation.value, ObjectValue):
        return ManagerConstructionGapV1(
            "non-manager-result", resolved.cid, "not object"
        )
    state = _object_value(invocation.value)
    state_cid = cid_of_json(state)
    preimage = {
        "kind": "python-manager-construction",
        "schemaVersion": "1",
        "resolvedObjectCid": resolved.cid,
        "receiverStateCid": state_cid,
        "formalActuals": [_binding_value(item) for item in invocation.bindings],
        "callFrames": [frame.__dict__ for frame in invocation.frames],
    }
    return ConstructedManagerBehaviorV1(
        resolved.cid,
        cid_of_json(preimage),
        invocation.value,
        state_cid,
        invocation.bindings,
        invocation.frames,
    )


def _invoke(definition, positional, keywords, definitions) -> _Invocation:
    if isinstance(definition.node, ast.ClassDef):
        return _construct_class(definition, positional, keywords, definitions)
    bindings, env = _bind(definition, positional, keywords)
    env.update(definitions)
    frames = [_frame(definition, bindings)]
    for statement in definition.node.body:
        if isinstance(statement, ast.Return) and statement.value is not None:
            value, nested = _expr(statement.value, env, definitions)
            return _Invocation(value, bindings, (*frames, *nested))
        if isinstance(statement, (ast.Global, ast.Nonlocal)):
            continue
        raise _Gap("unsupported-source", type(statement).__name__)
    raise _Gap("unsupported-source", "function has no value return")


def _construct_class(definition, positional, keywords, definitions) -> _Invocation:
    init = next(
        (
            item
            for item in definition.node.body
            if isinstance(item, ast.FunctionDef) and item.name == "__init__"
        ),
        None,
    )
    if init is None or definition.node.decorator_list:
        raise _Gap("opaque-call-target", "class construction is dynamic")
    init_def = _Definition(init, definition.source_cid)
    bindings, env = _bind(init_def, positional, keywords, skip_first=True)
    env.update(definitions)
    fields: list[ObjectField] = []
    frames = [_frame(init_def, bindings)]
    for statement in init.body:
        if not (isinstance(statement, ast.Assign) and len(statement.targets) == 1):
            raise _Gap("unsupported-source", type(statement).__name__)
        target = statement.targets[0]
        if not (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
        ):
            raise _Gap("unsupported-source", "constructor target")
        value, nested = _expr(statement.value, env, definitions)
        fields.append(ObjectField(target.attr, value))
        frames.extend(nested)
    receiver = ObjectValue(definition.node.name, tuple(fields), identity=definition.cid)
    return _Invocation(receiver, bindings, tuple(frames))


def _bind(definition, positional, keywords, skip_first=False):
    node = definition.node
    if not isinstance(node, ast.FunctionDef):
        raise _Gap("call-binding", "not function")
    raw = [*node.args.posonlyargs, *node.args.args]
    if skip_first:
        raw = raw[1:]
    parameters: list[inspect.Parameter] = []
    defaults = [None] * (len(raw) - len(node.args.defaults)) + list(node.args.defaults)
    for index, (argument, default) in enumerate(zip(raw, defaults, strict=True)):
        kind = (
            inspect.Parameter.POSITIONAL_ONLY
            if index < len(node.args.posonlyargs)
            else inspect.Parameter.POSITIONAL_OR_KEYWORD
        )
        parameters.append(
            inspect.Parameter(
                argument.arg,
                kind,
                default=(
                    inspect.Parameter.empty if default is None else _literal(default)
                ),
            )
        )
    if node.args.vararg:
        parameters.append(
            inspect.Parameter(node.args.vararg.arg, inspect.Parameter.VAR_POSITIONAL)
        )
    for argument, default in zip(
        node.args.kwonlyargs, node.args.kw_defaults, strict=True
    ):
        parameters.append(
            inspect.Parameter(
                argument.arg,
                inspect.Parameter.KEYWORD_ONLY,
                default=(
                    inspect.Parameter.empty if default is None else _literal(default)
                ),
            )
        )
    if node.args.kwarg:
        parameters.append(
            inspect.Parameter(node.args.kwarg.arg, inspect.Parameter.VAR_KEYWORD)
        )
    signature = inspect.Signature(parameters)
    try:
        bound = signature.bind(*positional, **dict(keywords))
    except TypeError as exc:
        raise _Gap("call-binding", str(exc)) from exc
    supplied = set(bound.arguments)
    bound.apply_defaults()
    result = []
    env = {}
    for index, parameter in enumerate(parameters):
        value = bound.arguments[parameter.name]
        if parameter.kind is inspect.Parameter.VAR_POSITIONAL:
            value = TupleValue(tuple(value))
            provenance = "variadic"
        elif parameter.kind is inspect.Parameter.VAR_KEYWORD:
            value = DictValue(tuple((StringValue(k), v) for k, v in value.items()))
            provenance = "variadic"
        else:
            provenance = "actual" if parameter.name in supplied else "default"
        coordinate = FormalParameterCoordinateV1(
            definition.cid, index, parameter.name, parameter.kind.name
        )
        binding = FormalActualBindingV1(coordinate, parameter.name, value, provenance)
        result.append(binding)
        env[parameter.name] = value
    return tuple(result), env


def _expr(node, env, definitions):
    if isinstance(node, ast.Name):
        if node.id not in env:
            raise _Gap("opaque-call-target", node.id)
        return env[node.id], ()
    if isinstance(node, ast.Constant):
        return _literal(node), ()
    if isinstance(node, ast.Call):
        callee, frames = _expr(node.func, env, definitions)
        if not isinstance(callee, _Definition):
            raise _Gap("opaque-call-target", "call target")
        positional = []
        for item in node.args:
            if isinstance(item, ast.Starred):
                value, nested = _expr(item.value, env, definitions)
                frames = (*frames, *nested)
                if not isinstance(value, TupleValue):
                    raise _Gap("call-binding", "* value")
                positional.extend(value.elements)
                continue
            value, nested = _expr(item, env, definitions)
            positional.append(value)
            frames = (*frames, *nested)
        keywords = []
        for item in node.keywords:
            value, nested = _expr(item.value, env, definitions)
            frames = (*frames, *nested)
            if item.arg is None:
                if not isinstance(value, DictValue):
                    raise _Gap("call-binding", "** value")
                keywords.extend(
                    (key.value, entry)
                    for key, entry in value.entries
                    if isinstance(key, StringValue)
                )
            else:
                keywords.append((item.arg, value))
        called = _invoke(callee, tuple(positional), tuple(keywords), definitions)
        return called.value, (*frames, *called.frames)
    raise _Gap("unsupported-source", type(node).__name__)


def _literal(node):
    value = node.value
    if value is None:
        return NoneValue()
    if value is True:
        return TrueBoolLiteralSugar(None)
    if value is False:
        return FalseBoolLiteralSugar(None)
    if isinstance(value, int):
        return TermValue(value)
    if isinstance(value, str):
        return StringValue(value)
    raise _Gap("unsupported-source", "literal")


def _floor_value(value):
    if isinstance(value, ObjectValue):
        return _object_value(value)
    return json.loads(encode_jcs(term_to_value(value.to_term(owner="Cut C"))))


def _object_value(value):
    return {
        "typeDefinitionCid": value.identity,
        "fields": [
            {"name": item.name, "value": _floor_value(item.value)}
            for item in value.fields
        ],
    }


def _binding_value(binding):
    return {
        "formal": binding.coordinate.__dict__,
        "actual": _floor_value(binding.actual),
        "provenance": binding.provenance,
    }


def _frame(definition, bindings):
    return ConstructedCallFrameV1(
        definition.node.name,
        definition.cid,
        cid_of_json([_binding_value(item) for item in bindings]),
    )


def _coordinate_cid(resolved):
    coordinate = resolved.definition
    return cid_of_json(
        {
            "sourceCid": coordinate.source_cid,
            "name": coordinate.name,
            "line": coordinate.start_line,
            "column": coordinate.start_col,
            "endLine": coordinate.end_line,
            "endColumn": coordinate.end_col,
        }
    )
