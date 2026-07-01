"""End-to-end: emit unittest source and run it with the stdlib test runner."""

from __future__ import annotations

import subprocess
import sys

import pytest

from sugar_emit_python_unittest.emitter import EmitPlan, emit


def _atomic(name: str, *args: dict) -> dict:
    return {"kind": "atomic", "name": name, "args": list(args)}


def _var(name: str) -> dict:
    return {"kind": "var", "name": name}


def _run_unittest_on(source: str, tmp_path) -> subprocess.CompletedProcess:
    module = tmp_path / "test_emitted_contract.py"
    module.write_text(source, encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", str(tmp_path)],
        capture_output=True,
        text=True,
    )


SUPPORTED_CASES = [
    ("eq", _atomic("concept:eq", _var("a"), _var("b"))),
    ("ne", _atomic("concept:ne", _var("a"), _var("b"))),
    ("lt", _atomic("concept:lt", _var("a"), _var("b"))),
    ("gt", _atomic("concept:gt", _var("a"), _var("b"))),
    ("le", _atomic("concept:le", _var("a"), _var("b"))),
    ("ge", _atomic("concept:ge", _var("a"), _var("b"))),
    ("option-is-some", _atomic("concept:option-is-some", _var("x"))),
    ("option-is-none", _atomic("concept:option-is-none", _var("x"))),
    ("fallible-err", _atomic("concept:fallible-err", _var("f"))),
]


@pytest.mark.parametrize(
    "name,predicate", SUPPORTED_CASES, ids=[c[0] for c in SUPPORTED_CASES]
)
def test_each_supported_predicate_emits_green_unittest(
    name, predicate, tmp_path
) -> None:
    emission = emit(EmitPlan(function=name.replace("-", "_"), predicates=[predicate]))

    assert emission.is_complete, emission.unsupported_predicates
    result = _run_unittest_on(emission.source, tmp_path)
    assert result.returncode == 0, (
        f"emitted test for {name!r} failed:\n"
        f"--- source ---\n{emission.source}\n--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )


def test_multi_predicate_contract_emits_green(tmp_path) -> None:
    emission = emit(
        EmitPlan(
            contract_id="concept:clamp",
            function="clamp",
            params=["x", "lo", "hi"],
            param_types=["int", "int", "int"],
            predicates=[
                _atomic("concept:ge", _var("x"), _var("lo")),
                _atomic("concept:le", _var("x"), _var("hi")),
                _atomic("concept:option-is-some", _var("result")),
            ],
        )
    )

    assert emission.is_complete
    result = _run_unittest_on(emission.source, tmp_path)
    assert result.returncode == 0, (
        f"--- source ---\n{emission.source}\n--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
