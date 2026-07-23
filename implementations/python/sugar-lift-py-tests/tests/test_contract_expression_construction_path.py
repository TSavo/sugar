from __future__ import annotations

import pytest

from sugar_lift_py_tests.contract_expression import parse_contract_expression


def test_renamed_contract_expression_uses_ordinary_call_and_formal_construction():
    formula = parse_contract_expression(
        "arbitrary_constructor(arbitrary_formal)", ["arbitrary_formal"]
    )

    # A renamed, non-vendor callee follows the ordinary CallSiteSugar path.
    # The old private evaluator emitted an unrelated ctor named only by the
    # parsed spelling; the sole path emits the native call coordinate.
    rendered = repr(formula)
    assert "call:arbitrary_constructor" in rendered
    assert "arbitrary_formal" in rendered
    assert "py.truthy" in rendered


def test_malformed_contract_expression_stays_loud():
    with pytest.raises(ValueError, match="empty or invalid contract expression"):
        parse_contract_expression("arbitrary_formal +", ["arbitrary_formal"])
