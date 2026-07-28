"""Hypothesis emission behavior: @given shell, dependent draws, honest gaps."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from declared_corpus import require_declared_corpus

from sugar_emit_python_hypothesis.emitter import EmitPlan, emit


def _op(name: str, *args: dict) -> dict:
    return {"kind": "op", "name": name, "args": list(args)}


def _var(name: str) -> dict:
    return {"kind": "var", "name": name}


def _const(value: object) -> dict:
    return {"kind": "const", "value": value}


def test_emits_hypothesis_given_with_dependent_integer_draws() -> None:
    plan = EmitPlan(
        contract_id="concept:lt",
        function="ordered",
        params=["x", "y"],
        param_types=["int", "int"],
        predicates=[_op("concept:lt", _var("x"), _var("y"))],
    )

    emission = emit(plan)

    assert emission.kind == "hypothesis-test-emission"
    assert emission.path == "test_ordered_hypothesis_contract.py"
    assert "from hypothesis import given, strategies as st" in emission.source
    assert "@given(data=st.data())" in emission.source
    assert "x = data.draw(st.integers())" in emission.source
    assert "y = data.draw(st.integers(min_value=x + 1))" in emission.source
    assert "assert x < y" in emission.source
    assert emission.emitted_predicates == ["lt"]
    assert emission.unsupported_predicates == []
    assert emission.is_complete


def test_constrains_variable_against_integer_constants() -> None:
    emission = emit(
        EmitPlan(
            function="bounded",
            predicates=[
                _op("concept:ge", _var("value"), _const(10)),
                _op("concept:le", _var("value"), _const(20)),
            ],
        )
    )

    assert "value = data.draw(st.integers(min_value=10))" in emission.source
    assert "value = data.draw(st.integers(max_value=20))" in emission.source
    assert "assert value >= 10" in emission.source
    assert "assert value <= 20" in emission.source
    assert emission.emitted_predicates == ["ge", "le"]


def test_unsupported_predicate_recorded_as_gap_not_emitted() -> None:
    emission = emit(
        EmitPlan(
            function="mixed",
            predicates=[
                _op("concept:eq", _var("a"), _var("b")),
                _op("concept:fallible-err", _var("callback")),
                _op("concept:lt", _op("+", _var("a"), _const(1)), _var("b")),
            ],
        )
    )

    assert emission.emitted_predicates == ["eq"]
    assert emission.unsupported_predicates == ["fallible-err", "lt"]
    assert not emission.is_complete
    assert "callback" not in emission.source
    assert "(a + 1)" not in emission.source


def test_emitted_supported_predicates_run_under_pytest(tmp_path: Path) -> None:
    # hypothesis is a HARD dependency of this package
    # (pyproject: dependencies = ["blake3>=1.0.0", "hypothesis>=6.0.0"]).
    # The package exists to emit Hypothesis tests; skipping its emission law
    # when Hypothesis is absent reported green on every machine lacking a
    # REQUIRED dependency.
    try:
        import hypothesis  # noqa: F401
    except ImportError:
        require_declared_corpus(
            "hypothesis is not importable",
            "the environment running this package's suite",
            'sugar-emit-python-hypothesis pyproject.toml [project] dependencies '
            '= ["blake3>=1.0.0", "hypothesis>=6.0.0"] -- a HARD dependency, '
            "not an extra",
            "pip install -e 'implementations/python/sugar-emit-python-hypothesis'",
        )
    predicates = [
        _op("concept:eq", _var("a"), _var("b")),
        _op("concept:ne", _var("a"), _var("b")),
        _op("concept:lt", _var("a"), _var("b")),
        _op("concept:gt", _var("a"), _var("b")),
        _op("concept:le", _var("a"), _var("b")),
        _op("concept:ge", _var("a"), _var("b")),
        _op("concept:option-is-none", _var("maybe")),
        _op("concept:option-is-some", _var("maybe")),
    ]
    emission = emit(EmitPlan(function="all_supported", predicates=predicates))
    assert emission.unsupported_predicates == []

    target = tmp_path / emission.path
    target.write_text(emission.source, encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", str(target), "-q"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
