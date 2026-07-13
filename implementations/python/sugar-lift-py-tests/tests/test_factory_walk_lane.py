"""The factory walk lane projects from audit rows the sugar tree already
carries: each SugarBody holds its FactoryAuditRow; walk_children names the
children in source order. No second recognition pass."""

from __future__ import annotations

from sugar_lift_py_tests.lift_rpc import lift_file_payload

_DEMO = (
    "def enc(x):\n"
    '    if x == "ccc":\n'
    '        return "yyy"\n'
    "    return x\n"
    "\n"
    "def A(z):\n"
    "    y = f(3)\n"
    "    assert y == 7\n"
    "    return z\n"
)

_ENC_SELECTED = [
    # One row per source STATEMENT -- term-role children (the if's Compare,
    # the return's literal) render on their statement's line, no row of
    # their own.
    "FunctionDefSugar",
    "IfSugar",
    "ReturnSugar",
    "ReturnSugar",
]


def test_factory_walk_is_nonempty_for_the_demo() -> None:
    payload = lift_file_payload(_DEMO, "vendor.py")
    assert payload.factory_walk
    assert len(payload.factory_walk) > 0


def test_every_walk_row_has_selected_and_locus() -> None:
    payload = lift_file_payload(_DEMO, "vendor.py")
    for row in payload.factory_walk:
        assert row.selected is not None
        assert row.ast_kind
        assert row.file == "vendor.py"
        assert row.line >= 1
        assert "blame" in row.extra


def test_enc_selected_sequence_is_source_order() -> None:
    payload = lift_file_payload(_DEMO, "vendor.py")
    # First FunctionDefSugar through the next FunctionDefSugar (exclusive).
    selected = []
    for row in payload.factory_walk:
        if row.selected == "FunctionDefSugar" and selected:
            break
        selected.append(row.selected)
    assert selected == _ENC_SELECTED


def test_one_statement_def_has_exactly_its_subtree() -> None:
    # def A(z): return z -- statement rows only: FunctionDef, Block, Return.
    source = "def A(z):\n    return z\n"
    payload = lift_file_payload(source, "t.py")
    assert [row.selected for row in payload.factory_walk] == [
        "FunctionDefSugar",
        "ReturnSugar",
    ]
    assert len(payload.factory_walk) == 2
