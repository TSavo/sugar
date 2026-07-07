from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
PKG_SRC = ROOT / "implementations/python/sugar-lift-python-source/src"
PY_TESTS_SRC = ROOT / "implementations/python/sugar-lift-py-tests/src"
if str(PY_TESTS_SRC) not in sys.path:
    sys.path.insert(0, str(PY_TESTS_SRC))
if str(PKG_SRC) not in sys.path:
    sys.path.insert(0, str(PKG_SRC))

from sugar_lift_python_source.bind_lifter import (
    _operand_slot,
    _public_reexport_map,
    lift_source,
)
from sugar_lift_python_source.bind_rpc import dispatch, initialize_result
from sugar_lift_py_tests.canonicalizer import blake3_512_of
from sugar_lift_py_tests.op_cid import local_op_cid
from sugar_lift_python_source.canonical import cid_of_json

KIT_DECLARATION_RPC_METHOD = "sugar.plugin.kit_declaration"


def _parse_top_level_toml(path: Path) -> dict[str, object]:
    values: dict[str, object] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("[") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        raw_value = value.strip()
        if raw_value == "true":
            values[key.strip()] = True
        elif raw_value == "false":
            values[key.strip()] = False
        else:
            values[key.strip()] = ast.literal_eval(raw_value)
    return values


def _plugin_entries(path: Path) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line == "[[plugins]]":
            current = {}
            entries.append(current)
            continue
        if current is not None and "=" in line:
            key, value = line.split("=", 1)
            current[key.strip()] = ast.literal_eval(value.strip())
    return entries


def _build_kit_declaration_session() -> str:
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": KIT_DECLARATION_RPC_METHOD},
        {"jsonrpc": "2.0", "id": 3, "method": "shutdown"},
    ]
    return "\n".join(json.dumps(message) for message in messages) + "\n"


def _python_bind_manifest() -> dict[str, object]:
    manifest = ROOT / "implementations/python/.sugar/lift/python-bind/manifest.toml"
    assert manifest.exists(), f"missing checked-in python-bind manifest: {manifest}"
    return _parse_top_level_toml(manifest)


def _cid(ch: str) -> str:
    return "blake3-512:" + ch * 128


def _template_cid_of_json(value: object) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=False).encode("utf-8")
    return blake3_512_of(encoded)


def _formula_gte_x_zero() -> dict:
    return {
        "args": [
            {"kind": "var", "name": "x"},
            {
                "kind": "const",
                "sort": {"kind": "primitive", "name": "Int"},
                "value": 0,
            },
        ],
        "kind": "atomic",
        "name": "≥",
    }


def _formula_out_eq_x() -> dict:
    return {
        "args": [{"kind": "var", "name": "out"}, {"kind": "var", "name": "x"}],
        "kind": "atomic",
        "name": "=",
    }


def _contract_comment_payload(
    role: str, formula: dict, fol_text: str
) -> tuple[dict, str]:
    payload = {
        "artifact_kind": "sugar-contract-comment-sugar",
        "concept_site_cid": _cid("1"),
        "contract_cid": _cid("2"),
        "emitted_by": {
            "kit_cid": _cid("3"),
            "kit_kind": "realize",
            "target_language": "python",
        },
        "fol_text": fol_text,
        "ir_formula_jcs": formula,
        "ir_formula_jcs_cid": cid_of_json(formula),
        "local_contract_cid": _cid("2"),
        "loss_record_cid": _cid("4"),
        "policy_cid": _cid("5"),
        "role": role,
        "schema_version": "1",
        "sugar_dict_cid": _cid("6"),
    }
    return payload, cid_of_json(payload)


def _comment_lines(payload: dict, payload_cid: str) -> str:
    return (
        "# sugar-contract: "
        + json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        + "\n"
        + f"# sugar-contract-payload-cid: {payload_cid}\n"
    )


def _local_op_cid(name: str) -> str:
    return local_op_cid(name)


def _walk_objects(value: object) -> list[dict]:
    found: list[dict] = []
    if isinstance(value, dict):
        found.append(value)
        for child in value.values():
            found.extend(_walk_objects(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_objects(child))
    return found


def _operator_atoms(term_shape: dict) -> list[dict]:
    return [node for node in _walk_objects(term_shape) if "op_cid" in node]


def _operator_cids(term_shape: dict) -> list[str]:
    return [str(atom["op_cid"]) for atom in _operator_atoms(term_shape)]


def _concept_comment_surfaces(term_shape: dict) -> list[str]:
    surfaces: list[str] = []
    comment_cid = _local_op_cid("concept:comment")
    for atom in _operator_atoms(term_shape):
        if atom.get("op_cid") != comment_cid:
            continue
        args = atom.get("args", [])
        if not isinstance(args, list) or not args:
            continue
        surface = args[0].get("value") if isinstance(args[0], dict) else None
        if isinstance(surface, str):
            surfaces.append(surface)
    return surfaces


def _gamma_shape(operator: str, args: list[dict] | None = None) -> dict:
    return {
        "args": args or [],
        "op_cid": _local_op_cid(operator),
    }


def _assert_absent_keys(value: object, forbidden: set[str]) -> None:
    if isinstance(value, dict):
        assert forbidden.isdisjoint(value.keys())
        for child in value.values():
            _assert_absent_keys(child, forbidden)
    elif isinstance(value, list):
        for child in value:
            _assert_absent_keys(child, forbidden)


def test_library_bindings_layer_lifts_requests_shim_from_real_python_source() -> None:
    fixture = (
        Path(__file__).parent / "fixtures/library_bindings/requests_fetch_status.py"
    )
    source = fixture.read_text(encoding="utf-8")

    result = lift_source(source, "src/shims/requests.py", layer="library-bindings")

    assert result.diagnostics == []
    assert len(result.ir) == 1
    entry = result.ir[0]
    assert entry["kind"] == "library-sugar-binding-entry"
    assert entry["op_cid"] == _local_op_cid("concept:http-request")
    assert entry["target_language"] == "python"
    assert entry["target_library_tag"] == "requests"
    assert entry["source_function_name"] == "fetch_status"
    assert entry["param_names"] == ["url"]
    assert entry["param_types"] == ["str"]
    assert entry["return_type"] == "int"
    assert "emission_template" not in entry
    assert entry["term_shape_cid"] == cid_of_json(entry["term_shape"])
    assert entry["signature_shape_cid"] == cid_of_json(
        {
            "param_names": ["url"],
            "param_types": ["str"],
            "return_type": "int",
        }
    )
    body_source = entry["body_source"]
    assert body_source["file"] == "src/shims/requests.py"
    assert body_source["span"] == {
        "start_line": 5,
        "start_col": 0,
        "end_line": 8,
        "end_col": 31,
    }
    # the SourceMemento PINS the body + template by cid; no inline copy in the proof.
    assert "body_text" not in body_source and "ast_template" not in body_source
    assert body_source["source_cid"].startswith("blake3-512:")
    assert body_source["template_cid"].startswith("blake3-512:")
    assert body_source["param_names"] == ["url"]


# -----------------------------------------------------------------
# #1357 / #1355: family + library_version axes on @sugar.bind
# decorators. Parallel to walk_rpc (rust) + typescript-source tests.
# Both fields are optional; absent ↔ absent in emitted JSON.
# -----------------------------------------------------------------


def test_library_bindings_lifts_family_and_library_version_when_present() -> None:
    source = (
        "from sugar import sugar\n"
        "\n"
        "@sugar.bind(\n"
        '    concept="concept:sql-query",\n'
        '    library="sqlite3",\n'
        '    family="concept:family:sql",\n'
        '    version="python-3",\n'
        ")\n"
        "def query(conn, sql):\n"
        "    return conn.execute(sql).fetchall()\n"
    )
    result = lift_source(source, "src/shims/sqlite.py", layer="library-bindings")
    assert result.diagnostics == []
    assert len(result.ir) == 1
    entry = result.ir[0]
    assert entry["kind"] == "library-sugar-binding-entry"
    assert entry["family"] == "concept:family:sql"
    assert entry["library_version"] == "python-3"


def test_library_bindings_omits_family_and_library_version_when_absent() -> None:
    # Back-compat: existing shims without family/version still lift; the
    # new fields are simply absent (NOT empty strings).
    source = (
        "from sugar import sugar\n"
        "\n"
        '@sugar.bind(concept="concept:http-request", library="requests")\n'
        "def fetch_status(url):\n"
        "    import requests\n"
        "    return requests.get(url).status_code\n"
    )
    result = lift_source(source, "src/shims/requests.py", layer="library-bindings")
    assert result.diagnostics == []
    entry = result.ir[0]
    assert "family" not in entry
    assert "library_version" not in entry


def test_library_bindings_rpc_passes_requested_layer(tmp_path: Path) -> None:
    (tmp_path / "shim.py").write_text(
        "from sugar import sugar\n"
        "import requests\n"
        "\n"
        '@sugar.bind(concept="concept:http-request", library="requests")\n'
        "def fetch_status(url: str) -> int:\n"
        "    response = requests.get(url)\n"
        "    return response.status_code\n",
        encoding="utf-8",
    )
    request = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "lift",
        "params": {
            "workspace_root": str(tmp_path),
            "source_paths": ["shim.py"],
            "options": {"layer": "library-bindings"},
        },
    }

    response = dispatch(request)

    assert response["id"] == 7
    assert response["result"]["kind"] == "ir-document"
    assert response["result"]["ir"][0]["kind"] == "library-sugar-binding-entry"


def test_bind_lift_erases_signature_types_from_bind_ir_entries() -> None:
    source = (
        "def add(left: int, right: int) -> int:\n"
        "    return left + right\n"
        "\n"
        "def generated(value):\n"
        "    return value\n"
    )

    result = lift_source(source, "pkg/foo.py")

    assert result.diagnostics == []
    assert len(result.ir) == 2
    add, generated = result.ir
    assert add["param_names"] == ["left", "right"]
    assert "param_types" not in add
    assert "return_type" not in add
    assert "param_types" not in generated
    assert "return_type" not in generated


def test_bind_lift_emits_operand_binding_sidecar_with_integer_positions() -> None:
    source = "def nested(a, b, c):\n" "    return (a + b) * c\n"

    result = lift_source(source, "pkg/math.py")

    assert result.diagnostics == []
    assert len(result.ir) == 1
    entry = result.ir[0]
    assert entry["source_function_name"] == "nested"
    assert entry["operand_bindings"] == [
        {"position": [0, 0], "symbol": "a"},
        {"position": [0, 1], "symbol": "b"},
        {"position": [1], "symbol": "c"},
    ]
    assert all(
        isinstance(binding["position"], list)
        and all(isinstance(part, int) for part in binding["position"])
        for binding in entry["operand_bindings"]
    )
    assert "fn_name" not in entry


def test_bind_lift_source_emits_language_neutral_entries() -> None:
    source = (
        "# concept: identity\n"
        "# @requires: x >= 0\n"
        "# @ensures: result >= 0\n"
        "def wrap_identity(x: int) -> int:\n"
        "    return x\n"
        "\n"
        "class Cell:\n"
        "    # unrelated comment\n"
        "    # concept: bool-cell\n"
        "    @staticmethod\n"
        "    def toggle(flag: bool) -> bool:\n"
        "        return not flag\n"
        "\n"
        "# concept: option\n"
        "def maybe_first(items: list) -> int:\n"
        "    first = 0\n"
        "    if len(items) == 0:\n"
        "        return -1\n"
        "    else:\n"
        "        return items[0]\n"
    )

    result = lift_source(source, "pkg/foo.py")

    assert result.diagnostics == []
    assert len(result.ir) == 3
    _assert_absent_keys(
        result.ir,
        {"attr_pre", "attr_post", "concept_annotation", "fn_name"},
    )
    assert result.ir[0]["param_names"] == ["x"]
    assert "param_types" not in result.ir[0]
    assert "return_type" not in result.ir[0]
    assert result.ir[0]["term_shape"] == {}
    assert result.ir[1]["term_shape"] == _gamma_shape("concept:not", [{}])
    for entry in result.ir:
        assert entry["kind"] == "bind-lift-entry"
        assert entry["term_shape_cid"] == cid_of_json(entry["term_shape"])
        _assert_absent_keys(
            entry,
            {"file", "fn_line", "line", "column", "col"},
        )
        _assert_absent_keys(entry["term_shape"], {"op", "kind"})
    assert "python:" not in json.dumps(result.ir, sort_keys=True)


def test_bind_lift_contract_surfaces_do_not_emit_envelope_hash_fields() -> None:
    sources = [
        ("# @requires: x > 0\n" "def add(x, y):\n" "    return x + y\n"),
        (
            "from sugar_lift_py_tests.decorators import contract\n"
            '@contract(pre="x > 0")\n'
            "def add(x, y):\n"
            "    return x + y\n"
        ),
    ]
    forbidden = {"attr_pre", "attr_post", "concept_annotation", "fn_name"}

    for source in sources:
        result = lift_source(source, "pkg/add.py")

        assert result.diagnostics == []
        assert len(result.ir) == 1
        assert forbidden.isdisjoint(result.ir[0])
        _assert_absent_keys(result.ir[0], forbidden)


def test_bind_lift_emits_gamma_shape_for_add_return() -> None:
    result = lift_source("def add(x, y):\n    return x + y\n", "pkg/add.py")

    assert result.diagnostics == []
    assert result.ir[0]["term_shape"] == _gamma_shape("concept:add", [{}, {}])


def test_bind_lift_discriminates_sub_gamma_shape() -> None:
    add = lift_source("def f(x, y):\n    return x + y\n", "pkg/add.py").ir[0]
    sub = lift_source("def f(x, y):\n    return x - y\n", "pkg/sub.py").ir[0]

    assert add["term_shape"] == _gamma_shape("concept:add", [{}, {}])
    assert sub["term_shape"] == _gamma_shape("concept:sub", [{}, {}])
    assert add["term_shape_cid"] != sub["term_shape_cid"]


def test_bind_lift_preserves_nested_gamma_composition() -> None:
    result = lift_source(
        "def f(x, y, z):\n    return x + y * z\n",
        "pkg/nested.py",
    )

    assert result.diagnostics == []
    assert result.ir[0]["term_shape"] == _gamma_shape(
        "concept:add",
        [{}, _gamma_shape("concept:mul", [{}, {}])],
    )


def test_bind_lift_emits_gamma_shape_for_statement_concepts() -> None:
    cases = [
        (
            "def f():\n" "    while True:\n" "        pass\n",
            _gamma_shape("concept:while", [{}, _gamma_shape("concept:skip")]),
        ),
        (
            "def f(items):\n" "    for item in items:\n" "        pass\n",
            _gamma_shape("concept:for", [_gamma_shape("concept:skip")]),
        ),
        (
            "def f():\n" "    while True:\n" "        break\n",
            _gamma_shape("concept:while", [{}, _gamma_shape("concept:break")]),
        ),
        (
            "def f():\n" "    while True:\n" "        continue\n",
            _gamma_shape("concept:while", [{}, _gamma_shape("concept:continue")]),
        ),
        (
            "def f(x, y):\n" "    x = y\n",
            _gamma_shape("concept:assign", [{}, {}]),
        ),
        (
            "def f(g, x):\n" "    g(x)\n",
            _gamma_shape("concept:call", [{}, {}]),
        ),
        (
            "def f(g, x, y):\n" "    x = y\n" "    g(x)\n",
            _gamma_shape(
                "concept:seq",
                [
                    _gamma_shape("concept:assign", [{}, {}]),
                    _gamma_shape("concept:call", [{}, {}]),
                ],
            ),
        ),
    ]

    for source, expected in cases:
        result = lift_source(source, "pkg/statements.py")

        assert result.diagnostics == []
        assert result.ir[0]["term_shape"] == expected


def test_bind_lift_discriminates_while_and_for_statement_concepts() -> None:
    while_entry = lift_source(
        "def f(items):\n" "    while True:\n" "        pass\n",
        "pkg/while.py",
    ).ir[0]
    for_entry = lift_source(
        "def f(items):\n" "    for item in items:\n" "        pass\n",
        "pkg/for.py",
    ).ir[0]

    assert while_entry["term_shape"] == _gamma_shape(
        "concept:while",
        [{}, _gamma_shape("concept:skip")],
    )
    assert for_entry["term_shape"] == _gamma_shape(
        "concept:for",
        [_gamma_shape("concept:skip")],
    )
    assert while_entry["term_shape_cid"] != for_entry["term_shape_cid"]


def test_bind_lift_preserves_nested_statement_gamma_composition() -> None:
    result = lift_source(
        "def f(x):\n"
        "    if x > 0:\n"
        "        while x > 0:\n"
        "            x = x - 1\n"
        "    return x\n",
        "pkg/nested_statements.py",
    )

    assert result.diagnostics == []
    assert result.ir[0]["term_shape"] == _gamma_shape(
        "concept:conditional",
        [
            _gamma_shape("concept:gt", [{}, {}]),
            _gamma_shape(
                "concept:while",
                [
                    _gamma_shape("concept:gt", [{}, {}]),
                    _gamma_shape(
                        "concept:assign",
                        [{}, _gamma_shape("concept:sub", [{}, {}])],
                    ),
                ],
            ),
            {},
        ],
    )


def test_bind_lift_strips_source_location_keys_from_bind_payload() -> None:
    result = lift_source("def add(x, y):\n    return x + y\n", "/tmp/work/pkg/add.py")

    assert result.diagnostics == []
    _assert_absent_keys(result.ir, {"file", "fn_line", "line", "column", "col"})


def test_bind_lift_preserves_operator_concept_cid_atoms() -> None:
    source = (
        "def add(x, y):\n"
        "    return x + y\n"
        "\n"
        "def sub(x, y):\n"
        "    return x - y\n"
        "\n"
        "def mul(x, y):\n"
        "    return x * y\n"
        "\n"
        "def div(x, y):\n"
        "    return x / y\n"
        "\n"
        "def eq(x, y):\n"
        "    return x == y\n"
        "\n"
        "def ne(x, y):\n"
        "    return x != y\n"
        "\n"
        "def lt(x, y):\n"
        "    return x < y\n"
        "\n"
        "def le(x, y):\n"
        "    return x <= y\n"
        "\n"
        "def gt(x, y):\n"
        "    return x > y\n"
        "\n"
        "def ge(x, y):\n"
        "    return x >= y\n"
        "\n"
        "def logical_not(x):\n"
        "    return not x\n"
    )

    result = lift_source(source, "pkg/operators.py")

    assert result.diagnostics == []
    expected = {
        "add": ("concept:add", _local_op_cid("concept:add")),
        "sub": ("concept:sub", _local_op_cid("concept:sub")),
        "mul": ("concept:mul", _local_op_cid("concept:mul")),
        "div": ("concept:div", _local_op_cid("concept:div")),
        "eq": ("concept:eq", _local_op_cid("concept:eq")),
        "ne": ("concept:ne", _local_op_cid("concept:ne")),
        "lt": ("concept:lt", _local_op_cid("concept:lt")),
        "le": ("concept:le", _local_op_cid("concept:le")),
        "gt": ("concept:gt", _local_op_cid("concept:gt")),
        "ge": ("concept:ge", _local_op_cid("concept:ge")),
        "logical_not": ("concept:not", _local_op_cid("concept:not")),
    }
    for entry, (_operator, op_cid) in zip(result.ir, expected.values(), strict=True):
        atoms = _operator_atoms(entry["term_shape"])
        assert atoms[0]["op_cid"] == op_cid
        assert set(atoms[0]) == {"args", "op_cid"}
        assert all(arg == {} for arg in atoms[0]["args"])
        _assert_absent_keys(
            atoms[0], {"kind", "op", "file", "fn_line", "line", "column"}
        )


def test_operand_slot_accepts_op_cid_only_operation_atoms() -> None:
    atom = {
        "op_cid": _local_op_cid("concept:add"),
        "args": [{}, {}],
    }

    assert _operand_slot(atom) == atom


def test_bind_lift_operator_atoms_make_distinct_term_shape_cids() -> None:
    add = lift_source("def f(x, y):\n    return x + y\n", "pkg/add.py").ir[0]
    sub = lift_source("def f(x, y):\n    return x - y\n", "pkg/sub.py").ir[0]

    assert add["term_shape_cid"] != sub["term_shape_cid"]


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("a < b", ["concept:lt"]),
        ("a == b", ["concept:eq"]),
        ("a >= b", ["concept:ge"]),
    ],
)
def test_bind_lift_compare_single_op_discriminates_concept_atom(
    expr: str,
    expected: list[str],
) -> None:
    result = lift_source(f"def f(a, b):\n    return {expr}\n", "pkg/compare_single.py")

    assert result.diagnostics == []
    assert _operator_cids(result.ir[0]["term_shape"]) == [
        _local_op_cid(op) for op in expected
    ]


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("a < b < c", ["concept:ite", "concept:lt", "concept:lt"]),
        ("a < b >= c", ["concept:ite", "concept:lt", "concept:ge"]),
        ("a == b != c", ["concept:ite", "concept:eq", "concept:ne"]),
    ],
)
def test_bind_lift_compare_two_chain_desugars_to_and_composition(
    expr: str,
    expected: list[str],
) -> None:
    result = lift_source(f"def f(a, b, c):\n    return {expr}\n", "pkg/compare_two.py")

    assert result.diagnostics == []
    assert _operator_cids(result.ir[0]["term_shape"]) == [
        _local_op_cid(op) for op in expected
    ]


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        (
            "a < b <= c != d",
            ["concept:ite", "concept:ite", "concept:lt", "concept:le", "concept:ne"],
        ),
        (
            "a > b >= c == d",
            ["concept:ite", "concept:ite", "concept:gt", "concept:ge", "concept:eq"],
        ),
        (
            "a != b < c > d",
            ["concept:ite", "concept:ite", "concept:ne", "concept:lt", "concept:gt"],
        ),
    ],
)
def test_bind_lift_compare_three_chain_mixed_ops_desugars_to_and_composition(
    expr: str,
    expected: list[str],
) -> None:
    result = lift_source(
        f"def f(a, b, c, d):\n    return {expr}\n", "pkg/compare_three.py"
    )

    assert result.diagnostics == []
    assert _operator_cids(result.ir[0]["term_shape"]) == [
        _local_op_cid(op) for op in expected
    ]


def test_bind_lift_line_comments_as_concept_comment_terms() -> None:
    source = (
        "def f(value):\n"
        "    # first line comment\n"
        "    value = value + 1\n"
        "    # second line comment\n"
        "    # third line comment\n"
        "    return value\n"
    )

    result = lift_source(source, "pkg/comment_lines.py")

    assert result.diagnostics == []
    term_shape = result.ir[0]["term_shape"]
    assert _operator_cids(term_shape).count(_local_op_cid("concept:comment")) == 3
    assert _concept_comment_surfaces(term_shape) == [
        "first line comment",
        "second line comment",
        "third line comment",
    ]


def test_bind_lift_concept_comment_excludes_comment_carriers() -> None:
    source = (
        "def f(value):\n"
        "    # sugar:concept:skip\n"
        "    # sugar-concept: {}\n"
        "    # sugar-concept-payload-cid: blake3-512:dead\n"
        "    # ordinary comment\n"
        "    return value\n"
    )

    result = lift_source(source, "pkg/comment_carriers.py")

    assert _concept_comment_surfaces(result.ir[0]["term_shape"]) == ["ordinary comment"]


def test_bind_lift_filters_unnamed_concepts_and_void_return() -> None:
    source = (
        "# concept: UNNAMED-CONCEPT-deadbeef\n"
        "def generated(x):\n"
        "    x += 1\n"
        "    return None\n"
        "\n"
        "def no_annotation(y) -> None:\n"
        "    return None\n"
    )

    result = lift_source(source, "foo.py")

    _assert_absent_keys(result.ir, {"concept_annotation", "fn_name"})
    assert result.ir[0]["param_names"] == ["x"]
    assert "param_types" not in result.ir[0]
    assert "return_type" not in result.ir[0]
    assert result.ir[0]["term_shape"] == _gamma_shape("concept:add", [{}, {}])
    assert "UNNAMED-CONCEPT" not in json.dumps(result.ir, sort_keys=True)
    assert "return_type" not in result.ir[1]


def test_bind_rpc_initialize_declares_bind_ir_surface() -> None:
    result = initialize_result()

    assert result["name"] == "sugar-lift-python-bind"
    assert result["protocol_version"] == "pep/1.7.0"
    assert result["capabilities"] == {
        "authoring_surfaces": ["python", "python-bind"],
        "emits_signed_mementos": False,
        "ir_version": "bind-ir/1.0.0",
    }


def test_checked_in_project_registers_python_bind_lift_surface() -> None:
    entries = _plugin_entries(ROOT / "implementations/python/.sugar/config.toml")

    assert {
        "name": "python-bind",
        "kind": "lift",
        "surface": "python-bind",
        "layer": "library-bindings",
    } in entries


def test_checked_in_python_bind_manifest_invokes_module_form_and_declares_kit() -> None:
    manifest = _python_bind_manifest()

    assert manifest["command"] == [
        "python3",
        "-m",
        "sugar_lift_python_source.bind_rpc",
        "--rpc",
    ]
    assert manifest["working_dir"] == "sugar-lift-python-source/src"

    completed = subprocess.run(
        manifest["command"],
        cwd=ROOT / "implementations/python" / str(manifest["working_dir"]),
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
    assert "error" not in declaration, declaration
    assert declaration["result"]["kit"]["id"] == "python-bind"


def test_bind_rpc_kit_declaration_returns_python_bind_surface() -> None:
    response = dispatch(
        {"jsonrpc": "2.0", "id": 2, "method": KIT_DECLARATION_RPC_METHOD}
    )

    assert "error" not in response, response
    result = response["result"]
    assert result["kit"] == {
        "id": "python-bind",
        "language": "python",
        "version": "0.1.0",
    }
    required_by_name = {
        method["name"]: method["required"] for method in result["rpc"]["methods"]
    }
    assert required_by_name == {
        "initialize": True,
        KIT_DECLARATION_RPC_METHOD: True,
        "lift": True,
        "shutdown": False,
    }
    assert result["proofResolution"] == {"strategy": "pip"}
    assert result["effectKinds"] == []
    assert result["effectLeaves"] == []
    assert result["guardPredicates"] == []
    assert result["controlCarriers"] == []
    assert result["residueCategories"] == []


def test_bind_rpc_lift_returns_ir_document(tmp_path: Path) -> None:
    source = tmp_path / "foo.py"
    source.write_text(
        "# concept: identity\ndef f(x: int) -> int:\n    return x\n", encoding="utf-8"
    )

    response = dispatch(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "lift",
            "params": {
                "workspace_root": str(tmp_path),
                "source_paths": ["foo.py"],
            },
        }
    )

    assert response["id"] == 7
    assert response["result"]["kind"] == "ir-document"
    assert response["result"]["diagnostics"] == []
    assert "concept_annotation" not in response["result"]["ir"][0]
    assert "fn_name" not in response["result"]["ir"][0]


def test_bind_lift_recovers_contract_comment_witness() -> None:
    payload, payload_cid = _contract_comment_payload(
        "pre", _formula_gte_x_zero(), "x >= 0"
    )
    source = (
        _comment_lines(payload, payload_cid)
        + "# concept: identity\n"
        + "def wrap_identity(x: int) -> int:\n"
        + "    return x\n"
    )

    result = lift_source(source, "pkg/foo.py")

    assert result.diagnostics == []
    witnesses = result.ir[0]["witnesses"]
    assert len(witnesses) == 1
    witness = witnesses[0]
    assert witness["role"] == "pre"
    assert witness["source_kind"] == "native-surface"
    assert witness["confidence_basis_points"] == 10000
    assert witness["predicate"] == _formula_gte_x_zero()
    assert witness["predicate_text"] == "x >= 0"
    assert witness["extension_fields"] == {
        "concept_site_cid": _cid("1"),
        "contract_cid": _cid("2"),
        "ir_formula_jcs_cid": cid_of_json(_formula_gte_x_zero()),
        "local_contract_cid": _cid("2"),
        "loss_record_cid": _cid("4"),
        "payload_cid": payload_cid,
        "policy_cid": _cid("5"),
        "sugar_dict_cid": _cid("6"),
        "surface": "contract-comment-sugar",
    }


def test_bind_lift_recovers_docstring_contract_comment_witness() -> None:
    payload, payload_cid = _contract_comment_payload(
        "post", _formula_out_eq_x(), "out == x"
    )
    source = (
        "def wrap_identity(x: int) -> int:\n"
        '    """\n'
        "    human prose stays non-authoritative\n"
        "    sugar-contract: "
        + json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        + "\n"
        f"    sugar-contract-payload-cid: {payload_cid}\n"
        '    """\n'
        "    return x\n"
    )

    result = lift_source(source, "pkg/foo.py")

    assert result.diagnostics == []
    witness = result.ir[0]["witnesses"][0]
    assert witness["role"] == "post"
    assert witness["predicate"] == _formula_out_eq_x()
    assert witness["extension_fields"]["payload_cid"] == payload_cid


def test_bind_lift_contract_comment_fails_closed_for_bad_payloads() -> None:
    payload, payload_cid = _contract_comment_payload(
        "pre", _formula_gte_x_zero(), "x >= 0"
    )
    cases = [
        _comment_lines(
            {**payload, "role": "sideways"},
            cid_of_json({**payload, "role": "sideways"}),
        ),
        _comment_lines(
            {**payload, "schema_version": "2"},
            cid_of_json({**payload, "schema_version": "2"}),
        ),
        _comment_lines(
            {**payload, "ir_formula_jcs_cid": _cid("7")},
            cid_of_json({**payload, "ir_formula_jcs_cid": _cid("7")}),
        ),
        _comment_lines(payload, _cid("8")),
        "# sugar-contract: {not json}\n",
    ]

    for prefix in cases:
        result = lift_source(
            prefix + "def f(x: int) -> int:\n    return x\n", "pkg/foo.py"
        )

        assert result.ir[0].get("witnesses", []) == []
        assert any(
            diag["kind"] == "contract-comment-invalid" for diag in result.diagnostics
        )


def test_bind_lift_recovers_decorator_contract_witnesses() -> None:
    source = (
        "from sugar_lift_py_tests.decorators import contract\n"
        '@contract(pre="x >= 0", post="out >= 0")\n'
        "def nonnegative_identity(x: int) -> int:\n"
        "    return x\n"
    )

    result = lift_source(source, "pkg/foo.py")

    assert result.diagnostics == []
    witnesses = result.ir[0]["witnesses"]
    assert [witness["role"] for witness in witnesses] == ["pre", "post"]
    assert [witness["predicate_text"] for witness in witnesses] == [
        "x >= 0",
        "out >= 0",
    ]
    assert all(witness["source_kind"] == "native-surface" for witness in witnesses)
    assert all(
        witness["extension_fields"]["surface"] == "python-decorator-contract"
        for witness in witnesses
    )


# =============================================================================
# Substrate-honest parity: loss, observed_dimension, @concept_gap
# =============================================================================


def test_sugar_bind_with_empty_loss_emits_empty_entries() -> None:
    source = (
        "from sugar import sugar\n"
        "import sqlite3\n"
        "\n"
        '@sugar.bind(concept="concept:sql-connection-close", library="sqlite3", loss=[])\n'
        "def close_connection(conn: sqlite3.Connection) -> None:\n"
        "    conn.close()\n"
    )
    result = lift_source(source, "shim.py", layer="library-bindings")
    assert result.diagnostics == []
    assert len(result.ir) == 1
    entry = result.ir[0]
    assert entry["kind"] == "library-sugar-binding-entry"
    lrc = entry["loss_record_contribution"]
    assert lrc["form"] == "literal"
    assert lrc["value"]["entries"] == []
    assert "observed_dimension" not in entry


def test_sugar_bind_with_multi_dim_loss_populates_entries() -> None:
    source = (
        "from sugar import sugar\n"
        "import sqlite3\n"
        "\n"
        "@sugar.bind(\n"
        '    concept="concept:sql-connection-open",\n'
        '    library="sqlite3",\n'
        '    loss=["sync-vs-async", "auth-mechanism", "connection-pooling"],\n'
        ")\n"
        "def open_db(path: str) -> sqlite3.Connection:\n"
        "    return sqlite3.connect(path)\n"
    )
    result = lift_source(source, "shim.py", layer="library-bindings")
    assert result.diagnostics == []
    assert len(result.ir) == 1
    entry = result.ir[0]
    entries = entry["loss_record_contribution"]["value"]["entries"]
    assert entries == ["sync-vs-async", "auth-mechanism", "connection-pooling"]
    assert "observed_dimension" not in entry


def test_sugar_bind_with_observed_dimension_propagates_to_entry() -> None:
    source = (
        "from sugar import sugar\n"
        "import sqlite3\n"
        "\n"
        "@sugar.bind(\n"
        '    concept="concept:contract-observation",\n'
        '    library="sqlite3",\n'
        '    observed_dimension="autocommit-mode",\n'
        ")\n"
        "def in_transaction(conn: sqlite3.Connection) -> bool:\n"
        "    return conn.in_transaction\n"
    )
    result = lift_source(source, "shim.py", layer="library-bindings")
    assert result.diagnostics == []
    assert len(result.ir) == 1
    entry = result.ir[0]
    assert entry["observed_dimension"] == "autocommit-mode"
    # No loss provided, so entries should be empty
    assert entry["loss_record_contribution"]["value"]["entries"] == []


def test_concept_gap_decorator_emits_concept_gap_memento() -> None:
    source = (
        "from sugar import concept_gap\n"
        "\n"
        "@concept_gap(\n"
        '    surface="sqlite3.Connection.backup",\n'
        '    concept="concept:sql-physical-backup",\n'
        '    reason="SQLite-binary-specific physical backup. N=1 across connection-level APIs.",\n'
        '    would_close_with_cluster="Connection-level physical-backup method on >=2 SQL drivers",\n'
        ")\n"
        "class GappedBackup:\n"
        "    pass\n"
    )
    result = lift_source(source, "shim.py", layer="library-bindings")
    assert result.diagnostics == []
    assert len(result.ir) == 1
    entry = result.ir[0]
    assert entry["kind"] == "concept-gap-memento"
    assert entry["target_language"] == "python"
    assert entry["surface"] == "sqlite3.Connection.backup"
    assert entry["concept"] == "concept:sql-physical-backup"
    assert entry["reason"] != ""
    assert (
        entry["would_close_with_cluster"]
        == "Connection-level physical-backup method on >=2 SQL drivers"
    )


def test_concept_gap_decorator_sugar_namespace_also_recognized() -> None:
    source = (
        "import sugar\n"
        "\n"
        "@sugar.concept_gap(\n"
        '    surface="sqlite3.Connection.backup",\n'
        '    concept="concept:sql-physical-backup",\n'
        '    reason="SQLite-binary-specific physical backup. N=1.",\n'
        '    would_close_with_cluster="Connection-level physical-backup on >=2 drivers",\n'
        ")\n"
        "class GappedBackupNs:\n"
        "    pass\n"
    )
    result = lift_source(source, "shim.py", layer="library-bindings")
    assert result.diagnostics == []
    assert len(result.ir) == 1
    entry = result.ir[0]
    assert entry["kind"] == "concept-gap-memento"
    assert entry["surface"] == "sqlite3.Connection.backup"


def test_concept_gap_missing_field_produces_diagnostic_not_ir() -> None:
    source = (
        "from sugar import concept_gap\n"
        "\n"
        "@concept_gap(\n"
        '    surface="sqlite3.Connection.backup",\n'
        '    concept="concept:sql-physical-backup",\n'
        "    # reason and would_close_with_cluster intentionally omitted\n"
        ")\n"
        "class BadGapBackup:\n"
        "    pass\n"
    )
    result = lift_source(source, "shim.py", layer="library-bindings")
    assert len(result.ir) == 0
    assert any(d["kind"] == "concept-gap-memento-invalid" for d in result.diagnostics)


def test_sugar_and_concept_gap_coexist_in_same_file() -> None:
    source = (
        "from sugar import sugar, concept_gap\n"
        "import sqlite3\n"
        "\n"
        "@sugar.bind(\n"
        '    concept="concept:sql-connection-open",\n'
        '    library="sqlite3",\n'
        '    loss=["sync-vs-async"],\n'
        ")\n"
        "def open_db(path: str) -> sqlite3.Connection:\n"
        "    return sqlite3.connect(path)\n"
        "\n"
        "@concept_gap(\n"
        '    surface="sqlite3.Connection.backup",\n'
        '    concept="concept:sql-physical-backup",\n'
        '    reason="SQLite-binary-specific. N=1.",\n'
        '    would_close_with_cluster="Connection-level backup on >=2 drivers",\n'
        ")\n"
        "class GappedBackup:\n"
        "    pass\n"
    )
    result = lift_source(source, "shim.py", layer="library-bindings")
    assert result.diagnostics == []
    kinds = [e["kind"] for e in result.ir]
    assert kinds.count("library-sugar-binding-entry") == 1
    assert kinds.count("concept-gap-memento") == 1


def test_concept_gap_decorator_new_spelling_emits_concept_gap_memento() -> None:
    source = (
        "from sugar import concept_gap\n"
        "\n"
        "@concept_gap(\n"
        '    surface="sqlite3.Connection.backup",\n'
        '    concept="concept:sql-physical-backup",\n'
        '    reason="SQLite-binary-specific physical backup. N=1 across connection-level APIs.",\n'
        '    would_close_with_cluster="Connection-level physical-backup method on >=2 SQL drivers",\n'
        ")\n"
        "class BackupConceptGap:\n"
        "    pass\n"
    )
    result = lift_source(source, "shim.py", layer="library-bindings")
    assert result.diagnostics == []
    assert len(result.ir) == 1
    entry = result.ir[0]
    assert entry["kind"] == "concept-gap-memento"
    assert entry["surface"] == "sqlite3.Connection.backup"


def test_layer_all_emits_both_bind_entry_and_language_neutral_entry() -> None:
    """layer='all' must emit BOTH library-sugar-binding-entry AND bind-lift-entry."""
    source = (
        "from sugar import sugar\n"
        "import sqlite3\n"
        "\n"
        '@sugar.bind(concept="concept:sql-connection-close", library="sqlite3", loss=[])\n'
        "def close_connection(conn: sqlite3.Connection) -> None:\n"
        "    conn.close()\n"
    )
    result = lift_source(source, "shim.py", layer="all")
    assert result.diagnostics == []
    kinds = [e["kind"] for e in result.ir]
    assert (
        "library-sugar-binding-entry" in kinds
    ), "layer='all' must include library-sugar-binding-entry"
    assert "bind-lift-entry" in kinds, "layer='all' must include bind-lift-entry"


def test_sugar_bind_body_source_is_a_lean_source_memento() -> None:
    """body_source is the SourceMemento: locus + CIDs, ZERO inline body. cmd_mint
    and the recognizer resolve the body from disk via the Source Oracle -- the
    proof never carries a doubled copy of the code (no flag, no fat alternative)."""
    source = (
        "from sugar import sugar\n"
        "import sqlite3\n"
        "\n"
        '@sugar.bind(concept="concept:sql-connection-close", library="sqlite3", loss=[])\n'
        "def close_connection(conn: sqlite3.Connection) -> None:\n"
        "    conn.close()\n"
    )
    result = lift_source(source, "shim.py", layer="library-bindings")
    assert result.diagnostics == []
    assert len(result.ir) == 1
    bs = result.ir[0]["body_source"]
    assert (
        "body_text" not in bs and "ast_template" not in bs
    ), "no inline body in the proof"
    assert (
        bs["source_cid"] and bs["template_cid"]
    ), "the body is PINNED by cid, not carried"


def _single_sugar_entry(source: str) -> dict:
    result = lift_source(source, "shim.py", layer="library-bindings")
    assert result.diagnostics == []
    assert len(result.ir) == 1
    return result.ir[0]


def test_sugar_body_emits_ast_template_alongside_body_text() -> None:
    source = (
        "from sugar import sugar\n"
        "import json\n"
        "\n"
        '@sugar.bind(concept="concept:json-parse", library="json")\n'
        "def json_parse(payload):\n"
        "    return json.loads(payload)\n"
    )

    import ast as _ast
    from sugar_lift_python_source.ast_template import function_body_template

    entry = _single_sugar_entry(source)
    body_source = entry["body_source"]

    # body_source is the SourceMemento -- no inline template/body in the proof.
    assert "body_text" not in body_source and "ast_template" not in body_source
    assert body_source["param_names"] == ["payload"]
    # the SourceMemento PINS the template by cid; recomputing it from the source
    # reproduces that cid (the oracle reconstructs the exact dict on demand).
    fn = next(n for n in _ast.parse(source).body if isinstance(n, _ast.FunctionDef))
    expected = function_body_template(fn)
    assert expected == {
        "kind": "block",
        "stmts": [
            {
                "kind": "expr_stmt",
                "expr": {
                    "kind": "return",
                    "expr": {
                        "kind": "method_call",
                        "receiver": {"kind": "ident", "name": "json"},
                        "method": "loads",
                        "args": [{"kind": "param_ref", "index": 1}],
                    },
                },
                "trailing_semi": False,
            }
        ],
    }
    assert body_source["template_cid"] == _template_cid_of_json(expected)


def test_sugar_body_alpha_equivalence_collapses_to_same_cid() -> None:
    src_a = (
        "from sugar import sugar\n"
        "\n"
        '@sugar.bind(concept="concept:json-parse", library="json-a")\n'
        "def json_parse(payload):\n"
        "    return json.loads(payload)\n"
    )
    src_b = (
        "from sugar import sugar\n"
        "\n"
        '@sugar.bind(concept="concept:json-parse", library="json-b")\n'
        "def json_parse(raw_text):\n"
        "    return json.loads(raw_text)\n"
    )

    entry_a = _single_sugar_entry(src_a)
    entry_b = _single_sugar_entry(src_b)

    # alpha-equivalent bodies pin the SAME template_cid; different parameter names
    # mean different SOURCE bytes -> different source_cid. (No inline template/body
    # in the SourceMemento; the cids carry the invariant.)
    assert (
        entry_a["body_source"]["template_cid"] == entry_b["body_source"]["template_cid"]
    )
    assert entry_a["body_source"]["source_cid"] != entry_b["body_source"]["source_cid"]


def test_sugar_body_param_name_swap_canonicalizes() -> None:
    src_a = (
        "from sugar import sugar\n"
        "\n"
        '@sugar.bind(concept="concept:call", library="lib-a")\n'
        "def f(a, b):\n"
        "    return g(a, b)\n"
    )
    src_b = (
        "from sugar import sugar\n"
        "\n"
        '@sugar.bind(concept="concept:call", library="lib-b")\n'
        "def f(x, y):\n"
        "    return g(x, y)\n"
    )

    entry_a = _single_sugar_entry(src_a)
    entry_b = _single_sugar_entry(src_b)

    assert (
        entry_a["body_source"]["template_cid"] == entry_b["body_source"]["template_cid"]
    )


def test_universal_lift_untagged_function_is_sugar_at_library_bindings_layer() -> None:
    # The zero-code-changes product: a plain function — NO @sugar.bind, no
    # sugar import, nothing — IS sugar at the library-bindings layer, with the
    # symbol derived from the qualified module path. The `all` (contract) layer
    # is unaffected, so the general bind-lift-entry tests keep holding.
    source = "def add(x, y):\n    return x + y\n"

    lb = lift_source(source, "pkg/calc.py", layer="library-bindings")
    sugar = [e for e in lb.ir if e.get("kind") == "library-sugar-binding-entry"]
    assert len(sugar) == 1
    assert sugar[0]["symbol"] == "pkg.calc.add"
    assert sugar[0]["binding_origin"] == "derived"
    # body_source is the SourceMemento: locus + cids, no inline body (the oracle
    # resolves `return x + y` from disk on demand).
    bs = sugar[0]["body_source"]
    assert "body_text" not in bs and "ast_template" not in bs
    assert bs["source_cid"] and bs["template_cid"]
    assert "op_cid" in sugar[0]

    # The general `all` layer does NOT emit a derived sugar binding (untagged) —
    # only the bind-lift-entry — so the contract-path unit tests are unaffected.
    al = lift_source(source, "pkg/calc.py", layer="all")
    assert not [e for e in al.ir if e.get("kind") == "library-sugar-binding-entry"]


def test_public_reexport_map_follows_declared_internal_star_hops(
    tmp_path: Path,
) -> None:
    package = tmp_path / "project"
    package.mkdir()
    (package / "__init__.py").write_text("from ._core import finfo\n", encoding="utf-8")
    core = package / "_core"
    core.mkdir()
    (core / "__init__.py").write_text("from .getlimits import *\n", encoding="utf-8")
    (core / "getlimits.py").write_text(
        "__all__ = ['finfo']\n" "class finfo:\n" "    pass\n",
        encoding="utf-8",
    )

    reexports = _public_reexport_map(package)

    assert reexports is not None
    assert reexports["_core.finfo"] == ("project", "project.finfo")
    assert reexports["_core.getlimits.finfo"] == ("project", "project.finfo")


def test_public_reexport_map_follows_absolute_package_aggregator_chain(
    tmp_path: Path,
) -> None:
    package = tmp_path / "project"
    package.mkdir()
    (package / "__init__.py").write_text(
        "from project.core.api import DataFrame\n",
        encoding="utf-8",
    )
    core = package / "core"
    core.mkdir()
    (core / "__init__.py").write_text("", encoding="utf-8")
    (core / "api.py").write_text(
        "from project.core.frame import DataFrame\n",
        encoding="utf-8",
    )
    (core / "frame.py").write_text("class DataFrame:\n    pass\n", encoding="utf-8")

    reexports = _public_reexport_map(package)

    assert reexports is not None
    assert reexports["core.api.DataFrame"] == ("project", "project.DataFrame")
    assert reexports["core.frame.DataFrame"] == ("project", "project.DataFrame")


def test_public_reexport_map_follows_nested_api_namespace_and_aliases(
    tmp_path: Path,
) -> None:
    package = tmp_path / "project"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    api = package / "api" / "indexers"
    api.mkdir(parents=True)
    (package / "api" / "__init__.py").write_text(
        "from project.api import indexers\n",
        encoding="utf-8",
    )
    (api / "__init__.py").write_text(
        "from project.core.indexers.objects import (\n"
        "    VariableOffsetWindowIndexer,\n"
        "    BaseIndexer as PublicBaseIndexer,\n"
        ")\n",
        encoding="utf-8",
    )
    objects = package / "core" / "indexers"
    objects.mkdir(parents=True)
    (package / "core" / "__init__.py").write_text("", encoding="utf-8")
    (package / "core" / "indexers" / "__init__.py").write_text("", encoding="utf-8")
    (objects / "objects.py").write_text(
        "class BaseIndexer:\n    pass\n"
        "class VariableOffsetWindowIndexer:\n    pass\n",
        encoding="utf-8",
    )

    reexports = _public_reexport_map(package)

    assert reexports is not None
    assert reexports["core.indexers.objects.VariableOffsetWindowIndexer"] == (
        "project",
        "project.api.indexers.VariableOffsetWindowIndexer",
    )
    assert reexports["core.indexers.objects.BaseIndexer"] == (
        "project",
        "project.api.indexers.PublicBaseIndexer",
    )


def test_public_reexport_map_follows_absolute_star_exports(
    tmp_path: Path,
) -> None:
    package = tmp_path / "project"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    api = package / "api" / "types"
    api.mkdir(parents=True)
    (package / "api" / "__init__.py").write_text("", encoding="utf-8")
    (api / "__init__.py").write_text(
        "from project.core.dtypes.api import *\n",
        encoding="utf-8",
    )
    dtypes = package / "core" / "dtypes"
    dtypes.mkdir(parents=True)
    (package / "core" / "__init__.py").write_text("", encoding="utf-8")
    (dtypes / "__init__.py").write_text("", encoding="utf-8")
    (dtypes / "api.py").write_text(
        "__all__ = ['is_integer_dtype']\n"
        "def is_integer_dtype(value):\n"
        "    return True\n",
        encoding="utf-8",
    )

    reexports = _public_reexport_map(package)

    assert reexports is not None
    assert reexports["core.dtypes.api.is_integer_dtype"] == (
        "project",
        "project.api.types.is_integer_dtype",
    )


def test_public_reexport_map_prefers_top_level_public_spelling(
    tmp_path: Path,
) -> None:
    package = tmp_path / "project"
    package.mkdir()
    (package / "__init__.py").write_text(
        "from project.io.parsers.readers import read_fwf\n",
        encoding="utf-8",
    )
    parsers = package / "io" / "parsers"
    parsers.mkdir(parents=True)
    (package / "io" / "__init__.py").write_text("", encoding="utf-8")
    (parsers / "__init__.py").write_text(
        "from project.io.parsers.readers import read_fwf\n",
        encoding="utf-8",
    )
    (parsers / "readers.py").write_text(
        "def read_fwf():\n" "    pass\n",
        encoding="utf-8",
    )

    reexports = _public_reexport_map(package)

    assert reexports is not None
    assert reexports["io.parsers.readers.read_fwf"] == (
        "project",
        "project.read_fwf",
    )
