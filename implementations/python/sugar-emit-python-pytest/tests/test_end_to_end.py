"""End-to-end: contract in -> pytest source out -> emitted test runs GREEN.

This is the strongest verification the brief asks for. For each supported
predicate we build a contract, emit a pytest module, write it to a tmp file,
run ``pytest`` on it in a subprocess, and assert returncode == 0. The
placeholder values are chosen per-predicate (see
``predicate_table.placeholder_value``) so the emitted assertions actually
PASS, not merely compile/import.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from sugar_emit_python_pytest.emitter import EmitPlan, emit


def _op(name: str, *args: dict) -> dict:
    return {"kind": "op", "name": name, "args": list(args)}


def _var(name: str) -> dict:
    return {"kind": "var", "name": name}


def _run_pytest_on(source: str, tmp_path) -> subprocess.CompletedProcess:
    module = tmp_path / "test_emitted_contract.py"
    module.write_text(source, encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(module), "-q"],
        capture_output=True,
        text=True,
    )


# (predicate name, predicate term) for every supported predicate.
SUPPORTED_CASES = [
    ("eq", _op("concept:eq", _var("a"), _var("b"))),
    ("ne", _op("concept:ne", _var("a"), _var("b"))),
    ("lt", _op("concept:lt", _var("a"), _var("b"))),
    ("gt", _op("concept:gt", _var("a"), _var("b"))),
    ("le", _op("concept:le", _var("a"), _var("b"))),
    ("ge", _op("concept:ge", _var("a"), _var("b"))),
    ("option-is-some", _op("concept:option-is-some", _var("x"))),
    ("option-is-none", _op("concept:option-is-none", _var("x"))),
    ("fallible-err", _op("concept:fallible-err", _var("f"))),
]


@pytest.mark.parametrize(
    "name,predicate", SUPPORTED_CASES, ids=[c[0] for c in SUPPORTED_CASES]
)
def test_each_supported_predicate_emits_green_pytest(name, predicate, tmp_path) -> None:
    plan = EmitPlan(function=name.replace("-", "_"), predicates=[predicate])
    emission = emit(plan)
    assert emission.is_complete, emission.unsupported_predicates

    result = _run_pytest_on(emission.source, tmp_path)
    assert result.returncode == 0, (
        f"emitted test for {name!r} failed:\n"
        f"--- source ---\n{emission.source}\n--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )


def test_multi_predicate_contract_emits_green(tmp_path) -> None:
    # A realistic clamp contract: x >= lo AND x <= hi, plus option-is-some.
    plan = EmitPlan(
        contract_id="concept:clamp",
        function="clamp",
        params=["x", "lo", "hi"],
        param_types=["int", "int", "int"],
        predicates=[
            _op("concept:ge", _var("x"), _var("lo")),
            _op("concept:le", _var("x"), _var("hi")),
            _op("concept:option-is-some", _var("result")),
        ],
    )
    emission = emit(plan)
    assert emission.is_complete

    result = _run_pytest_on(emission.source, tmp_path)
    assert result.returncode == 0, (
        f"--- source ---\n{emission.source}\n--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
