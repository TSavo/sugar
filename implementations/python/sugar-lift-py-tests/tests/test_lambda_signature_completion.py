from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import LambdaCallable, TermValue
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.temporal import TemporalContext


def _site(source: str) -> SourceFragment:
    node = ast.parse(source, mode="eval").body
    return SourceFragment.from_node(node, "vendor.py", source=source)


def _ctx(**values) -> FactoryBuildContext:
    temporal = TemporalContext.empty()
    for name, value in values.items():
        temporal = temporal.bind_value(name, value)
    return FactoryBuildContext(
        filename="vendor.py",
        catalog=default_catalog(),
        temporal=temporal,
    )


def _build(source: str, ctx: FactoryBuildContext | None = None):
    ctx = ctx or _ctx()
    return build_node(
        _site(source),
        filename="vendor.py",
        role=SugarRole.TERM,
        ctx=ctx,
    )


@pytest.mark.parametrize(
    "source",
    (
        "lambda source, f=None: source",
        "lambda x, func=callable, a=args, kw=kwargs: func(x, *a, **kw)",
        "lambda x, a, *, b: x + a + b",
        "lambda x, *, a: x",
        "lambda x, y, b=1: x + y + b",
    ),
)
def test_defaulted_and_keyword_only_lambdas_have_one_owner(source: str) -> None:
    built = _build(source)

    assert type(built.sugar).__name__ == "LambdaSugar"


def test_lambda_defaults_reduce_in_the_definition_temporal() -> None:
    ctx = _ctx(seed=TermValue(4))
    value = complete_value(
        _build("lambda x=seed: x", ctx).sugar.desugar(ctx), owner="test"
    )

    assert isinstance(value, LambdaCallable)
    assert value.parameters == ("x",)
    assert value.default_values == (TermValue(4),)
    assert value.keyword_only_parameters == ()


def test_keyword_only_signature_is_carried_structurally() -> None:
    value = complete_value(
        _build("lambda x, *, required, optional=3: x").sugar.desugar(_ctx()),
        owner="test",
    )

    assert isinstance(value, LambdaCallable)
    assert value.keyword_only_parameters == ("required", "optional")
    assert value.keyword_only_default_values == (None, TermValue(3))


def test_default_values_participate_in_lambda_identity() -> None:
    one = complete_value(_build("lambda x=1: x").sugar.desugar(_ctx()), owner="test")
    two = complete_value(_build("lambda x=2: x").sugar.desugar(_ctx()), owner="test")

    assert one.to_term(owner="test") != two.to_term(owner="test")
    assert one.to_term(owner="test") == ctor(
        "python:lambda",
        [
            ctor(
                "python:lambda_default",
                [str_const("x"), TermValue(1).to_term(owner="test")],
            )
        ],
    )


def test_positional_only_lambda_remains_a_loud_factory_gap() -> None:
    with pytest.raises(FactoryPanic, match="observed=Lambda requested=term"):
        _build("lambda x, /: x")


def test_lambda_signature_discriminator_runs_both_process_arms() -> None:
    tests_dir = Path(__file__).resolve().parent
    src_dir = tests_dir.parent / "src"
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(tests_dir), str(src_dir))),
    }
    script = """\
import ast
import sys
from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory.build import build_node
from sugar_lift_py_tests.factory.source_fragment import SourceFragment

source = "lambda x=1, *, y: x" if sys.argv[1] == "owned" else "lambda x, /: x"
node = ast.parse(source, mode="eval").body
site = SourceFragment.from_node(node, "vendor.py", source=source)
build_node(site, filename="vendor.py", role=SugarRole.TERM)
"""

    owned = subprocess.run(
        [sys.executable, "-c", script, "owned"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    positional_only = subprocess.run(
        [sys.executable, "-c", script, "positional-only"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert owned.returncode == 0, owned.stderr
    assert positional_only.returncode == 1, positional_only.stderr
