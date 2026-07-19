from __future__ import annotations

from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.claim import SugarRole
import ast


def test_authenticated_bare_type_call_selects_registered_recognizer() -> None:
    site = SourceFragment.from_node(
        ast.parse("type(1)", mode="eval").body, "type.py"
    )
    built = build_node(site, SugarRole.TERM, default_catalog())
    assert type(built.sugar).__name__ == "BuiltinTypeCallSugar"


def test_receiver_qualified_type_call_stays_outside_partition() -> None:
    site = SourceFragment.from_node(
        ast.parse("obj.type(1)", mode="eval").body, "type.py"
    )
    built = build_node(site, SugarRole.TERM, default_catalog())
    assert type(built.sugar).__name__ != "BuiltinTypeCallSugar"
