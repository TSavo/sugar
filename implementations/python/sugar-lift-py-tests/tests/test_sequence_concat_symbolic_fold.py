"""py.sequence_concat accepts a constructed symbolic fold (comprehension).

Residual: RuntimeEffect over ComprehensionValue failed because
is_lift_time_decidable did not know _Lambda inside py.listcomp, and concat
minted RuntimeEffect instead of a symbolic + coordinate.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.effect.runtime_effect import is_lift_time_decidable
from sugar_lift_py_tests.floor.comprehension_value import ComprehensionValue
from sugar_lift_py_tests.floor.list_value import ListValue
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.floor.universe_value import UniverseValue
from sugar_lift_py_tests.ir import PrimitiveSort, _Lambda, ctor, make_var, num
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1


def test_lambda_body_is_not_lift_time_decidable() -> None:
    body = make_var("p")
    lam = _Lambda("p", PrimitiveSort("Value"), body)
    term = ctor(
        "py.listcomp",
        [make_var("xs"), lam, ctor("python:loop.exhaustion", [])],
    )
    assert is_lift_time_decidable(term) is False
    assert is_lift_time_decidable(lam) is False


def test_list_plus_comprehension_constructs_symbolic_concat() -> None:
    left = ListValue((TermValue(1),))
    right = ComprehensionValue(
        ctor(
            "py.listcomp",
            [
                make_var("xs"),
                _Lambda("p", PrimitiveSort("Value"), make_var("p")),
                ctor("python:loop.exhaustion", []),
            ],
        )
    )

    class _Site:
        filename = "test_sequence_concat_symbolic_fold.py"
        line = 1
        col = 0

    out = left.add(right, site=_Site())
    assert isinstance(out, Complete)
    assert isinstance(out.value, ComprehensionValue)
    assert out.value.term.name == "+"  # type: ignore[attr-defined]


def test_source_list_plus_comprehension_returns_universe(tmp_path: Path) -> None:
    path = tmp_path / "t.py"
    path.write_text(
        "def f(xs):\n" "    return [1] + [x for x in xs]\n",
        encoding="utf-8",
    )
    fn = next(
        SourceFile(
            path_source(str(path)),
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        ).functions()
    )
    out = fn.sugar().desugar(None)
    assert isinstance(out, Complete)
    assert isinstance(out.value, UniverseValue)
