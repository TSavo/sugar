"""Teeth for the source-owned enum namespace construction path.

These laws deliberately stop immediately beside the real ``enum._EnumDict``
lifecycle.  They protect the producer/consumer transport without copying the
large lifecycle test or admitting enum names as implementation rules.
"""

from __future__ import annotations

import ast
import csv
import importlib.metadata
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_python_source import manager_construction
from sugar_lift_python_source.resolution_session import SourceResolutionSession


def _distribution(root: Path, source: str) -> importlib.metadata.Distribution:
    package = root / "enum_shadow_fixture"
    package.mkdir()
    (package / "__init__.py").write_text(source, encoding="utf-8")
    metadata = root / "enum_shadow_fixture-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: enum-shadow-fixture\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (metadata / "top_level.txt").write_text("enum_shadow_fixture\n", encoding="utf-8")
    recorded = (
        "enum_shadow_fixture/__init__.py",
        "enum_shadow_fixture-1.0.dist-info/METADATA",
        "enum_shadow_fixture-1.0.dist-info/top_level.txt",
        "enum_shadow_fixture-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for item in recorded:
            writer.writerow((item, "", ""))
    return importlib.metadata.Distribution.at(metadata)


class _CountingRhsSugar:
    def __init__(self, calls: list[int], value: object) -> None:
        self.calls = calls
        self.value = value

    def desugar(self, ctx=None):
        del ctx
        self.calls.append(1)
        return Complete(self.value)


class _CountingRhs:
    def __init__(self, calls: list[int], value: object) -> None:
        self.calls = calls
        self.value = value

    def sugar(self):
        return _CountingRhsSugar(self.calls, self.value)


def test_module_chained_assignment_evaluates_rhs_once_and_shares_floor() -> None:
    """One RHS evaluation supplies the identical Floor to every Name target."""
    calls: list[int] = []
    value = TermValue(17)
    statement = SimpleNamespace(value=_CountingRhs(calls, value))
    targets = tuple(ast.parse("left = right = 0").body[0].targets)
    sugar = manager_construction._ModuleNameAssignmentBindingSugar(  # type: ignore[arg-type]
        statement,
        targets,
    )

    outcome = sugar.desugar(None)

    assert calls == [1]
    assert isinstance(outcome, Complete)
    assert outcome.value.bindings == (("left", value), ("right", value))
    assert outcome.value.bindings[0][1] is outcome.value.bindings[1][1]


def test_ground_false_else_return_has_the_canonical_true_guard() -> None:
    """The selected else return carries true, not a double-negated spelling."""
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.floor import GuardedReturn, ReturnValue
    from sugar_lift_py_tests.outcome.exit_set import true_guard
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_source_tree.tree import SourceFile

    source = "def selected():\n    if False:\n        return 1\n    else:\n        return 2\n"
    tree = SourceFile(
        (source, "ground_false_selected_return.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    function = next(tree.functions())

    outcome = function.sugar().desugar(None)

    assert isinstance(outcome, Complete)
    returns = tuple(
        statement
        for statement in outcome.value.record.statements
        if isinstance(statement, (ReturnValue, GuardedReturn))
    )
    assert len(returns) == 1
    selected = returns[0]
    assert isinstance(selected, GuardedReturn)
    assert selected.value == TermValue(2)
    assert selected.guards == (true_guard(),)


def test_enum_dict_class_transport_retains_authenticated_builtin_dict_base(
    tmp_path: Path,
) -> None:
    """Deleting producer base transport makes the real enum-adjacent tooth red."""
    from sugar_lift_py_tests.floor import BuiltinDictClassValue, ClassDefinitionValue
    from sugar_lift_python_source.dependency_artifact import DependencyArtifactGraph

    source = (
        "class _EnumDict(dict):\n"
        "    def __init__(self):\n"
        "        self.marker = 1\n"
        "    def __setitem__(self, key, value):\n"
        "        return value\n"
        "after = 1\n"
    )
    graph = DependencyArtifactGraph.authenticate(_distribution(tmp_path, source))
    module = graph.modules["enum_shadow_fixture"]
    parsed = ast.parse(module.source)
    enum_dict = next(
        statement
        for statement in parsed.body
        if isinstance(statement, ast.ClassDef) and statement.name == "_EnumDict"
    )
    locus = next(
        statement
        for statement in parsed.body
        if statement.lineno > enum_dict.end_lineno
    )

    session = SourceResolutionSession(
        enrolled_distributions=frozenset({graph.distribution_name})
    )
    exits = manager_construction._module_prefix_outcome(
        module, locus, graph=graph, session=session
    )

    assert len(exits.exits) == 1
    completed = exits.exits[0]
    value = completed.value.context.temporal.value_if_bound("_EnumDict")
    assert isinstance(value, ClassDefinitionValue)
    assert any(isinstance(base, BuiltinDictClassValue) for base in value.base_classes)
    assert {method.name for method in value.methods} >= {"__init__", "__setitem__"}


def test_enum_dict_receiver_mutation_retains_identity_and_source_methods(
    tmp_path: Path,
) -> None:
    """Builtin mapping state augments the receiver; it never replaces it."""
    from sugar_lift_py_tests.floor import (
        ClassDefinitionValue,
        MappingObjectValue,
        StringValue,
    )
    from sugar_lift_python_source.dependency_artifact import DependencyArtifactGraph

    source = (
        "class _EnumDict(dict):\n"
        "    def marker(self):\n"
        "        return 7\n"
        "after = 1\n"
    )
    graph = DependencyArtifactGraph.authenticate(_distribution(tmp_path, source))
    module = graph.modules["enum_shadow_fixture"]
    parsed = ast.parse(module.source)
    enum_dict = parsed.body[0]
    exits = manager_construction._module_prefix_outcome(
        module,
        parsed.body[1],
        graph=graph,
        session=SourceResolutionSession(
            enrolled_distributions=frozenset({graph.distribution_name})
        ),
    )
    completed = exits.exits[0]
    value = completed.value.context.temporal.value_if_bound("_EnumDict")
    assert isinstance(value, ClassDefinitionValue)
    receiver = value.construct_receiver_state_from_block(None, "receiver-coordinate")
    assert isinstance(receiver, MappingObjectValue)

    mutated = receiver.setitem(StringValue("member"), TermValue(7), enum_dict)

    assert isinstance(mutated, Complete)
    assert isinstance(mutated.value, MappingObjectValue)
    assert mutated.value.identity == receiver.identity == "receiver-coordinate"
    assert mutated.value.methods == receiver.methods
    assert {method.name for method in mutated.value.methods} == {"marker"}
    assert mutated.value.entries == ((StringValue("member"), TermValue(7)),)

    # Lying face: deleting the producer's base transport removes the mapping
    # capability.  The truthful assertions above therefore cannot pass merely
    # because the consumer recognizes the source class name.
    without_base_transport = replace(value, base_classes=())
    unbacked = without_base_transport.construct_receiver_state_from_block(
        None, "receiver-coordinate"
    )
    assert not isinstance(unbacked, MappingObjectValue)
