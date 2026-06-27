from __future__ import annotations

import ast
from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.claim import SugarCatalog, SugarClaim, SugarRole
from sugar_lift_py_tests.factory import FactoryGap, build_next


def test_factory_without_sugar_panics_on_last_popped_source_site() -> None:
    source = "def encode_len(data):\n    return len(data)\n"

    with pytest.raises(FactoryGap) as raised:
        build_next(source, filename="base64.py", role=SugarRole.TERM)

    gap = raised.value
    assert str(gap).startswith("write more Sugar for this AST")
    assert gap.info == {
        "owner": "python.factory",
        "blame": "base64.py:2:15",
        "observed": "Name",
        "requested": "term",
        "fix": "create sugar_lift_py_tests.sugar.name.name_sugar",
    }
    assert gap.audit_row.to_json() == {
        "kind": "factory-audit-row",
        "role": "term",
        "status": "sugar-gap",
        "observed": "Name",
        "blame": "base64.py:2:15",
        "selected": None,
        "candidates": [],
        "message": str(gap),
    }


def test_factory_matches_registered_sugar_for_last_popped_source_site() -> None:
    source = "def encode_len(data):\n    return len(data)\n"

    @dataclass(frozen=True)
    class NameSugar:
        identifier: str

    def owns_name(site) -> bool:
        return isinstance(site.node, ast.Name)

    def build_name(site) -> NameSugar:
        return NameSugar(site.node.id)

    catalog = SugarCatalog(
        [
            SugarClaim(
                name="python.name",
                role=SugarRole.TERM,
                owns=owns_name,
                build=build_name,
            )
        ]
    )

    result = build_next(source, filename="base64.py", role=SugarRole.TERM, catalog=catalog)

    assert result.sugar == NameSugar("data")
    assert result.audit_row.to_json() == {
        "kind": "factory-audit-row",
        "role": "term",
        "status": "selected",
        "observed": "Name",
        "blame": "base64.py:2:15",
        "selected": "python.name",
        "candidates": ["python.name"],
        "message": "selected Sugar `python.name` for role term at `base64.py:2:15`",
    }
