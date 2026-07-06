from __future__ import annotations

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.sugar_body import SugarBody


def test_sugar_body_rejects_non_reducible_sugar_at_construction() -> None:
    with pytest.raises(TypeError, match="SugarBody.sugar must implement desugar"):
        SugarBody(sugar=object(), role=SugarRole.TERM)
