from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from sugar_lift_py_tests.canonicalizer import encode_jcs
from sugar_lift_py_tests.claim import SugarCatalog, SugarClaim, SugarRole
from sugar_lift_py_tests.factory import FactoryGap, build_next, build_node
from sugar_lift_py_tests.floor import ArrayLiteral, Bv32Value, TermValue
from sugar_lift_py_tests.ir import term_to_value
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar_body import SugarBody
from sugar_lift_py_tests.sugar.array_literal_sugar import (
    ARRAY_LITERAL_CLAIM,
    ArrayLiteralSugar,
)
from sugar_lift_py_tests.sugar.bitwise_op_sugar import BITWISE_OP_CLAIM, BitwiseOpSugar
from sugar_lift_py_tests.sugar.primitive_literal_sugar import PrimitiveLiteralSugar

ROOT = Path(__file__).resolve().parents[4]
PYTHON_KIT = ROOT / "implementations/python"
PY_TESTS = PYTHON_KIT / "sugar-lift-py-tests"


def test_batch_lift_entrypoints_use_lift_rpc_not_lsp() -> None:
    manifest = (PYTHON_KIT / ".sugar/lift/python/manifest.toml").read_text(
        encoding="utf-8"
    )
    pyproject = (PY_TESTS / "pyproject.toml").read_text(encoding="utf-8")

    assert (
        'command = ["python3", "-m", "sugar_lift_py_tests.lift_rpc", "--rpc"]'
        in manifest
    )
    assert 'sugar-lift-python = "sugar_lift_py_tests.lift_rpc:main"' in pyproject
    assert 'sugar-lift-python = "sugar_lift_py_tests.lsp:main"' not in pyproject


def test_lift_rpc_reports_factory_gap_without_old_lsp_entry(tmp_path) -> None:
    source = tmp_path / "base64.py"
    source.write_text("def encode_len(data):\n    global x\n", encoding="utf-8")
    env = {
        **os.environ,
        "PYTHONPATH": str(PY_TESTS / "src"),
    }
    request = "\n".join(
        json.dumps(message)
        for message in [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "lift",
                "params": {"workspace_root": str(tmp_path), "source_paths": ["."]},
            },
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": {}},
        ]
    )

    completed = subprocess.run(
        [sys.executable, "-m", "sugar_lift_py_tests.lift_rpc", "--rpc"],
        input=request + "\n",
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert completed.returncode == 0, completed.stderr
    responses = [
        json.loads(line) for line in completed.stdout.splitlines() if line.strip()
    ]
    lift_response = next(response for response in responses if response.get("id") == 2)
    assert lift_response["error"]["message"].startswith("write more Sugar for this AST")
    assert lift_response["error"]["data"]["info"] == {
        "owner": "python.factory",
        "blame": str(source) + ":2:4",
        "observed": "Global",
        "requested": "statement",
        "fix": "create sugar_lift_py_tests.sugar.global.global_sugar",
        "gap_kind": "Sugar",
        "gap_locus": "AST",
    }


def test_lift_rpc_audit_only_argv_collects_all_factory_gaps(tmp_path) -> None:
    first = tmp_path / "a.py"
    second = tmp_path / "b.py"
    empty_package_marker = tmp_path / "empty" / "__init__.py"
    first.write_text("def a():\n    global x\n", encoding="utf-8")
    second.write_text("def b():\n    global y\n", encoding="utf-8")
    empty_package_marker.parent.mkdir()
    empty_package_marker.write_text("", encoding="utf-8")
    env = {
        **os.environ,
        "PYTHONPATH": str(PY_TESTS / "src"),
    }
    request = "\n".join(
        json.dumps(message)
        for message in [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "lift",
                "params": {"workspace_root": str(tmp_path), "source_paths": ["."]},
            },
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": {}},
        ]
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "sugar_lift_py_tests.lift_rpc",
            "--rpc",
            "--audit-only",
        ],
        input=request + "\n",
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert completed.returncode == 0, completed.stderr
    responses = [
        json.loads(line) for line in completed.stdout.splitlines() if line.strip()
    ]
    lift_response = next(response for response in responses if response.get("id") == 2)
    error = lift_response["error"]
    assert error["message"] == "audit-only construction gaps"
    gaps = error["data"]["auditOnlyGaps"]
    assert [gap["label"] for gap in gaps] == [str(first), str(second)]
    assert [gap["gap"]["observed"] for gap in gaps] == ["Global", "Global"]
    assert all(
        gap["message"].startswith("write more Sugar for this AST") for gap in gaps
    )


def test_lift_rpc_normal_mode_ignores_empty_package_markers(tmp_path) -> None:
    empty_package_marker = tmp_path / "pkg" / "__init__.py"
    ordinary = tmp_path / "pkg" / "ordinary.py"
    empty_package_marker.parent.mkdir()
    empty_package_marker.write_text("", encoding="utf-8")
    ordinary.write_text("def ordinary():\n    return 1\n", encoding="utf-8")
    env = {
        **os.environ,
        "PYTHONPATH": str(PY_TESTS / "src"),
    }
    request = "\n".join(
        json.dumps(message)
        for message in [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "lift",
                "params": {"workspace_root": str(tmp_path), "source_paths": ["."]},
            },
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": {}},
        ]
    )

    completed = subprocess.run(
        [sys.executable, "-m", "sugar_lift_py_tests.lift_rpc", "--rpc"],
        input=request + "\n",
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert completed.returncode == 0, completed.stderr
    responses = [
        json.loads(line) for line in completed.stdout.splitlines() if line.strip()
    ]
    lift_response = next(response for response in responses if response.get("id") == 2)
    assert "error" not in lift_response
    assert all(value == 0 for value in lift_response["result"]["sourceLedger"].values())


def test_factory_without_sugar_panics_on_last_popped_source_fragment() -> None:
    source = "def encode_len(data):\n    global x\n"

    with pytest.raises(FactoryGap) as raised:
        build_next(source, filename="base64.py", role=SugarRole.TERM)

    gap = raised.value
    assert str(gap).startswith("write more Sugar for this AST")
    assert gap.info == {
        "owner": "python.factory",
        "blame": "base64.py:2:4",
        "observed": "Global",
        "requested": "statement",
        "fix": "create sugar_lift_py_tests.sugar.global.global_sugar",
        "gap_kind": "Sugar",
        "gap_locus": "AST",
    }
    assert gap.audit_row.to_json() == {
        "kind": "factory-audit-row",
        "role": "statement",
        "status": "sugar-gap",
        "observed": "Global",
        "blame": "base64.py:2:4",
        "selected": None,
        "candidates": [],
        "message": str(gap),
    }


def test_factory_matches_registered_sugar_for_last_popped_source_fragment() -> None:
    source = "def encode_len(data):\n    return len(data)\n"

    @dataclass(frozen=True)
    class NameSugar:
        identifier: str

    def owns_name(site) -> bool:
        return isinstance(site.node, ast.Name)

    def build_name(site, _ctx) -> NameSugar:
        return NameSugar(site.node.id)

    catalog = SugarCatalog(
        [
            SugarClaim(
                name="python.name",
                role=SugarRole.TERM,
                owns=owns_name,
                build=build_name,
            )
        ]
    )

    result = build_next(
        source, filename="base64.py", role=SugarRole.TERM, catalog=catalog
    )

    assert result.sugar == NameSugar("data")
    assert result.audit_row.to_json() == {
        "kind": "factory-audit-row",
        "role": "term",
        "status": "selected",
        "observed": "Name",
        "blame": "base64.py:2:15",
        "selected": "python.name",
        "candidates": ["python.name"],
        "message": "selected Sugar `python.name` for role term at `base64.py:2:15`",
    }


def test_factory_panics_when_multiple_claims_own_the_same_ast_without_ordering() -> (
    None
):
    node = ast.parse("1", mode="eval").body

    @dataclass(frozen=True)
    class OwnedSugar:
        owner: str

    def owns_literal(site) -> bool:
        return isinstance(site.node, ast.Constant)

    catalog = SugarCatalog(
        [
            SugarClaim(
                name="AlphaLiteralSugar",
                role=SugarRole.TERM,
                owns=owns_literal,
                build=lambda _site, _ctx: OwnedSugar("alpha"),
            ),
            SugarClaim(
                name="BetaLiteralSugar",
                role=SugarRole.TERM,
                owns=owns_literal,
                build=lambda _site, _ctx: OwnedSugar("beta"),
            ),
        ]
    )

    with pytest.raises(FactoryGap) as raised:
        build_node(node, filename="ambiguous.py", role=SugarRole.TERM, catalog=catalog)

    assert str(raised.value).startswith("write more Sugar ordering for this AST")
    assert raised.value.info == {
        "owner": "python.factory",
        "blame": "ambiguous.py:1:0",
        "observed": "PrimitiveLiteral candidates=[AlphaLiteralSugar, BetaLiteralSugar]",
        "requested": "term",
        "fix": "declare comes_before or split the sugar role",
        "gap_kind": "Sugar ordering",
        "gap_locus": "AST",
    }
    assert raised.value.audit_row.to_json() == {
        "kind": "factory-audit-row",
        "role": "term",
        "status": "sugar-ambiguous",
        "observed": "PrimitiveLiteral",
        "blame": "ambiguous.py:1:0",
        "selected": None,
        "candidates": ["AlphaLiteralSugar", "BetaLiteralSugar"],
        "message": str(raised.value),
    }


def test_factory_uses_comes_before_to_resolve_multiple_claims() -> None:
    node = ast.parse("1", mode="eval").body

    @dataclass(frozen=True)
    class OwnedSugar:
        owner: str

    def owns_literal(site) -> bool:
        return isinstance(site.node, ast.Constant)

    alpha = SugarClaim(
        name="AlphaLiteralSugar",
        role=SugarRole.TERM,
        owns=owns_literal,
        build=lambda _site, _ctx: OwnedSugar("alpha"),
        comes_before=("BetaLiteralSugar",),
    )
    beta = SugarClaim(
        name="BetaLiteralSugar",
        role=SugarRole.TERM,
        owns=owns_literal,
        build=lambda _site, _ctx: OwnedSugar("beta"),
    )
    catalog = SugarCatalog([beta, alpha])

    result = build_node(
        node,
        filename="ordered.py",
        role=SugarRole.TERM,
        catalog=catalog,
    )

    assert result.sugar == OwnedSugar("alpha")
    assert result.audit_row.to_json() == {
        "kind": "factory-audit-row",
        "role": "term",
        "status": "selected",
        "observed": "PrimitiveLiteral",
        "blame": "ordered.py:1:0",
        "selected": "AlphaLiteralSugar",
        "candidates": ["BetaLiteralSugar", "AlphaLiteralSugar"],
        "message": "selected Sugar `AlphaLiteralSugar` for role term at `ordered.py:1:0`",
    }


def test_array_literal_factory_hits_missing_primitive_literal_leaf_first() -> None:
    node = ast.parse("[1, 2, 3]", mode="eval").body

    with pytest.raises(FactoryGap) as raised:
        build_node(
            node,
            filename="array.py",
            role=SugarRole.TERM,
            catalog=SugarCatalog([ARRAY_LITERAL_CLAIM]),
        )

    assert raised.value.info == {
        "owner": "python.factory",
        "blame": "array.py:1:1",
        "observed": "PrimitiveLiteral",
        "requested": "term",
        "fix": "create sugar_lift_py_tests.sugar.primitive_literal_sugar",
        "gap_kind": "Sugar",
        "gap_locus": "AST",
    }


def test_array_literal_factory_requires_primitive_literal_children() -> None:
    node = ast.parse("[1, 2, 3]", mode="eval").body

    result = build_node(node, filename="array.py", role=SugarRole.TERM)

    assert isinstance(result.sugar, ArrayLiteralSugar)
    assert all(isinstance(child, SugarBody) for child in result.sugar.elements)
    assert all(
        isinstance(child.sugar, PrimitiveLiteralSugar)
        for child in result.sugar.elements
    )
    assert complete_value(
        result.sugar.desugar(), owner="array literal"
    ) == ArrayLiteral((TermValue(1), TermValue(2), TermValue(3)))
    with pytest.raises(
        TypeError, match="ArrayLiteralSugar elements must be factory-built bodies"
    ):
        ArrayLiteralSugar(elements=(node,))  # type: ignore[arg-type]


def test_bitwise_op_factory_hits_missing_primitive_literal_leaf_first() -> None:
    node = ast.parse("1 & 3", mode="eval").body

    with pytest.raises(FactoryGap) as raised:
        build_node(
            node,
            filename="bitwise.py",
            role=SugarRole.TERM,
            catalog=SugarCatalog([BITWISE_OP_CLAIM]),
        )

    assert raised.value.info == {
        "owner": "python.factory",
        "blame": "bitwise.py:1:0",
        "observed": "PrimitiveLiteral",
        "requested": "term",
        "fix": "create sugar_lift_py_tests.sugar.primitive_literal_sugar",
        "gap_kind": "Sugar",
        "gap_locus": "AST",
    }


def test_bitwise_op_factory_requires_factory_built_operands() -> None:
    and_node = ast.parse("1 & 3", mode="eval").body
    shift_node = ast.parse("1 << 4", mode="eval").body

    and_result = build_node(and_node, filename="bitwise.py", role=SugarRole.TERM)
    shift_result = build_node(shift_node, filename="bitwise.py", role=SugarRole.TERM)

    assert isinstance(and_result.sugar, BitwiseOpSugar)
    assert isinstance(shift_result.sugar, BitwiseOpSugar)
    assert isinstance(and_result.sugar.left, SugarBody)
    assert isinstance(and_result.sugar.right, SugarBody)
    assert isinstance(and_result.sugar.left.sugar, PrimitiveLiteralSugar)
    assert isinstance(and_result.sugar.right.sugar, PrimitiveLiteralSugar)
    and_value = complete_value(and_result.sugar.desugar(), owner="bitwise and")
    shift_value = complete_value(shift_result.sugar.desugar(), owner="bitwise shift")
    assert isinstance(and_value, Bv32Value)
    assert isinstance(shift_value, Bv32Value)
    assert json.loads(encode_jcs(term_to_value(and_value.term))) == {
        "args": [
            {
                "kind": "const",
                "sort": {"kind": "primitive", "name": "Int"},
                "value": 1,
            },
            {
                "kind": "const",
                "sort": {"kind": "primitive", "name": "Int"},
                "value": 3,
            },
        ],
        "kind": "ctor",
        "name": "bv32.and",
    }
    assert json.loads(encode_jcs(term_to_value(shift_value.term))) == {
        "args": [
            {
                "kind": "const",
                "sort": {"kind": "primitive", "name": "Int"},
                "value": 1,
            },
            {
                "kind": "const",
                "sort": {"kind": "primitive", "name": "Int"},
                "value": 4,
            },
        ],
        "kind": "ctor",
        "name": "bv32.shl",
    }
    with pytest.raises(
        TypeError, match="BitwiseOpSugar operands must be factory-built bodies"
    ):
        BitwiseOpSugar(
            operator="&",
            left=and_node.left,  # type: ignore[arg-type]
            right=and_result.sugar.right,
        )
