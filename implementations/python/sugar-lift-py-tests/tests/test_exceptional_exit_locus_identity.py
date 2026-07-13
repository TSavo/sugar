from __future__ import annotations

import json

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.lift_rpc import _lift_file_for_enumeration


def test_exceptional_exit_uses_relative_locus_and_source_sha() -> None:
    source = "raise ValueError('bad')\n"
    ctx = FactoryBuildContext(
        filename="vendor/pkg/module.py", catalog=default_catalog()
    )
    site = SourceFragment.from_source(source, ctx.filename).statements()[0]
    sugar = build_node(
        site,
        filename=ctx.filename,
        role=SugarRole.STATEMENT,
        ctx=ctx,
    ).sugar
    value = sugar.desugar(ctx).value
    formula = value.post_contribution()[0]

    rendered = repr(formula)
    assert "/tmp/" not in rendered
    assert "vendor/pkg/module.py:1:0" in rendered
    assert "#source-sha256=" in rendered


def test_exceptional_exit_refuses_an_absolute_uncanonicalized_locus() -> None:
    source = "raise ValueError('bad')\n"
    filename = "/tmp/build/vendor/pkg/module.py"
    ctx = FactoryBuildContext(filename=filename, catalog=default_catalog())
    site = SourceFragment.from_source(source, filename).statements()[0]
    sugar = build_node(
        site, filename=filename, role=SugarRole.STATEMENT, ctx=ctx
    ).sugar

    with pytest.raises(FactoryPanic, match="workspace-relative source locus"):
        sugar.desugar(ctx)


def test_same_source_under_two_workspaces_has_identical_contract_identity(tmp_path) -> None:
    source = "def stop():\n    raise TypeError('bad')\n"
    relative = "vendor/pkg/module.py"
    payloads = []
    for workspace_name in ("first-workspace", "second-workspace"):
        root = tmp_path / workspace_name
        path = root / relative
        path.parent.mkdir(parents=True)
        path.write_text(source)
        ir, _edges = _lift_file_for_enumeration(str(root), root, relative)
        payloads.append(ir)

    assert payloads[0] == payloads[1]
    rendered = json.dumps(payloads[0], sort_keys=True)
    assert str(tmp_path) not in rendered
    assert f"{relative}:2:4" in rendered
    assert "#source-sha256=" in rendered
