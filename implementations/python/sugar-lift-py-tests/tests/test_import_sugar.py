"""The import sugar: a callee reached through `import` is dug into its OWN
installed source, so the factory walks its body like a local function. Proven
here with a base64 encoder pulled from a separate module (no .proof) -- the dig
emits the str.eq-bv-blocks universe walked from the imported source."""

from __future__ import annotations

import json
import textwrap

from sugar_lift_py_tests.floor import ArrayLiteral, ImportAliasValue, TermValue
from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.operations.binary_operator_operation import (
    BinaryOperatorOperation,
)
from sugar_lift_py_tests.operations.method_call_operation import MethodCallOperation
from sugar_lift_py_tests.operations.subscript_operation import SubscriptOperation
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.sugar.floor_terms import floor_to_term

_ENCODER = textwrap.dedent("""
    def encodeBase64(value):
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
        b0 = ord(value[0])
        b1 = ord(value[1])
        b2 = ord(value[2])
        return (
            alphabet[b0 >> 2]
            + alphabet[((b0 & 3) << 4) | (b1 >> 4)]
            + alphabet[((b1 & 15) << 2) | (b2 >> 6)]
            + alphabet[b2 & 63]
        )
    """)


def test_import_sugar_digs_imported_callee_into_its_module_source(
    tmp_path, monkeypatch
):
    (tmp_path / "b64importmod.py").write_text(_ENCODER, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(__import__("sys").modules, "b64importmod", raising=False)

    src = (
        "from b64importmod import encodeBase64\n"
        "def test_c():\n"
        '    assert encodeBase64("xyz") == "eHl6"\n'
    )
    rep = build_literal_call_report(
        source=src, filename="consumer.py", memento_file="consumer.py"
    )
    names = [c.name for c in rep.payload.ir]
    # The dig followed `from b64importmod import encodeBase64` INTO the module's
    # source: the universe contract is keyed to that module, not the consumer file.
    assert names == [
        "b64importmod::encodeBase64::callable",
        "b64importmod.encodeBase64#euf#c:call:b64importmod.encodeBase64(s:'xyz')::assertion",
    ]
    assert rep.payload.ir[0].bridge_source_symbol == "call:b64importmod.encodeBase64"
    assert "str.eq-bv-blocks" in json.dumps(rep.payload.ir[0].post.to_rpc())


def test_import_alias_floor_projects_and_runtime_operations_are_typed_red() -> None:
    alias = ImportAliasValue(name="numpy", bound_name="np")

    assert alias.to_term(owner="test") == ctor(
        "python:import_alias", [str_const("np"), str_const("numpy")]
    )
    assert floor_to_term(ArrayLiteral((alias,)), owner="test") == ctor(
        "array",
        [ctor("python:import_alias", [str_const("np"), str_const("numpy")])],
    )

    operations = (
        alias.call_method_with(
            MethodCallOperation(name="__call__", arguments=(), blame="t.py:1:0"),
            ctx=None,
        ),
        alias.subscript_with(
            SubscriptOperation(index=TermValue(0), blame="t.py:2:0"),
            ctx=None,
        ),
        alias.binary_operator_with(
            BinaryOperatorOperation(operator="+", right=TermValue(1), blame="t.py:3:0"),
            ctx=None,
        ),
    )
    for outcome in operations:
        assert isinstance(outcome, Incomplete)
        assert "import alias runtime boundary" in outcome.reason
        assert "`np -> numpy`" in outcome.reason
