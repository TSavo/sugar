# SPDX-License-Identifier: MIT OR Apache-2.0

from __future__ import annotations

import pytest

from sugar_lift_py_tests.decorators import (
    contract,
    ContractViolation,
    collect_module,
)
from sugar_lift_py_tests.ir import (
    _Atomic,
    _Connective,
    _Ctor,
    atomic,
    eq,
    gt,
    gte,
    make_var,
    num,
    str_const,
    bool_const,
)


def _flatten_and(formula):
    if isinstance(formula, _Connective) and formula.kind == "and":
        out = []
        for operand in formula.operands:
            out.extend(_flatten_and(operand))
        return out
    return [formula]


def _assert_none_guard_formula(formula, *, comparison_name: str, guard_name: str):
    atoms = [atom for atom in _flatten_and(formula) if isinstance(atom, _Atomic)]
    assert any(
        atom.name == comparison_name
        and len(atom.args) == 2
        and isinstance(atom.args[1], _Ctor)
        and atom.args[1].name == "None"
        for atom in atoms
    )
    guards = [atom for atom in atoms if atom.name == guard_name]
    assert len(guards) == 1
    assert ":" not in guards[0].name
    assert len(guards[0].args) == 1


class TestContractDecorator:
    def test_precondition_string_expr(self):
        @contract(pre="x >= 0")
        def abs_(x: int) -> int:
            return x if x >= 0 else -x

        decl = abs_._sugar_contract
        assert (
            decl.name
            == "TestContractDecorator.test_precondition_string_expr.<locals>.abs_"
        )
        assert decl.pre is not None

    def test_postcondition_string_expr(self):
        @contract(pre="x >= 0", post="out >= 0")
        def sqrt(x: float) -> float:
            return x**0.5

        decl = sqrt._sugar_contract
        assert decl.pre is not None
        assert decl.post is not None
        assert decl.out_binding == "out"

    def test_none_string_expr_emits_substrate_guard_fact(self):
        @contract(pre="x is not None")
        def identity(x: object) -> object:
            return x

        decl = identity._sugar_contract
        assert decl.pre is not None
        _assert_none_guard_formula(
            decl.pre,
            comparison_name="≠",
            guard_name="is_some",
        )

    def test_runtime_precondition_passes(self):
        @contract(pre=lambda x: x >= 0)
        def abs_(x: int) -> int:
            return x if x >= 0 else -x

        assert abs_(5) == 5

    def test_runtime_precondition_fails(self):
        @contract(pre=lambda x: x >= 0)
        def abs_(x: int) -> int:
            return x if x >= 0 else -x

        with pytest.raises(ContractViolation):
            abs_(-1)

    def test_collect_module(self):
        # Build a temporary module-like namespace with decorated functions.
        import types

        mod = types.ModuleType("test_mod")

        @contract(pre="x >= 0")
        def func_a(x: int) -> int:
            return x

        @contract(pre="y > 0", post="out > 0")
        def func_b(y: int) -> int:
            return y

        mod.func_a = func_a
        mod.func_b = func_b

        decls = collect_module(mod)
        names = [d.name for d in decls]
        assert any("func_a" in n for n in names)
        assert any("func_b" in n for n in names)
