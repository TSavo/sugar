from __future__ import annotations

import ast

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory import build_node
from sugar_lift_py_tests.outcome import complete_value


def test_alias_sugar_accounts_plain_import_alias_as_inert_binding() -> None:
    alias_node = ast.parse("import numpy as np").body[0].names[0]

    result = build_node(alias_node, filename="imports.py", role=SugarRole.TERM)
    value = complete_value(result.sugar.desugar(None), owner="import alias")

    assert result.sugar.__class__.__name__ == "AliasSugar"
    assert value.__class__.__name__ == "ImportAliasValue"
    assert value.name == "numpy"
    assert value.bound_name == "np"


def test_alias_sugar_accounts_from_import_alias_as_inert_binding() -> None:
    alias_node = ast.parse("from numpy import dtype as np_dtype").body[0].names[0]

    result = build_node(alias_node, filename="imports.py", role=SugarRole.TERM)
    value = complete_value(result.sugar.desugar(None), owner="import alias")

    assert result.sugar.__class__.__name__ == "AliasSugar"
    assert value.name == "dtype"
    assert value.bound_name == "np_dtype"
