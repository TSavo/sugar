"""Resolve Class.method through an imported class export.

Vendor shape matched by pytest's RaisesExc.__enter__:
``from _pytest._code import ExceptionInfo`` then ``ExceptionInfo.for_later()``.
The binding names the class export; the extra Attribute segment is a method
on that class, not a nested module.
"""

from __future__ import annotations

import csv
import importlib.metadata
from pathlib import Path

from sugar_lift_py_tests.import_binding import authenticated_import_value_use_receipts
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.dependency_artifact import (
    DependencyArtifactGraph,
    PythonObjectResolutionGapV1,
    ResolvedPythonObjectV1,
    resolve_import_binding as _resolve_import_binding,
)
from sugar_lift_python_source.resolution_session import SourceResolutionSession


def resolve_import_binding(*args, graph, session=None, **kwargs):
    if session is None:
        session = SourceResolutionSession(
            enrolled_distributions=frozenset({graph.distribution_name})
        )
    return _resolve_import_binding(*args, graph=graph, session=session, **kwargs)


def _graph(root: Path, package: str):
    holder = (
        f"# package {package}\n"
        "class Holder:\n"
        "    @classmethod\n"
        "    def for_later(cls):\n"
        "        return None\n"
    )
    source = (
        f"from .holder import Holder  # {package}\n"
        "ready = Holder.for_later()\n"
        "missing = Holder.absent()\n"
    )
    files = {
        f"{package}/__init__.py": source,
        f"{package}/holder.py": holder,
    }
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    metadata = root / f"{package}_dist-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {package}\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (metadata / "top_level.txt").write_text(f"{package}\n", encoding="utf-8")
    recorded = (
        *files,
        f"{metadata.name}/METADATA",
        f"{metadata.name}/top_level.txt",
        f"{metadata.name}/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for item in recorded:
            writer.writerow((item, "", ""))
    graph = DependencyArtifactGraph.authenticate(
        importlib.metadata.Distribution.at(metadata)
    )
    path = root / package / "__init__.py"
    source_cid = blake3_512_of(source.encode("utf-8"))
    receipts, _ = authenticated_import_value_use_receipts(
        root, path, source, source_cid, module_identities={}
    )
    return graph, receipts


def _receipt(receipts, path: list[str]):
    return next(row for row in receipts if row.use["exportedMemberPath"] == path)


def test_imported_class_classmethod_resolves_to_class_body_definition(tmp_path: Path):
    graph, receipts = _graph(tmp_path, "holder_package")

    result = resolve_import_binding(_receipt(receipts, ["for_later"]), graph=graph)

    assert isinstance(result, ResolvedPythonObjectV1), result
    assert result.definition.kind == "function"
    assert result.definition.name == "for_later"
    assert result.module_name == "holder_package.holder"


def test_imported_class_absent_member_stays_outside_binding(tmp_path: Path):
    graph, receipts = _graph(tmp_path, "absent_member_package")

    result = resolve_import_binding(_receipt(receipts, ["absent"]), graph=graph)

    assert isinstance(result, PythonObjectResolutionGapV1), result
    assert result.kind == "target-outside-binding"
    assert result.exported_name == "absent"
    assert result.module_name == "absent_member_package.holder"



def test_imported_class_classmethod_projects_an_ordinary_source_call_frame(
    tmp_path: Path,
) -> None:
    """An imported Class.method export has an ordinary source call frame.

    Resolving the binding is not enough: RaisesExc.__enter__ calls
    ``ExceptionInfo.for_later()``, which needs the method's frame, not a
    definition-missing gap after the coordinate was already found.
    """
    from sugar_lift_python_source.manager_construction import (
        ManagerConstructionGapV1,
        resolve_source_visible_frame,
    )

    graph, receipts = _graph(tmp_path, "holder_frame_package")
    session = SourceResolutionSession(
        enrolled_distributions=frozenset({graph.distribution_name})
    )
    resolved = resolve_import_binding(
        _receipt(receipts, ["for_later"]), graph=graph, session=session
    )
    assert isinstance(resolved, ResolvedPythonObjectV1), resolved

    projected = resolve_source_visible_frame(
        resolved, graph=graph, session=session
    )

    assert not isinstance(projected, ManagerConstructionGapV1), projected
    frame, target = projected
    assert target.name == "for_later"
    assert frame.parameters == ("cls",)



def test_classmethod_attribute_call_binds_the_class_as_cls() -> None:
    """``Holder.for_later()`` binds the class to the implicit cls formal.

    A seated classmethod frame includes ``cls``. The attribute receiver is
    that actual; without it, bind_node_actuals raises missing required formal 0.
    """
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap
    from sugar_source_tree.nodes import Attribute, Call, ClassDef, FunctionDef
    from sugar_source_tree.tree import SourceFile

    source = (
        "class Holder:\n"
        "    @classmethod\n"
        "    def for_later(cls):\n"
        "        return None\n"
        "ready = Holder.for_later()\n"
    )
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (source, "classmethod-cls.py", blake3_512_of(source.encode())),
        construction_context=context,
    )
    holder = next(
        node
        for node in tree.nodes()
        if isinstance(node, ClassDef) and node.name == "Holder"
    )
    method = next(
        node
        for node in holder.body
        if isinstance(node, FunctionDef) and node.name == "for_later"
    )
    call = next(
        node
        for node in tree.nodes()
        if isinstance(node, Call)
        and isinstance(node.func, Attribute)
        and node.func.attr == "for_later"
    )
    context.source_call_frames[call.source_occurrence()] = (
        method.source_visible_call_frame()
    )
    try:
        sugar = call.sugar()
    except SourceCallBindingGap as exc:
        raise AssertionError(exc) from exc
    assert len(sugar.args) == 1
    from sugar_source_tree.panic import SugarNotWritten

    try:
        sugar.desugar()
    except SugarNotWritten as exc:
        raise AssertionError(exc) from exc



def test_nested_classmethod_is_re_found_by_its_unit_seal() -> None:
    """A classmethod is not a module-scope binding; its unit seal still finds it.

    ``_callee_definition_by_name_in_its_unit`` correctly answers nothing for
    ``Holder.for_later``. Testimony used to stop there unless the nested
    method was named ``__call__``, leaving ``resolved-not-a-functiondef``.
    """
    from sugar_source_tree.binding_state import (
        _callee_definition_by_name_in_its_unit,
        _callee_nested_call_method_by_seal,
    )
    from sugar_source_tree.nodes import ClassDef, FunctionDef
    from sugar_source_tree.tree import SourceFile

    source = (
        "class Holder:\n"
        "    @classmethod\n"
        "    def for_later(cls):\n"
        "        return None\n"
    )
    tree = SourceFile(
        (source, "nested-classmethod-seal.py", blake3_512_of(source.encode()))
    )
    holder = next(
        node
        for node in tree.nodes()
        if isinstance(node, ClassDef) and node.name == "Holder"
    )
    method = next(
        node
        for node in holder.body
        if isinstance(node, FunctionDef) and node.name == "for_later"
    )
    assert _callee_definition_by_name_in_its_unit(method) is None
    assert _callee_nested_call_method_by_seal(method) is method


def test_nested_dunder_call_is_still_re_found_by_its_unit_seal() -> None:
    """Callable-instance ``Class.__call__`` stays findable by the same seal."""
    from sugar_source_tree.binding_state import _callee_nested_call_method_by_seal
    from sugar_source_tree.nodes import ClassDef, FunctionDef
    from sugar_source_tree.tree import SourceFile

    source = (
        "class Fail:\n"
        "    def __call__(self, reason=''):\n"
        "        return reason\n"
    )
    tree = SourceFile(
        (source, "nested-dunder-call-seal.py", blake3_512_of(source.encode()))
    )
    fail = next(
        node
        for node in tree.nodes()
        if isinstance(node, ClassDef) and node.name == "Fail"
    )
    method = next(
        node
        for node in fail.body
        if isinstance(node, FunctionDef) and node.name == "__call__"
    )
    assert _callee_nested_call_method_by_seal(method) is method



def _constructor_graph(root: Path, package: str):
    holder = (
        f"# package {package}\n"
        "class Holder:\n"
        "    def __init__(self, value=None):\n"
        "        self.value = value\n"
        "    @classmethod\n"
        "    def for_later(cls):\n"
        "        return cls(None)\n"
        "ready = Holder.for_later()\n"
    )
    source = (
        f"from .holder import Holder  # {package}\n"
        "ready = Holder.for_later()\n"
    )
    files = {
        f"{package}/__init__.py": source,
        f"{package}/holder.py": holder,
    }
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    metadata = root / f"{package}_dist-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {package}\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (metadata / "top_level.txt").write_text(f"{package}\n", encoding="utf-8")
    recorded = (
        *files,
        f"{metadata.name}/METADATA",
        f"{metadata.name}/top_level.txt",
        f"{metadata.name}/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for item in recorded:
            writer.writerow((item, "", ""))
    graph = DependencyArtifactGraph.authenticate(
        importlib.metadata.Distribution.at(metadata)
    )
    path = root / package / "__init__.py"
    source_cid = blake3_512_of(source.encode("utf-8"))
    receipts, _ = authenticated_import_value_use_receipts(
        root, path, source, source_cid, module_identities={}
    )
    return graph, receipts


def test_classmethod_receiver_construction_is_not_a_value_call(tmp_path: Path) -> None:
    """``return cls(...)`` on a classmethod constructs the bound class.

    Frame preparation used to park that call as value-call-target because
    ``cls`` is a formal. After substitution it is a computed call of the
    class bound as the receiver, which already has a constructor door.
    An ordinary ``return helper()`` formal stays a value-call.
    """
    from sugar_lift_py_tests.context import ReduceContext
    from sugar_lift_py_tests.floor import (
        BlockValue,
        CallSiteValue,
        ClassDefinitionValue,
        ObjectValue,
        ReturnValue,
    )
    from sugar_lift_py_tests.floor.none_value import NoneValue
    from sugar_lift_py_tests.outcome import Complete
    from sugar_lift_py_tests.temporal.builtin_name_bindings import builtin_name_temporal
    from sugar_lift_python_source.manager_construction import (
        ManagerConstructionGapV1,
        resolve_source_visible_frame,
    )
    from sugar_source_tree.nodes import Attribute, Call
    from sugar_source_tree.panic import SugarNotWritten

    graph, receipts = _constructor_graph(tmp_path, "holder_ctor_package")
    session = SourceResolutionSession(
        enrolled_distributions=frozenset({graph.distribution_name})
    )
    resolved = resolve_import_binding(
        _receipt(receipts, ["for_later"]), graph=graph, session=session
    )
    assert isinstance(resolved, ResolvedPythonObjectV1), resolved

    projected = resolve_source_visible_frame(
        resolved, graph=graph, session=session
    )
    assert not isinstance(projected, ManagerConstructionGapV1), projected
    frame, target = projected
    owner = target.unit.lexical_class_owner_for(target)
    assert owner is not None and owner.name == "Holder"

    holder_outcome = owner.sugar().desugar()
    assert isinstance(holder_outcome, Complete), holder_outcome
    assert isinstance(holder_outcome.value, ClassDefinitionValue)

    module = target.unit.constructed_module.root
    stack = [module]
    call = None
    while stack:
        node = stack.pop()
        if (
            isinstance(node, Call)
            and isinstance(node.func, Attribute)
            and node.func.attr == "for_later"
        ):
            call = node
            break
        stack.extend(child for _, _, child in node.children())
    assert call is not None

    context = target.unit.construction_context
    context.source_call_frames[call.source_occurrence()] = frame
    try:
        sugar = call.sugar()
    except SugarNotWritten as exc:
        raise AssertionError(exc) from exc

    ctx = ReduceContext(
        temporal=builtin_name_temporal().bind_value(
            "Holder", holder_outcome.value, blame="Holder"
        )
    )
    try:
        outcome = sugar.desugar(ctx)
    except SugarNotWritten as exc:
        raise AssertionError(exc) from exc

    assert isinstance(outcome, Complete), outcome
    callsite = outcome.value
    assert isinstance(callsite, CallSiteValue), callsite
    retained = callsite._retained_source_completion
    assert retained is not None, callsite
    body = retained.value
    assert isinstance(body, BlockValue), body
    assert len(body.statements) == 1
    returned = body.statements[0]
    assert isinstance(returned, ReturnValue), returned
    constructed = returned.value
    assert isinstance(constructed, ObjectValue), constructed
    assert constructed.class_name == "Holder"
    stored = {field.name: field.value for field in constructed.fields}
    assert "value" in stored
    assert isinstance(stored["value"], NoneValue)
