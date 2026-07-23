from __future__ import annotations

import inspect

from sugar_lift_python_source import compiler
from sugar_lift_python_source.ir import int_const


def test_renamed_nonvendor_compile_returns_source_not_backend_nodes() -> None:
    source = compiler.compile_body_term(
        int_const(7), fn_name="renamed_nonvendor", formals=["operand"]
    )

    assert source.startswith("def renamed_nonvendor(operand):")
    assert "import ast" not in inspect.getsource(compiler)
    assert not hasattr(compiler, "_compile_contract")
