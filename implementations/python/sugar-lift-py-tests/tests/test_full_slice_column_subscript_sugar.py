"""A full first-axis slice plus integer column is one tuple index coordinate."""

from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys

from factory_reduce import reduce_value

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import CallSiteValue, SymbolicValue
from sugar_lift_py_tests.ir import ctor, make_var, num
from sugar_lift_py_tests.lift_rpc import audit_lift_file

NONE = ctor("None", [])


def _site(expr: str) -> SourceFragment:
    return SourceFragment.from_node(ast.parse(expr, mode="eval").body, "vendor.py")


def test_full_slice_integer_column_uses_tuple_index_coordinate() -> None:
    value = reduce_value(
        "values[:, 0]",
        {"values": SymbolicValue(make_var("values"))},
    )

    assert isinstance(value, CallSiteValue)
    assert value.term == ctor(
        "py.subscript",
        [
            make_var("values"),
            ctor(
                "tuple",
                [ctor("py.slice", [NONE, NONE, NONE]), num(0)],
            ),
        ],
    )


def test_other_multiaxis_indexes_stay_outside_the_narrow_partition() -> None:
    catalog = default_catalog()
    for expression in ("values[:, 1:]", "values[:, [0]]", "values[1:, 0]"):
        assert [
            candidate.name
            for candidate in catalog.candidates_for(SugarRole.TERM, _site(expression))
        ] == ["SubscriptSugar"]


def test_owner_is_exactly_full_slice_integer_column_partition() -> None:
    catalog = default_catalog()
    assert [
        candidate.name
        for candidate in catalog.candidates_for(SugarRole.TERM, _site("values[:, 0]"))
    ] == ["FullSliceColumnSubscriptSugar", "SubscriptSugar"]
    selected = build_node(
        _site("values[:, 0]"), filename="vendor.py", role=SugarRole.TERM
    )

    assert selected.audit_row.selected == "FullSliceColumnSubscriptSugar"
    narrow_claim = next(
        claim
        for claim in catalog.claims
        if claim.name == "FullSliceColumnSubscriptSugar"
    )
    assert narrow_claim.comes_before == ("SubscriptSugar",)
    assert [
        candidate.name
        for candidate in catalog.candidates_for(SugarRole.TERM, _site("values[:, 1:]"))
    ] == ["SubscriptSugar"]


def test_full_slice_column_discriminator_runs_both_process_arms() -> None:
    tests_dir = Path(__file__).resolve().parent
    src_dir = tests_dir.parent / "src"
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(tests_dir), str(src_dir))),
    }

    def run(expected_column: int) -> subprocess.CompletedProcess[str]:
        script = f"""\
from factory_reduce import reduce_value
from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.ir import ctor, make_var, num

none = ctor("None", [])
value = reduce_value(
    "values[:, 0]",
    {{"values": SymbolicValue(make_var("values"))}},
)
assert value.term == ctor(
    "py.subscript",
    [
        make_var("values"),
        ctor("tuple", [ctor("py.slice", [none, none, none]), num({expected_column})]),
    ],
)
"""
        return subprocess.run(
            [sys.executable, "-c", script],
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )

    truthful = run(0)
    lying = run(1)

    assert truthful.returncode == 0, truthful.stderr
    assert lying.returncode == 1, lying.stderr


def test_real_frame_file_shape_has_no_subscript_factory_panic() -> None:
    source = """
def first_column(value):
    return value.iloc[:, 0]
"""
    recovered = audit_lift_file(source, "core/frame.py", recover_panics=True)
    assert all(panic.gap["observed"] != "Subscript" for panic in recovered.panics)
