"""The scope law holds for every function's outcome, the carrier included.

One rule (the owner, PR A ruling 2): a function's outcome formula is checked
over its formals plus ``out``; a free variable outside them is a
``FreeVariableRefusal``, and the full scan mint packages turns it into the
function's ``undecided`` row. Before this, a native-operation carrier
(``return x + LIMIT``) skipped the check and the function emitted nothing at
all (#7818's two cases B and C): the proof silently lacked its claims.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests import lift_rpc
from sugar_lift_py_tests import tree_enumerate as _tree
from sugar_lift_py_tests.proofir._errors import FreeVariableRefusal


def _functions(tmp_path: Path, source: str) -> dict:
    path = tmp_path / "m.py"
    path.write_text(source, encoding="utf-8")
    from sugar_source_tree.reporter import CollectingReporter

    tree = lift_rpc.open_source_file_for_construction(
        path, root=tmp_path, reporter=CollectingReporter()
    )
    return {fn.name: fn for fn in tree.functions()}


def test_a_carrier_naming_a_module_level_name_is_refused_by_name(
    tmp_path: Path,
) -> None:
    fns = _functions(tmp_path, "LIMIT = 10\n\n\ndef f(x):\n    return x + LIMIT\n")
    with pytest.raises(FreeVariableRefusal) as refused:
        _tree.function_contract_rows(fns["f"], "m.py")
    assert "LIMIT" in refused.value.names

    row = _tree.refused_function_row(fns["f"], "m.py", refused.value)
    wire = row.to_rpc_with_term_table(None)
    assert wire["kind"] == "undecided"
    assert wire["symbol"].endswith(".f")
    assert wire["site"]["file"] == "m.py"
    assert wire["site"]["startLine"] == 4
    assert set(wire["site"]) == {
        "file",
        "sourceCid",
        "startLine",
        "startCol",
        "endLine",
        "endCol",
    }
    (tag,) = wire["reason"]
    assert tag == "refused"
    assert "illegal free var(s): LIMIT" in wire["reason"]["refused"]["observed"]


def test_a_carrier_inside_its_scope_passes(tmp_path: Path) -> None:
    fns = _functions(tmp_path, "def f(x):\n    return x + 10\n")
    # The control: in scope, so no refusal (the carrier is an effect, no row).
    _tree.function_contract_rows(fns["f"], "m.py")
