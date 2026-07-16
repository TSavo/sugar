from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.outcome import complete_value


def _union_site(source: str) -> SourceFragment:
    module = ast.parse(source)
    node = next(node for node in ast.walk(module) if isinstance(node, ast.BinOp))
    return SourceFragment.from_node(node, "union.py", source=source)


def _runtime_site(source: str) -> SourceFragment:
    node = ast.parse(source, mode="eval").body
    return SourceFragment.from_node(node, "runtime.py", source=source)


def test_annotation_union_builds_the_native_union_coordinate() -> None:
    source = "def accept(value: int | str) -> None:\n    pass\n"
    ctx = FactoryBuildContext(filename="union.py", catalog=default_catalog())

    result = build_node(
        _union_site(source), filename="union.py", role=SugarRole.TERM, ctx=ctx
    )

    assert result.audit_row.selected == "AnnotationUnionSugar"
    assert complete_value(result.sugar.desugar(ctx), owner="test") == SymbolicValue(
        ctor(
            "|",
            [
                ctor("python:type", [str_const("int")]),
                ctor("python:type", [str_const("str")]),
            ],
        )
    )


def test_sourceless_annassign_carries_annotation_position_testimony() -> None:
    statement = ast.parse("value: int | str").body[0]
    site = SourceFragment.from_node(statement, "installed.py")
    annotation = site.annassign_annotation()
    ctx = FactoryBuildContext(filename="installed.py", catalog=default_catalog())

    result = build_node(
        annotation, filename="installed.py", role=SugarRole.TERM, ctx=ctx
    )

    assert result.audit_row.selected == "AnnotationUnionSugar"
    assert complete_value(result.sugar.desugar(ctx), owner="test") == SymbolicValue(
        ctor(
            "|",
            [
                ctor("python:type", [str_const("int")]),
                ctor("python:type", [str_const("str")]),
            ],
        )
    )


def test_sourceless_nested_annassign_union_marks_the_whole_annotation_tree() -> None:
    statement = ast.parse("value: int | str | bytes").body[0]
    site = SourceFragment.from_node(statement, "installed.py")
    annotation = site.annassign_annotation()
    ctx = FactoryBuildContext(filename="installed.py", catalog=default_catalog())

    result = build_node(
        annotation, filename="installed.py", role=SugarRole.TERM, ctx=ctx
    )

    assert result.audit_row.selected == "AnnotationUnionSugar"
    assert result.sugar.left.sugar.__class__.__name__ == "AnnotationUnionSugar"
    assert complete_value(result.sugar.desugar(ctx), owner="test") == SymbolicValue(
        ctor(
            "|",
            [
                ctor(
                    "|",
                    [
                        ctor("python:type", [str_const("int")]),
                        ctor("python:type", [str_const("str")]),
                    ],
                ),
                ctor("python:type", [str_const("bytes")]),
            ],
        )
    )


def test_annotation_union_discriminator_runs_both_process_arms() -> None:
    tests_dir = Path(__file__).resolve().parent
    src_dir = tests_dir.parent / "src"
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(tests_dir), str(src_dir))),
    }
    source = "def accept(value: int | str) -> None:\n    pass\n"

    def run(expected: str) -> subprocess.CompletedProcess[str]:
        script = f"""\
import ast
from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.outcome import complete_value

source = {source!r}
node = next(node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.BinOp))
site = SourceFragment.from_node(node, "union.py", source=source)
ctx = FactoryBuildContext(filename="union.py", catalog=default_catalog())
value = complete_value(
    build_node(site, filename="union.py", role=SugarRole.TERM, ctx=ctx).sugar.desugar(ctx),
    owner="test",
)
assert value.term == {expected}
"""
        return subprocess.run(
            [sys.executable, "-c", script],
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )

    truthful = run(
        'ctor("|", [ctor("python:type", [str_const("int")]), '
        'ctor("python:type", [str_const("str")])])'
    )
    lying = run(
        'ctor("|", [ctor("python:type", [str_const("str")]), '
        'ctor("python:type", [str_const("int")])])'
    )

    assert truthful.returncode == 0, truthful.stderr
    assert lying.returncode == 1, lying.stderr


def test_sourceless_annotation_discriminator_runs_both_process_arms() -> None:
    tests_dir = Path(__file__).resolve().parent
    src_dir = tests_dir.parent / "src"
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(tests_dir), str(src_dir))),
    }

    def run(expected_right: str) -> subprocess.CompletedProcess[str]:
        script = f"""\
import ast
from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.outcome import complete_value

statement = ast.parse("value: int | str").body[0]
site = SourceFragment.from_node(statement, "installed.py").annassign_annotation()
ctx = FactoryBuildContext(filename="installed.py", catalog=default_catalog())
value = complete_value(
    build_node(site, filename="installed.py", role=SugarRole.TERM, ctx=ctx).sugar.desugar(ctx),
    owner="test",
)
assert value.term == ctor(
    "|",
    [ctor("python:type", [str_const("int")]), ctor("python:type", [str_const({expected_right!r})])],
)
"""
        return subprocess.run(
            [sys.executable, "-c", script],
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )

    truthful = run("str")
    lying = run("bytes")
    assert truthful.returncode == 0, truthful.stderr
    assert lying.returncode == 1, lying.stderr


def test_annotation_and_runtime_bit_or_have_disjoint_factory_owners() -> None:
    catalog = default_catalog()
    annotation = _union_site("def accept(value: int | str) -> None:\n    pass\n")
    runtime = _runtime_site("x | y")

    assert [
        candidate.name
        for candidate in catalog.candidates_for(SugarRole.TERM, annotation)
    ] == ["AnnotationUnionSugar"]
    assert [
        candidate.name for candidate in catalog.candidates_for(SugarRole.TERM, runtime)
    ] == ["RuntimeBitwiseOpSugar"]


def test_sourceful_annotation_membership_follows_only_the_parent_chain() -> None:
    cases = (
        ("def f(value: list[ArgType]):\n    pass\n", "ArgType", True),
        ("def f() -> list[ReturnType]:\n    pass\n", "ReturnType", True),
        ("value: list[AssignedType] = []\n", "AssignedType", True),
        ("value = list[RuntimeType]\n", "RuntimeType", False),
    )

    for source, name, expected in cases:
        node = next(
            node
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Name) and node.id == name
        )
        site = SourceFragment.from_node(node, "membership.py", source=source)
        assert site.is_within_annotation() is expected


def test_sourceless_runtime_bit_or_stays_unowned_and_loud() -> None:
    catalog = default_catalog()
    runtime = SourceFragment.from_node(
        ast.parse("x | y", mode="eval").body,
        "installed.py",
    )

    assert catalog.candidates_for(SugarRole.TERM, runtime) == []
