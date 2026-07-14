from __future__ import annotations

import ast
from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.floor import DictValue, StringValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.sugar.dict_literal_sugar import DictLiteralSugar


def _build(source: str):
    node = ast.parse(source, mode="eval").body
    ctx = FactoryBuildContext(filename="vendor.py", catalog=default_catalog())
    return (
        build_node(
            node,
            filename="vendor.py",
            role=SugarRole.TERM,
            ctx=ctx,
        ),
        ctx,
    )


def test_concrete_dict_unpack_merges_in_source_order() -> None:
    built, ctx = _build('{**{"a": 1}, "a": 2, **{"b": 3}}')

    assert built.sugar.desugar(ctx) == Complete(
        DictValue(
            (
                (StringValue("a"), TermValue(2)),
                (StringValue("b"), TermValue(3)),
            )
        )
    )


def test_runtime_mapping_unpack_yields_named_witnessed_effect() -> None:
    built, ctx = _build('{"fixed": 1, **mapping}')
    ctx = replace(
        ctx,
        temporal=ctx.temporal.bind_value("mapping", SymbolicValue(make_var("mapping"))),
    )

    outcome = built.sugar.desugar(ctx)

    assert isinstance(outcome, Incomplete)
    assert type(outcome.effect).__name__ == "DictUnpackRuntimeEffect"
    assert outcome.effect.witness.operation.name == "py.dict_unpack"
    assert outcome.effect.witness.locus == "vendor.py:1:0"


def test_dict_unpack_owner_is_disjoint_from_call_kwargs_unpack() -> None:
    built, _ctx = _build("{**mapping}")
    assert isinstance(built.sugar, DictLiteralSugar)

    node = ast.parse("dict(**mapping)", mode="eval").body
    ctx = FactoryBuildContext(filename="vendor.py", catalog=default_catalog())
    call = build_node(
        node,
        filename="vendor.py",
        role=SugarRole.TERM,
        ctx=ctx,
    )
    assert type(call.sugar).__name__ == "KeywordCallSugar"


def test_dict_unpack_discriminator_runs_both_process_arms() -> None:
    tests_dir = Path(__file__).resolve().parent
    src_dir = tests_dir.parent / "src"
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(tests_dir), str(src_dir))),
    }

    def run(expected: int) -> subprocess.CompletedProcess[str]:
        script = f"""\
import ast
from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.floor import StringValue, TermValue

node = ast.parse('{{**{{"a": 1}}, "a": 2}}', mode="eval").body
ctx = FactoryBuildContext(filename="vendor.py", catalog=default_catalog())
built = build_node(node, filename="vendor.py", role=SugarRole.TERM, ctx=ctx)
outcome = built.sugar.desugar(ctx)
value = outcome.value.subscript(StringValue("a"), built.sugar.site).value
assert value == TermValue({expected})
"""
        return subprocess.run(
            [sys.executable, "-c", script],
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )

    truthful = run(2)
    lying = run(1)
    assert truthful.returncode == 0, truthful.stderr
    assert lying.returncode == 1, lying.stderr
