from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import audit_lift_file

PREFIX = """\
class Clock:
    def replace(self, hour=0):
        return Clock()

    def utcoffset(self):
        return 0

    def check(self):
"""


def _audit(body: str):
    source = PREFIX + body
    payload, gaps = audit_lift_file(source, "clock.py", hold_panic=True)
    assertions = account_lift_coverage(
        census_source(source, file="clock.py"), payload.to_rpc()
    ).to_json()["assertions"]
    return payload.to_rpc(), gaps, assertions


def test_chained_method_call_is_the_same_linear_temporal_rewrite() -> None:
    two_line, two_line_gaps, two_line_axis = _audit(
        "        tmp = self.replace(hour=0)\n" "        assert tmp.utcoffset() == 0\n"
    )
    chained, chained_gaps, chained_axis = _audit(
        "        assert self.replace(hour=0).utcoffset() == 0\n"
    )

    assert two_line_gaps == []
    assert chained_gaps == []
    for axis in (two_line_axis, chained_axis):
        assert axis["stated"] == 1
        assert axis["lifted_cited"] == 1
        assert axis["refused_loud"] == 0
        assert axis["silently_unaccounted"] == 0
    two_line_contract = next(row for row in two_line["ir"] if row["kind"] == "contract")
    chained_contract = next(row for row in chained["ir"] if row["kind"] == "contract")
    assert two_line_contract["inv"] == chained_contract["inv"]


@pytest.mark.parametrize(
    "expression",
    ["pd_array(values).isin(needles)", "CategoricalDtype().update_dtype(dtype)"],
)
def test_plain_call_receiver_method_chain_constructs(expression: str) -> None:
    node = ast.parse(expression, mode="eval").body

    built = build_node(node, filename="pandas.py", role=SugarRole.TERM)

    assert type(built.sugar).__name__ == "MethodChainSugar"


def test_unclassifiable_chained_receiver_stays_loud() -> None:
    node = ast.parse("(lambda: 1)().bit_length()", mode="eval").body
    with pytest.raises(FactoryPanic):
        build_node(node, filename="bad.py", role=SugarRole.TERM)


@pytest.mark.parametrize(
    "expression",
    ["pd_array(values).isin(needles)", "CategoricalDtype().update_dtype(dtype)"],
)
def test_plain_call_receiver_chain_discriminator_runs_both_process_arms(
    expression: str,
) -> None:
    tests_dir = Path(__file__).resolve().parent
    src_dir = tests_dir.parent / "src"
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(tests_dir), str(src_dir))),
    }
    script = f"""\
import ast
from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory.build import build_node

built = build_node(ast.parse({expression!r}, mode="eval").body, filename="pandas.py", role=SugarRole.TERM)
assert type(built.sugar).__name__ == "{{expected}}"
"""

    truthful = subprocess.run(
        [sys.executable, "-c", script.format(expected="MethodChainSugar")],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    lying = subprocess.run(
        [sys.executable, "-c", script.format(expected="MethodCallSugar")],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert truthful.returncode == 0, truthful.stderr
    assert lying.returncode == 1, lying.stderr


def test_method_chain_has_one_factory_owner() -> None:
    node = ast.parse("self.replace(hour=0).utcoffset()", mode="eval").body
    site = SourceFragment.from_node(node, "clock.py")

    assert {
        candidate.name
        for candidate in default_catalog().candidates_for(SugarRole.TERM, site)
    } == {"MethodChainSugar", "MethodCallSugar"}
    assert (
        type(build_node(node, filename="clock.py", role=SugarRole.TERM).sugar).__name__
        == "MethodChainSugar"
    )


@pytest.mark.parametrize(
    "expression",
    ["pd_array(values).isin(needles)", "CategoricalDtype().update_dtype(dtype)"],
)
def test_plain_call_receiver_chain_keeps_the_method_chain_owner_partition(
    expression: str,
) -> None:
    site = SourceFragment.from_node(
        ast.parse(expression, mode="eval").body, "pandas.py"
    )

    assert {
        candidate.name
        for candidate in default_catalog().candidates_for(SugarRole.TERM, site)
    } == {"MethodChainSugar", "MethodCallSugar"}
    assert (
        type(
            build_node(
                ast.parse(expression, mode="eval").body,
                filename="pandas.py",
                role=SugarRole.TERM,
            ).sugar
        ).__name__
        == "MethodChainSugar"
    )
