# SPDX-License-Identifier: MIT OR Apache-2.0
"""Last residual refuse: if-exp, bare return, attr assign, *args/**kwargs, super."""

from __future__ import annotations

import ast

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import lift_file_payload
from sugar_lift_py_tests.sugar.attribute_assign_sugar import AttributeAssignSugar
from sugar_lift_py_tests.sugar.bare_return_sugar import BareReturnSugar
from sugar_lift_py_tests.sugar.if_exp_sugar import IfExpSugar
from sugar_lift_py_tests.sugar.method_call_sugar import MethodCallSugar
from sugar_lift_py_tests.sugar.starred_sugar import StarredSugar
from sugar_lift_py_tests.sugar.try_sugar import TrySugar


def test_if_exp_sugar_owns_and_selects() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    r = build_node(
        ast.parse("1 if True else 2", mode="eval").body,
        filename="t.py",
        role=SugarRole.TERM,
        ctx=ctx,
    )
    assert r.audit_row.selected == "IfExpSugar"
    assert IfExpSugar.owns(
        SourceFragment.from_node(ast.parse("a if b else c", mode="eval").body, "t.py")
    )


def test_bare_return_and_attr_assign_owned() -> None:
    bare = SourceFragment.from_node(ast.parse("def f():\n  return\n").body[0].body[0], "t.py")
    assert BareReturnSugar.owns(bare)
    attr = SourceFragment.from_node(ast.parse("e.payload = None\n").body[0], "t.py")
    assert AttributeAssignSugar.owns(attr)


def test_starred_and_super_method_with_kwargs() -> None:
    star = SourceFragment.from_node(ast.parse("f(*xs)", mode="eval").body, "t.py")
    # Starred is arg child
    args = star.call_args()
    assert any(a.observed == "Starred" for a in args)
    assert StarredSugar.owns(next(a for a in args if a.observed == "Starred"))
    site = SourceFragment.from_node(
        ast.parse("super().unsign(v, *args, **kwargs)", mode="eval").body, "t.py"
    )
    assert MethodCallSugar.owns(site)
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    r = build_node(site.node, filename="t.py", role=SugarRole.TERM, ctx=ctx)
    assert r.audit_row.selected == "MethodCallSugar"


def test_try_multi_still_owns() -> None:
    site = SourceFragment.from_node(
        ast.parse("try:\n  pass\nexcept (TypeError, ValueError):\n  pass\n").body[0],
        "t.py",
    )
    assert TrySugar.owns(site)


def test_loads_unsafe_sdist_lifted() -> None:
    from pathlib import Path

    f = Path(
        "/opt/data/tmp/sugar-sources-cache/itsdangerous/2.2.0/src/tests/"
        "test_itsdangerous/test_serializer.py"
    )
    if not f.is_file():
        return
    src = f.read_text(encoding="utf-8")
    rpc = lift_file_payload(src, str(f)).to_rpc()
    ax = account_lift_coverage(census_source(src, file=str(f)), rpc).to_json()[
        "assertions"
    ]
    assert ax["silently_unaccounted"] == 0
    # loads_unsafe + file load faces: at least 19 of 22 (residual skipkeys)
    assert ax["lifted_cited"] >= 19
    assert ax["refused_loud"] <= 3


def test_suite_residual_at_most_two() -> None:
    from pathlib import Path
    from collections import Counter

    root = Path(
        "/opt/data/tmp/sugar-sources-cache/itsdangerous/2.2.0/src/tests/"
        "test_itsdangerous"
    )
    if not root.is_dir():
        return
    totals = Counter()
    for f in sorted(root.glob("test_*.py")):
        src = f.read_text(encoding="utf-8")
        rpc = lift_file_payload(src, str(f)).to_rpc()
        ax = account_lift_coverage(census_source(src, file=str(f)), rpc).to_json()[
            "assertions"
        ]
        for k in ("stated", "lifted_cited", "refused_loud", "silently_unaccounted"):
            totals[k] += ax.get(k, 0)
    assert totals["silently_unaccounted"] == 0
    assert totals["lifted_cited"] >= 55
    assert totals["refused_loud"] <= 2
