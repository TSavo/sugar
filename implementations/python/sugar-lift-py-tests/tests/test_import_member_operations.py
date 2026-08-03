"""Import-member operations door — one floor, many uses.

ImportMemberValue is a source-authenticated export whose runtime type is not
lift-time decided. Ops must not fall through to FloorValue's construction-
panic ``write more Floor`` arm (that miscounts undecided type as OUR defect).

Triage:
  - subscript / attribute / contains → existing FloorValue.undecided_* (wire)
  - call / method / iter / binary → ImportedModuleRuntimeEffect incomplete
  - equals → FloorValue.equals via to_term (already constructs)

Not this door: CallSiteSugar / MethodCallSugar / sugar_base (blue).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sugar_lift_py_tests.floor.import_member_value import ImportMemberValue
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_source_tree.panic import SugarNotWritten


def _import_member_and_site() -> tuple[ImportMemberValue, object]:
    """Real seated ImportMemberValue + its source fragment (for effect locus)."""
    from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
    from sugar_lift_python_source.dependency_artifact import DependencyArtifactGraph
    from sugar_lift_python_source.manager_construction import (
        _seat_import_value_use_receipts,
    )
    from sugar_lift_python_source.resolution_session import SourceResolutionSession
    from sugar_source_tree.nodes import Attribute, ClassDef
    from sugar_source_tree.tree import SourceFile

    graph = DependencyArtifactGraph.authenticate_stdlib_module("re")
    module = graph.modules["re"]
    context = TreeConstructionContextV1.for_source_call_construction()
    source_file = SourceFile(
        (module.source, module.source_seat, module.source_cid),
        construction_context=context,
    )
    regex_flag = next(
        node
        for node in source_file.root.body
        if isinstance(node, ClassDef) and node.name == "RegexFlag"
    )
    _seat_import_value_use_receipts(
        source_file=source_file,
        module=module,
        target=regex_flag,
        session=SourceResolutionSession(
            enrolled_distributions=frozenset(), enabled=False
        ),
        context=context,
        dependency_graphs={"re": graph},
    )
    member = next(
        node
        for node in source_file.nodes()
        if isinstance(node, Attribute) and node.attr == "SRE_FLAG_ASCII"
    )
    outcome = member.sugar().desugar()
    assert isinstance(outcome, Complete)
    assert type(outcome.value) is ImportMemberValue
    return outcome.value, member.fragment


def _import_member() -> ImportMemberValue:
    return _import_member_and_site()[0]


def test_import_member_runtime_type_undecided() -> None:
    v = _import_member()
    assert v.denotes_value() is True
    assert v.runtime_type_is_decided() is False


def test_subscript_is_undecided_refusal_not_write_more_floor() -> None:
    """Wiring: enter FloorValue.undecided_subscript, not construction panic."""
    v, site = _import_member_and_site()
    with pytest.raises(SugarNotWritten, match="ImportMemberValue.subscript") as caught:
        v.subscript(v, site)
    assert "write more Floor" not in str(caught.value)
    assert "undecided" in str(caught.value.observed).lower()


def test_attribute_is_undecided_refusal_not_write_more_floor() -> None:
    v, site = _import_member_and_site()
    with pytest.raises(SugarNotWritten, match="ImportMemberValue.attribute") as caught:
        v.attribute("bit_count", site)
    assert "write more Floor" not in str(caught.value)
    assert "undecided" in str(caught.value.observed).lower()


def test_contains_is_undecided_refusal_not_write_more_floor() -> None:
    v, site = _import_member_and_site()
    with pytest.raises(SugarNotWritten, match="ImportMemberValue.contains") as caught:
        v.contains(v, site)
    assert "write more Floor" not in str(caught.value)


def test_call_through_import_is_runtime_boundary_incomplete() -> None:
    """Call-through-import: Incomplete effect — not CallSite, not write-more-Floor."""
    v, site = _import_member_and_site()
    op = SimpleNamespace(site=site, name="__call__")
    outcome = v.callable_application_with(op, None)
    assert isinstance(outcome, Incomplete)
    from sugar_lift_py_tests.effect import ImportedModuleRuntimeEffect

    assert type(outcome.effect) is ImportedModuleRuntimeEffect
    msg = str(outcome.effect).lower()
    assert "import" in msg and "member" in msg


def test_iteration_is_runtime_boundary_incomplete() -> None:
    v, site = _import_member_and_site()
    op = SimpleNamespace(site=site)
    outcome = v.iter_with(op, None)
    assert isinstance(outcome, Incomplete)
    from sugar_lift_py_tests.effect import ImportedModuleRuntimeEffect

    assert type(outcome.effect) is ImportedModuleRuntimeEffect


def test_comparison_constructs_on_authenticated_term() -> None:
    """Equals uses to_term — constructs without inventing runtime type."""
    v, site = _import_member_and_site()
    outcome = v.equals(v, site)
    assert isinstance(outcome, Complete)
