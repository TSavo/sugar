from __future__ import annotations

import ast
from pathlib import Path

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import audit_lift_file, lift_file_payload
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.slice_subscript_sugar import SliceSubscriptSugar


def _site(source: str) -> SourceFragment:
    return SourceFragment.from_node(
        ast.parse(source, mode="eval").body, "Lib/datetime.py", source=source
    )


def test_line_preserving_datetime_slice_unit_fixture_lifts_and_cites() -> None:
    source = (
        "\n" * 1505
        + "def _time_repr_slice(s):\n"
        + '    assert s[-1:] == ")"\n'
        + "\n" * 2
        + '    assert s[-1:] == ")"\n'
        + "    return s\n"
        + "\n" * 531
        + "def _datetime_repr_slice(s):\n"
        + '    assert s[-1:] == ")"\n'
        + "\n" * 2
        + '    assert s[-1:] == ")"\n'
        + "    return s\n"
    )
    filename = "Lib/datetime.py"
    payload = lift_file_payload(source, filename).to_rpc()
    assertions = account_lift_coverage(
        census_source(source, file=filename), payload
    ).to_json()["assertions"]

    assert assertions["lifted_cited"] == 4
    assert assertions["refused_loud"] == 0
    assert [locus["line"] for locus in assertions["lifted_loci"]] == [
        1507,
        1510,
        2044,
        2047,
    ]


def test_full_datetime_artifact_accounts_slice_assertions_and_named_blockers(cpython_311_datetime_path) -> None:
    path = cpython_311_datetime_path
    source = path.read_text(encoding="utf-8")
    assert len(source.splitlines()) == 2635

    payload, gaps = audit_lift_file(source, str(path), hold_panic=True)
    payload = payload.to_rpc()
    assertions = account_lift_coverage(
        census_source(source, file=str(path)), payload
    ).to_json()["assertions"]
    lifted_target_lines = {1507, 1510, 2044, 2047}

    assert assertions["stated"] == 45
    assert assertions["lifted_cited"] == 14
    assert lifted_target_lines <= {
        locus["line"] for locus in assertions["lifted_loci"]
    }
    assert any(
        gap.label.endswith(":182:0")
        and gap.info.get("observed") == "GuardedValue"
        for gap in gaps
    )


@pytest.mark.parametrize(
    "source",
    (
        "s[i:]",
        "s[1:3:step]",
        "s[1:3, 0]",
        "3[-1:]",
        "s[(A | B):]",
    ),
)
def test_unowned_slice_shapes_reach_the_loud_none_arm(source: str) -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(source, mode="eval").body

    with pytest.raises(FactoryPanic, match=r"None => panic"):
        result = build_node(node, filename="t.py", role=SugarRole.TERM, ctx=ctx)
        complete_value(result.sugar.desugar(ctx), owner="test")


def test_slice_ownership_is_total_except_bitor_annotation_bounds() -> None:
    assert SliceSubscriptSugar.owns(_site("s[-1:]"))
    assert SliceSubscriptSugar.owns(_site("s[:3]"))
    assert SliceSubscriptSugar.owns(_site("s[-3:-1]"))
    assert SliceSubscriptSugar.owns(_site("s[::2]"))
    assert SliceSubscriptSugar.owns(_site("'abcdef'[-2:]"))
    assert SliceSubscriptSugar.owns(_site("s[i:]"))
    assert SliceSubscriptSugar.owns(_site("s[1:3:step]"))
    assert not SliceSubscriptSugar.owns(_site("s[1:3, 0]"))
    assert SliceSubscriptSugar.owns(_site("3[-1:]"))
    assert not SliceSubscriptSugar.owns(_site("s[(A | B):]"))
