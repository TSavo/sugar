from __future__ import annotations

import pytest

from sugar_lift_python_source.compiler import compile_body_term


def test_compiler_adapter_is_general_over_function_spelling() -> None:
    source = compile_body_term(
        {"name": "python:return", "args": [{"kind": "const", "value": 1}]},
        fn_name="renamed_guard",
    )

    assert source == "def renamed_guard():\n    return 1\n"


def test_compiler_adapter_keeps_unknown_term_loud() -> None:
    malformed = {
        "name": "python:return",
        "args": [{"name": "python:unknown", "args": []}],
    }

    with pytest.raises(ValueError, match="unsupported term kind"):
        compile_body_term(malformed, fn_name="renamed_guard")
