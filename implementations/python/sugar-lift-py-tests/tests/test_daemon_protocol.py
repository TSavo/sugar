# SPDX-License-Identifier: Apache-2.0
#
# Smoke test: protocol conformance of the sugar-lsp-python binary.
#
# Asserts:
#   - The binary (or python3 -m fallback) responds to initialize/parse/shutdown.
#   - parse response has `result.declarations` as a JSON array, not a string.
#   - parse response has `result.callEdges` as a JSON array.
#   - Each declaration in a non-empty result is an object with kind=="contract".
#   - Byte-determinism: two runs on the same input produce identical output.
#
# The binary under test is resolved in order:
#   1. sugar-lsp-python on PATH (installed via pip install -e .)
#   2. The installed user-bin path /Users/tsavo/Library/Python/3.9/bin/sugar-lsp-python
#   3. python3 -m sugar_lift_py_tests.lsp  (module fallback, always available)

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
from typing import List

import pytest


# ---------------------------------------------------------------------------
# Helper: resolve the LSP binary command
# ---------------------------------------------------------------------------

def _lsp_cmd() -> List[str]:
    """Return the command list to invoke the Python LSP plugin."""
    # 1. On-PATH binary (post pip install).
    on_path = shutil.which("sugar-lsp-python")
    if on_path:
        return [on_path]

    # 2. Known user-scheme install location (macOS system Python 3.9).
    user_bin = os.path.expanduser("~/Library/Python/3.9/bin/sugar-lsp-python")
    if os.path.isfile(user_bin):
        return [user_bin]

    # 3. Module fallback -- always works when conftest.py has added src to sys.path.
    return [sys.executable, "-m", "sugar_lift_py_tests.lsp"]


# Fixture source containing a bounded-loop contract (Layer 2 pattern 1).
_FIXTURE_SOURCE = """\
def test_range_positive():
    for i in range(1, 10):
        assert i > 0
"""

_FIXTURE_PATH = "test_fixture.py"


def _run_lsp(ndjson_input: str) -> List[dict]:
    """Spawn the LSP binary, feed ndjson_input, return parsed response lines."""
    cmd = _lsp_cmd()
    src_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "src"))
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = src_dir if not existing else os.pathsep.join([src_dir, existing])
    result = subprocess.run(
        cmd,
        input=ndjson_input,
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    assert result.returncode == 0, (
        f"LSP binary exited {result.returncode}; stderr: {result.stderr!r}"
    )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def _build_session(source: str = _FIXTURE_SOURCE, path: str = _FIXTURE_PATH) -> str:
    """Build NDJSON input for initialize -> parse -> shutdown."""
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "parse",
         "params": {"path": path, "source": source}},
        {"jsonrpc": "2.0", "id": 3, "method": "shutdown"},
    ]
    return "\n".join(json.dumps(m) for m in msgs) + "\n"


def _build_analyze_session(source: str, path: str, uri: str = "file:///project/test_fixture.py") -> str:
    """Build NDJSON input for initialize -> analyzeDocument -> shutdown."""
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "analyzeDocument",
            "params": {
                "kit_id": "python",
                "uri": uri,
                "file": path,
                "text": source,
                "document_version": 42,
                "workspace_root": "/project",
                "accepted_protocol_catalog_cids": [],
                "policy_cids": [],
            },
        },
        {"jsonrpc": "2.0", "id": 3, "method": "shutdown"},
    ]
    return "\n".join(json.dumps(m) for m in msgs) + "\n"


def _build_kit_declaration_session() -> str:
    """Build NDJSON input for initialize -> kit_declaration -> shutdown."""
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "sugar.plugin.kit_declaration"},
        {"jsonrpc": "2.0", "id": 3, "method": "shutdown"},
    ]
    return "\n".join(json.dumps(m) for m in msgs) + "\n"


def _flatten_and_json(formula: dict) -> List[dict]:
    if formula.get("kind") == "and":
        out: List[dict] = []
        for operand in formula.get("operands", []):
            out.extend(_flatten_and_json(operand))
        return out
    return [formula]


def _assert_json_none_guard_formula(
    formula: dict, *, comparison_name: str, guard_name: str
) -> None:
    atoms = [atom for atom in _flatten_and_json(formula) if atom.get("kind") == "atomic"]
    assert any(
        atom.get("name") == comparison_name
        and len(atom.get("args", [])) == 2
        and atom["args"][1].get("kind") == "ctor"
        and atom["args"][1].get("name") == "None"
        for atom in atoms
    )
    guards = [atom for atom in atoms if atom.get("name") == guard_name]
    assert len(guards) == 1
    assert ":" not in guards[0]["name"]
    assert len(guards[0].get("args", [])) == 1


def _repo_root() -> str:
    return os.path.normpath(os.path.join(os.path.dirname(__file__), "../../../.."))


def _python_lift_manifest() -> dict[str, object]:
    manifest = os.path.join(
        _repo_root(), "implementations/python/.sugar/lift/python/manifest.toml"
    )
    values: dict[str, object] = {}
    with open(manifest, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if value.startswith("["):
                values[key] = ast.literal_eval(value)
            elif value.startswith('"'):
                values[key] = ast.literal_eval(value)
    return values


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDaemonProtocol:
    """Protocol conformance tests for the sugar-lsp-python binary."""

    def test_initialize_response(self):
        """Binary responds to initialize with the expected shape."""
        responses = _run_lsp(_build_session())
        init_resp = next(r for r in responses if r.get("id") == 1)
        result = init_resp["result"]
        assert result["name"] == "sugar-lsp-python"
        assert result["protocol_version"] == "sugar-lsp-shared/1"
        assert result["kit_id"] == "python"
        assert "python-source" in result["capabilities"]["source_surfaces"]
        assert "sugar.lsp.implication_failed" in result["capabilities"]["diagnostic_codes"]

    def test_checked_in_project_registers_python_lift_surface(self):
        """The checked-in Python kit config registers the lift-py-tests surface."""
        config = os.path.join(_repo_root(), "implementations/python/.sugar/config.toml")
        with open(config, "r", encoding="utf-8") as f:
            text = f.read()
        assert 'name = "python-lift"' in text
        assert 'kind = "lift"' in text
        assert 'surface = "python"' in text

    def test_checked_in_python_lift_manifest_invokes_module_form(self):
        """The checked-in lift manifest works from a clean source working_dir."""
        manifest = _python_lift_manifest()
        assert manifest["command"] == [
            "python3",
            "-m",
            "sugar_lift_py_tests.lsp",
            "--rpc",
        ]
        assert manifest["working_dir"] == "sugar-lift-py-tests/src"

        completed = subprocess.run(
            manifest["command"],
            cwd=os.path.join(_repo_root(), "implementations/python", manifest["working_dir"]),
            input=_build_kit_declaration_session(),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        assert completed.returncode == 0, completed.stderr
        responses = [
            json.loads(line) for line in completed.stdout.splitlines() if line.strip()
        ]
        declaration = next(response for response in responses if response.get("id") == 2)
        assert declaration["result"]["kit"]["id"] == "python"

    def test_kit_declaration_returns_python_lift_surface(self):
        """Binary serves an honest Python test-lift declaration."""
        responses = _run_lsp(_build_kit_declaration_session())
        declaration_resp = next(r for r in responses if r.get("id") == 2)
        assert "error" not in declaration_resp, declaration_resp
        result = declaration_resp["result"]
        assert result["kit"] == {
            "id": "python",
            "language": "python",
            "version": "0.1.0",
        }
        method_names = {method["name"] for method in result["rpc"]["methods"]}
        assert method_names == {
            "initialize",
            "sugar.plugin.kit_declaration",
            "analyzeDocument",
            "parse",
            "lift",
            "sugar.plugin.lift_implications",
            "shutdown",
        }
        assert result["proofResolution"] == {"strategy": "pip"}
        assert result["effectKinds"] == ["panic-freedom"]
        assert result["effectLeaves"] == []
        assert result["guardPredicates"] == [
            {
                "surface": "python",
                "local": "is_some",
                "concept": "concept:panic-freedom.option.some",
            },
            {
                "surface": "python",
                "local": "is_none",
                "concept": "concept:panic-freedom.option.none",
            },
        ]
        assert result["controlCarriers"] == []
        assert result["residueCategories"] == []
        json.dumps(declaration_resp)

    def test_parse_declarations_is_array(self):
        """parse response: result.declarations is a JSON array, not a string."""
        responses = _run_lsp(_build_session())
        parse_resp = next(r for r in responses if r.get("id") == 2)
        assert "error" not in parse_resp, f"parse returned error: {parse_resp}"
        result = parse_resp["result"]
        assert isinstance(result["declarations"], list), (
            f"declarations should be list, got {type(result['declarations']).__name__}: "
            f"{result['declarations']!r}"
        )

    def test_parse_call_edges_is_array(self):
        """parse response: result.callEdges is a JSON array, not a string."""
        responses = _run_lsp(_build_session())
        parse_resp = next(r for r in responses if r.get("id") == 2)
        result = parse_resp["result"]
        assert isinstance(result["callEdges"], list), (
            f"callEdges should be list, got {type(result['callEdges']).__name__}: "
            f"{result['callEdges']!r}"
        )

    def test_parse_emits_same_language_call_edge_locus(self):
        """Decorated Python functions emit same-kit call edges at call sites."""
        source = """\
from sugar_lift_py_tests.decorators import contract

@contract(pre="x >= 0")
def add(x: int) -> int:
    return x

@contract(post="out >= 0")
def compute(x: int) -> int:
    return add(x)
"""
        responses = _run_lsp(_build_session(source=source, path="fixture.py"))
        parse_resp = next(r for r in responses if r.get("id") == 2)
        assert "error" not in parse_resp, f"parse returned error: {parse_resp}"
        edges = parse_resp["result"]["callEdges"]
        assert any(
            edge.get("targetSymbol") == "python-kit:add"
            and isinstance(edge.get("sourceContractCid"), str)
            and edge["sourceContractCid"].startswith("blake3-512:")
            and edge.get("callSiteLocus") == {
                "column": 11,
                "file": "fixture.py",
                "line": 9,
            }
            for edge in edges
        ), f"expected compute -> python-kit:add call edge, got {edges!r}"

    def test_declarations_contain_contracts(self):
        """With a contract-bearing fixture, each declaration has kind=='contract'."""
        responses = _run_lsp(_build_session())
        parse_resp = next(r for r in responses if r.get("id") == 2)
        decls = parse_resp["result"]["declarations"]
        assert len(decls) >= 1, "Expected at least one declaration from bounded-loop fixture"
        for d in decls:
            assert isinstance(d, dict), f"declaration is not a dict: {d!r}"
            assert d.get("kind") == "contract", (
                f"expected kind='contract', got {d.get('kind')!r}"
            )

    def test_declarations_have_name_field(self):
        """Each declaration is an object with a 'name' field."""
        responses = _run_lsp(_build_session())
        parse_resp = next(r for r in responses if r.get("id") == 2)
        for d in parse_resp["result"]["declarations"]:
            assert "name" in d, f"declaration missing 'name': {d!r}"

    def test_empty_source_returns_empty_arrays(self):
        """Empty source returns declarations=[] and callEdges=[]."""
        responses = _run_lsp(_build_session(source="# no contracts here\n"))
        parse_resp = next(r for r in responses if r.get("id") == 2)
        result = parse_resp["result"]
        assert result["declarations"] == []
        assert result["callEdges"] == []

    def test_byte_determinism(self):
        """Two independent runs on the same input produce identical output."""
        ndjson = _build_session()
        run1 = _run_lsp(ndjson)
        run2 = _run_lsp(ndjson)
        # Compare the parse response (id==2) from both runs.
        parse1 = next(r for r in run1 if r.get("id") == 2)
        parse2 = next(r for r in run2 if r.get("id") == 2)
        assert json.dumps(parse1, sort_keys=True) == json.dumps(parse2, sort_keys=True), (
            "parse response is not byte-deterministic across two runs"
        )

    def test_unknown_language_returns_error(self):
        """Requesting a non-python language returns a JSON-RPC error, not a crash."""
        msgs = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "parse",
             "params": {"path": "f.rs", "source": "fn foo() {}", "language": "rust"}},
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown"},
        ]
        ndjson = "\n".join(json.dumps(m) for m in msgs) + "\n"
        responses = _run_lsp(ndjson)
        parse_resp = next(r for r in responses if r.get("id") == 2)
        assert "error" in parse_resp, "Expected error for unsupported language"
        assert parse_resp["error"]["code"] == -32602

    def test_analyze_document_floor_fixture_emits_shared_callsite_diagnostic(self):
        """analyzeDocument returns shared envelope plus call-site diagnostic."""
        repo_root = _repo_root()
        fixture = os.path.join(repo_root, "tests/lsp/floor-fixture/python.py")
        with open(fixture, "r", encoding="utf-8") as f:
            source = f.read()

        responses = _run_lsp(
            _build_analyze_session(
                source=source,
                path="tests/lsp/floor-fixture/python.py",
                uri="file:///project/tests/lsp/floor-fixture/python.py",
            )
        )
        analyze_resp = next(r for r in responses if r.get("id") == 2)
        assert "error" not in analyze_resp, f"analyzeDocument returned error: {analyze_resp}"
        result = analyze_resp["result"]
        assert result["kind"] == "lsp-document-analysis"
        assert result["schema_version"] == "1"
        assert result["kit_id"] == "python"
        assert result["uri"] == "file:///project/tests/lsp/floor-fixture/python.py"
        assert result["file"] == "tests/lsp/floor-fixture/python.py"
        assert isinstance(result["entries"], list)
        assert isinstance(result["statuses"], list)
        assert result["project"] is None
        assert result["document_cid"].startswith("blake3-512:")
        assert len(result["document_cid"]) == len("blake3-512:") + 128

        diagnostics = result["diagnostics"]
        assert len(diagnostics) == 1
        diagnostic = diagnostics[0]
        assert diagnostic["code"] == "sugar.lsp.implication_failed"
        assert diagnostic["severity"] == "error"
        assert diagnostic["producer"] == "forward-propagation"
        assert diagnostic["kit_id"] == "python"
        assert diagnostic["range"]["start_line"] == 17
        assert diagnostic["range"]["start_col"] == 13
        assert diagnostic["data"]["callee"] == "checkPositive"

    def test_parse_plain_unittest_testcase_assertions_as_normalized_contract(self):
        """Plain unittest.TestCase assertions lift through RPC as one contract."""
        source = """\
import unittest

class ParserTest(unittest.TestCase):
    def test_native_assertions(self):
        self.assertEqual(parse_int("42"), 42)
        self.assertNotEqual(parse_int("0"), 1)
        self.assertTrue(parse_int("5") > 0)
        self.assertIsNone(maybe_none())
        self.assertIsNotNone(maybe_value())
"""
        responses = _run_lsp(_build_session(source=source, path="test_parser.py"))
        parse_resp = next(r for r in responses if r.get("id") == 2)
        assert "error" not in parse_resp, f"parse returned error: {parse_resp}"
        decls = parse_resp["result"]["declarations"]
        assert len(decls) == 1
        decl = decls[0]
        assert decl["kind"] == "contract"
        # Class methods are qualified: "ClassName::method_name".
        assert decl["name"] == "ParserTest::test_native_assertions"
        inv = decl["inv"]
        assert inv["kind"] == "and"
        flat_atoms = [
            op for op in _flatten_and_json(inv) if op.get("kind") == "atomic"
        ]
        assert [op["name"] for op in flat_atoms] == [
            "=",
            "≠",
            ">",
            "=",
            "is_none",
            "≠",
            "is_some",
        ]
        none_atoms = [
            op for op in flat_atoms
            if op["name"] in {"=", "≠"}
            and len(op["args"]) == 2
            and op["args"][1].get("kind") == "ctor"
            and op["args"][1].get("name") == "None"
        ]
        assert len(none_atoms) == 2
        _assert_json_none_guard_formula(inv, comparison_name="=", guard_name="is_none")
        _assert_json_none_guard_formula(inv, comparison_name="≠", guard_name="is_some")

    def test_parse_unsupported_unittest_assertion_reports_lift_gap_warning(self):
        """Unsupported unittest forms report a gap and do not mint a contract."""
        source = """\
import unittest

class RegexTest(unittest.TestCase):
    def test_regex(self):
        self.assertRegex("abc", "a.*")
"""
        responses = _run_lsp(_build_session(source=source, path="test_regex.py"))
        parse_resp = next(r for r in responses if r.get("id") == 2)
        assert "error" not in parse_resp, f"parse returned error: {parse_resp}"
        result = parse_resp["result"]
        assert result["declarations"] == []
        assert any(
            "assertRegex" in warning["reason"] and "lift-gap" in warning["reason"]
            for warning in result["warnings"]
        )
