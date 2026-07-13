from __future__ import annotations

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory import build_node, default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment


def test_exceptional_exit_uses_relative_locus_and_source_sha() -> None:
    source = "raise ValueError('bad')\n"
    ctx = FactoryBuildContext(
        filename="/tmp/build/vendor/pkg/module.py", catalog=default_catalog()
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
