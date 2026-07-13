"""A subscript-selected callable is an address-bearing call receiver."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest
from factory_reduce import reduce_value

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import CallSiteValue, SymbolicValue
from sugar_lift_py_tests.ir import ctor, make_var, num, str_const


def _site(expr: str) -> SourceFragment:
    return SourceFragment.from_node(ast.parse(expr, mode="eval").body, "t.py")


def test_subscript_selected_callable_carries_receiver_coordinate() -> None:
    value = reduce_value(
        "dispatch[key](3)",
        binds={
            "dispatch": SymbolicValue(make_var("dispatch")),
            "key": SymbolicValue(make_var("key")),
        },
    )

    assert isinstance(value, CallSiteValue)
    receiver = ctor("py.subscript", [make_var("dispatch"), make_var("key")])
    assert value.target_name == "__call__"
    assert value.arg_values[0].to_term(owner="test") == receiver
    assert value.term == ctor("call:__call__", [receiver, num(3)])


def test_subscript_selected_callable_carries_named_keyword_coordinate() -> None:
    value = reduce_value(
        "dispatch[key](3, axis=1)",
        binds={
            "dispatch": SymbolicValue(make_var("dispatch")),
            "key": SymbolicValue(make_var("key")),
        },
    )

    receiver = ctor("py.subscript", [make_var("dispatch"), make_var("key")])
    assert isinstance(value, CallSiteValue)
    assert value.term == ctor(
        "call:__call__",
        [receiver, num(3), ctor("kw", [str_const("axis"), num(1)])],
    )
    assert value.parameters == ("axis",)


def test_subscript_selected_callable_carries_kwargs_expansion_coordinate() -> None:
    value = reduce_value(
        "dispatch[key](3, **options)",
        binds={
            "dispatch": SymbolicValue(make_var("dispatch")),
            "key": SymbolicValue(make_var("key")),
            "options": SymbolicValue(make_var("options")),
        },
    )

    receiver = ctor("py.subscript", [make_var("dispatch"), make_var("key")])
    assert isinstance(value, CallSiteValue)
    assert value.term == ctor(
        "call:__call__",
        [
            receiver,
            num(3),
            ctor("kw", [str_const("**"), make_var("options")]),
        ],
    )
    assert value.parameters == ("**",)


def test_subscript_named_keyword_value_discriminates_call_coordinate() -> None:
    binds = {
        "dispatch": SymbolicValue(make_var("dispatch")),
        "key": SymbolicValue(make_var("key")),
    }
    truthful = reduce_value("dispatch[key](axis=1)", binds=binds)
    lying = reduce_value("dispatch[key](axis=2)", binds=binds)

    assert truthful.term != lying.term
    assert truthful.parameters == lying.parameters == ("axis",)


def test_subscript_kwargs_expansion_discriminates_call_coordinate() -> None:
    binds = {
        "dispatch": SymbolicValue(make_var("dispatch")),
        "key": SymbolicValue(make_var("key")),
        "left": SymbolicValue(make_var("left")),
        "right": SymbolicValue(make_var("right")),
    }
    truthful = reduce_value("dispatch[key](**left)", binds=binds)
    lying = reduce_value("dispatch[key](**right)", binds=binds)

    assert truthful.term != lying.term
    assert truthful.parameters == lying.parameters == ("**",)


@pytest.mark.parametrize(
    ("expression", "truthful_expected", "lying_expected"),
    [
        (
            "dispatch[key](axis=1)",
            'ctor("kw", [str_const("axis"), num(1)])',
            'ctor("kw", [str_const("axis"), num(2)])',
        ),
        (
            "dispatch[key](**options)",
            'ctor("kw", [str_const("**"), make_var("options")])',
            'ctor("kw", [str_const("**"), make_var("other")])',
        ),
    ],
)
def test_subscript_keyword_discriminator_runs_both_process_arms(
    expression: str,
    truthful_expected: str,
    lying_expected: str,
) -> None:
    tests_dir = Path(__file__).resolve().parent
    src_dir = tests_dir.parent / "src"
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(tests_dir), str(src_dir))),
    }

    def run(expected: str) -> subprocess.CompletedProcess[str]:
        script = f"""\
from factory_reduce import reduce_value
from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.ir import ctor, make_var, num, str_const

binds = {{
    "dispatch": SymbolicValue(make_var("dispatch")),
    "key": SymbolicValue(make_var("key")),
    "options": SymbolicValue(make_var("options")),
}}
value = reduce_value({expression!r}, binds=binds)
receiver = ctor("py.subscript", [make_var("dispatch"), make_var("key")])
assert value.term == ctor("call:__call__", [receiver, {expected}])
"""
        return subprocess.run(
            [sys.executable, "-c", script],
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )

    truthful = run(truthful_expected)
    lying = run(lying_expected)

    assert truthful.returncode == 0, truthful.stderr
    assert lying.returncode == 1, lying.stderr


def test_direct_lambda_callee_stays_loud() -> None:
    with pytest.raises(FactoryPanic):
        build_node(
            ast.parse("(lambda x: x)(3)", mode="eval").body,
            filename="t.py",
            role=SugarRole.TERM,
        )


def test_subscript_call_owner_is_exactly_the_subscript_callee_partition() -> None:
    catalog = default_catalog()

    assert [
        candidate.name
        for candidate in catalog.candidates_for(
            SugarRole.TERM, _site("dispatch[key](3)")
        )
    ] == ["SubscriptCallSugar"]
    assert "SubscriptCallSugar" not in [
        candidate.name
        for candidate in catalog.candidates_for(SugarRole.TERM, _site("f(3)"))
    ]
    assert "SubscriptCallSugar" not in [
        candidate.name
        for candidate in catalog.candidates_for(SugarRole.TERM, _site("f()(3)"))
    ]


@pytest.mark.parametrize(
    "expression",
    ["dispatch[key](axis=1)", "dispatch[key](**options)"],
)
def test_subscript_keyword_call_owner_is_exactly_the_subscript_callee_partition(
    expression: str,
) -> None:
    assert [
        candidate.name
        for candidate in default_catalog().candidates_for(
            SugarRole.TERM, _site(expression)
        )
    ] == ["SubscriptCallSugar"]
