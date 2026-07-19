# SPDX-License-Identifier: MIT OR Apache-2.0
"""#5603: PytestRaisesWithSugar logo path deleted — rows stay loud.

Bucket (b): testing kit/bridge contract only. Raise statement construction is
orthogonal and still owned; pytest.raises with-forms are not.
"""

from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.sugar.pytest_raises_with_sugar import PytestRaisesWithSugar


def test_raise_statement_still_constructs_without_pytest_logo() -> None:
    """Plain raise is language-level; not gated on testing-framework logos."""
    source = (
        "def boom():\n"
        "    raise ValueError('x')\n"
    )
    raise_node = next(
        node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Raise)
    )
    site = SourceFragment.from_node(raise_node, "t.py", source=source)
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    built = build_node(site, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert built.audit_row.selected == "RaiseSugar"


def test_pytest_raises_with_stays_loud_without_kit_contract() -> None:
    source = (
        "import pytest\n"
        "def boom():\n"
        "    raise ValueError('x')\n"
        "def test_r():\n"
        "    with pytest.raises(ValueError):\n"
        "        boom()\n"
    )
    with_node = next(
        node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.With)
    )
    site = SourceFragment.from_node(with_node, "t.py", source=source)
    assert PytestRaisesWithSugar.owns(site) is False
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    try:
        built = build_node(site, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
        assert built.audit_row.selected != "PytestRaisesWithSugar"
    except FactoryPanic as raised:
        assert raised.info.observed in {"With", "Call", "pytest"}
