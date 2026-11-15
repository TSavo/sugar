from __future__ import annotations

import pytest

from sugar_lift_py_tests.contract_expression import parse_contract_expression


def test_contract_over_an_undecided_call_result_is_not_one_predicate():
    # A renamed, non-vendor callee follows the ordinary CallSiteSugar path,
    # and its result's truth is taken through the one truth rule
    # (``bool_op_sugar.truth_of``).  The call result's type is not decided,
    # so ``bool`` of it may run code and raise: its truth is two faces, not
    # one predicate, and the contract stays loud rather than claiming an
    # unguarded ``py.truthy``.
    with pytest.raises(ValueError, match="not one completed predicate"):
        parse_contract_expression(
            "arbitrary_constructor(arbitrary_formal)", ["arbitrary_formal"]
        )


def test_malformed_contract_expression_stays_loud():
    with pytest.raises(ValueError, match="empty or invalid contract expression"):
        parse_contract_expression("arbitrary_formal +", ["arbitrary_formal"])
