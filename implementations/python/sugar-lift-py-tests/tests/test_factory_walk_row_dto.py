from __future__ import annotations

import pytest

from sugar_lift_py_tests.kit_rpc.factory_walk_row_dto import FactoryWalkRowDto


def test_unknown_status_panics_instead_of_defaulting():
    with pytest.raises(TypeError, match="brand-new-status"):
        FactoryWalkRowDto(
            file="f.py",
            line=1,
            requested_role="TERM",
            ast_kind="Call",
            selected=None,
            status="brand-new-status",
            output=None,
            source_memento={},
        )
