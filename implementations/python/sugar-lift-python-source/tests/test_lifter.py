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

from sugar_lift_py_tests.canonicalizer import jcs_hash, vobj, vstr

from sugar_lift_python_source.canonical import canonical_json_bytes, cid_of_json
from sugar_lift_python_source.compiler import compile_body_term, compile_ir_document
from sugar_lift_python_source.ir import int_const, str_const
from sugar_lift_python_source.lifter import (
    _EffectSet,
    _Emitter,
    _UnsupportedSyntax,
    lift_source,
)
from sugar_lift_python_source.rpc import dispatch, initialize_result

KIT_DECLARATION_RPC_METHOD = "sugar.plugin.kit_declaration"
RUNTIME_FAILURE_EFFECT_LEAF = {
    "surface": "python-source",
    "local": "python:raise",
    "concept": "concept:panic-freedom.leaf.runtime-failure-site",
}
ATTRIBUTE_RUNTIME_FAILURE_EFFECT_LEAF = {
    "surface": "python-source",
    "local": "python:attribute",
    "concept": "concept:panic-freedom.leaf.runtime-failure-site",
}
SUBSCRIPT_RUNTIME_FAILURE_EFFECT_LEAF = {
    "surface": "python-source",
    "local": "python:subscript",
    "concept": "concept:panic-freedom.leaf.runtime-failure-site",
}
RUNTIME_FAILURE_EFFECT_LEAVES = [
    RUNTIME_FAILURE_EFFECT_LEAF,
    ATTRIBUTE_RUNTIME_FAILURE_EFFECT_LEAF,
    SUBSCRIPT_RUNTIME_FAILURE_EFFECT_LEAF,
]
PANIC_FREEDOM_EFFECT_KIND = "panic-freedom"
RUNTIME_FAILURE_SITE_CONCEPT = "concept:panic-freedom.leaf.runtime-failure-site"


def _canon(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


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


def _python_source_manifest() -> dict[str, object]:
    return _parse_top_level_toml(
        ROOT / "implementations/python/.sugar/lift/python-source/manifest.toml"
    )


def _contract(ir: list[dict[str, object]], suffix: str) -> dict[str, object]:
    for item in ir:
        if str(item.get("fnName", "")).endswith(suffix):
            return item
    raise AssertionError(f"missing contract ending in {suffix!r}: {ir!r}")


def _source_unit_contract(ir: list[dict[str, object]]) -> dict[str, object]:
    for item in ir:
        if str(item.get("fnName", "")).startswith("<source-unit:"):
            return item
    raise AssertionError(f"missing source-unit contract: {ir!r}")


def _class_shapes(ir: list[dict[str, object]]) -> list[dict[str, object]]:
    shapes = _source_unit_contract(ir).get("classShapes")
    assert isinstance(shapes, list), ir
    return [shape for shape in shapes if isinstance(shape, dict)]


def _class_shape(ir: list[dict[str, object]], qualname: str) -> dict[str, object]:
    for shape in _class_shapes(ir):
        if shape.get("qualname") == qualname:
            return shape
    raise AssertionError(f"missing class shape {qualname!r}: {_class_shapes(ir)!r}")


def _entries_by_name(entries: object) -> dict[str, dict[str, object]]:
    assert isinstance(entries, list), entries
    out: dict[str, dict[str, object]] = {}
    for entry in entries:
        assert isinstance(entry, dict), entry
        out[str(entry["name"])] = entry
    return out


def _runtime_failure_loci(contract: dict[str, object]) -> list[dict[str, object]]:
    loci = contract.get("panicLoci")
    assert isinstance(loci, list), contract
    return [locus for locus in loci if isinstance(locus, dict)]


def _var(name: str) -> dict[str, object]:
    return {"kind": "var", "name": name}


def _str_const(value: str) -> dict[str, object]:
    return {
        "kind": "const",
        "value": value,
        "sort": {"kind": "primitive", "name": "String"},
    }


def _attr(value: dict[str, object], name: str) -> dict[str, object]:
    return {
        "kind": "ctor",
        "name": "python:attribute",
        "args": [value, _str_const(name)],
    }


def _subscript(value: dict[str, object], index: dict[str, object]) -> dict[str, object]:
    return {"kind": "ctor", "name": "python:subscript", "args": [value, index]}


def _slice(
    lower: dict[str, object],
    upper: dict[str, object],
    step: dict[str, object],
) -> dict[str, object]:
    return {"kind": "ctor", "name": "python:slice", "args": [lower, upper, step]}


def _none_const() -> dict[str, object]:
    return {
        "kind": "const",
        "value": None,
        "sort": {"kind": "primitive", "name": "Unit"},
    }


def _no_value() -> dict[str, object]:
    return {"kind": "ctor", "name": "python:no_value", "args": []}


def _aug_assign(
    target: dict[str, object], op: str, value: dict[str, object]
) -> dict[str, object]:
    return {
        "kind": "ctor",
        "name": "python:aug_assign",
        "args": [target, _str_const(op), value],
    }


def _ann_assign(
    target: dict[str, object],
    annotation: dict[str, object],
    value: dict[str, object],
) -> dict[str, object]:
    return {
        "kind": "ctor",
        "name": "python:ann_assign",
        "args": [target, annotation, value],
    }


def _walrus(target: dict[str, object], value: dict[str, object]) -> dict[str, object]:
    return {
        "kind": "ctor",
        "name": "python:walrus",
        "args": [target, value],
    }


def _binary(
    name: str, left: dict[str, object], right: dict[str, object]
) -> dict[str, object]:
    return {"kind": "ctor", "name": name, "args": [left, right]}


def _call(name: str, *args: dict[str, object]) -> dict[str, object]:
    return {
        "kind": "ctor",
        "name": "python:call",
        "args": [_str_const(name), *args],
    }


def _call_term(callee: dict[str, object], *args: dict[str, object]) -> dict[str, object]:
    return {
        "kind": "ctor",
        "name": "python:call",
        "args": [callee, *args],
    }


def _kwarg(name: str, value: dict[str, object]) -> dict[str, object]:
    return {
        "kind": "ctor",
        "name": "python:kwarg",
        "args": [_str_const(name), value],
    }


def _tuple(*items: dict[str, object]) -> dict[str, object]:
    return {"kind": "ctor", "name": "python:tuple", "args": list(items)}


def _list(*items: dict[str, object]) -> dict[str, object]:
    return {"kind": "ctor", "name": "python:list", "args": list(items)}


def _listcomp(
    elt: dict[str, object], *generators: dict[str, object]
) -> dict[str, object]:
    return {"kind": "ctor", "name": "python:listcomp", "args": [elt, *generators]}


def _comprehension(
    target: dict[str, object],
    iterator: dict[str, object],
    *ifs: dict[str, object],
) -> dict[str, object]:
    return {
        "kind": "ctor",
        "name": "python:comprehension",
        "args": [target, iterator, *ifs],
    }


def _dict(*entries: dict[str, object]) -> dict[str, object]:
    return {"kind": "ctor", "name": "python:dict", "args": list(entries)}


def _dict_entry(key: dict[str, object], value: dict[str, object]) -> dict[str, object]:
    return {"kind": "ctor", "name": "python:dict_entry", "args": [key, value]}


def _bool_const(value: bool) -> dict[str, object]:
    return {
        "kind": "const",
        "value": value,
        "sort": {"kind": "primitive", "name": "Bool"},
    }


def _int_const(value: int) -> dict[str, object]:
    return {
        "kind": "const",
        "value": value,
        "sort": {"kind": "primitive", "name": "Int"},
    }


def _float_const(value: float) -> dict[str, object]:
    return {"kind": "const", "value": {"type": "float", "repr": repr(value)}}


def _bytes_const(value: bytes) -> dict[str, object]:
    return {"kind": "const", "value": {"type": "bytes", "repr": value.hex()}}


def _complex_const(value: complex) -> dict[str, object]:
    return {
        "kind": "const",
        "value": {
            "type": "complex",
            "re": repr(float(value.real)),
            "im": repr(float(value.imag)),
        },
    }


def _ellipsis_const() -> dict[str, object]:
    return {"kind": "const", "value": {"type": "ellipsis"}}


def _return(value: dict[str, object]) -> dict[str, object]:
    return {"kind": "ctor", "name": "python:return", "args": [value]}


def _assign(target: dict[str, object], value: dict[str, object]) -> dict[str, object]:
    return {"kind": "ctor", "name": "python:assign", "args": [target, value]}


def _seq(left: dict[str, object], right: dict[str, object]) -> dict[str, object]:
    return {"kind": "ctor", "name": "python:seq", "args": [left, right]}


def _expr_stmt(value: dict[str, object]) -> dict[str, object]:
    return {"kind": "ctor", "name": "python:expr", "args": [value]}


def _assert_stmt(
    condition: dict[str, object], message: dict[str, object]
) -> dict[str, object]:
    return {"kind": "ctor", "name": "python:assert", "args": [condition, message]}


def _with_stmt(body: dict[str, object]) -> dict[str, object]:
    return {"kind": "ctor", "name": "python:with", "args": [body]}


def _import_stmt(*names: str) -> dict[str, object]:
    return {
        "kind": "ctor",
        "name": "python:import",
        "args": [_str_const(name) for name in names],
    }


def _nested_funcdef(name: str) -> dict[str, object]:
    return {
        "kind": "ctor",
        "name": "python:nested_funcdef",
        "args": [_str_const(name)],
    }


def _fstring(*parts: dict[str, object]) -> dict[str, object]:
    return {"kind": "ctor", "name": "python:fstring", "args": list(parts)}


def _fstring_value(
    value: dict[str, object],
    conversion: dict[str, object] | None = None,
    format_spec: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "kind": "ctor",
        "name": "python:fstring_value",
        "args": [
            value,
            _none_const() if conversion is None else conversion,
            _none_const() if format_spec is None else format_spec,
        ],
    }


def _lambda_expr(*args: dict[str, object]) -> dict[str, object]:
    return {"kind": "ctor", "name": "python:lambda", "args": list(args)}


def _lambda_param(
    name: str,
    kind: str,
    default: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "kind": "ctor",
        "name": "python:lambda_param",
        "args": [
            _str_const(name),
            _str_const(kind),
            _no_value() if default is None else default,
        ],
    }


def _compare(
    op: str, left: dict[str, object], right: dict[str, object]
) -> dict[str, object]:
    return {
        "kind": "ctor",
        "name": "python:compare",
        "args": [_str_const(op), left, right],
    }


def _unpack_targets(*targets: dict[str, object]) -> dict[str, object]:
    return {
        "kind": "ctor",
        "name": "python:unpack_targets",
        "args": list(targets),
    }


def _unpack_assign(
    kind: str,
    targets: dict[str, object],
    value: dict[str, object],
) -> dict[str, object]:
    return {
        "kind": "ctor",
        "name": "python:unpack_assign",
        "args": [_str_const(kind), targets, value],
    }


def _ctor_names(node: object) -> list[str]:
    if isinstance(node, dict):
        names = [str(node["name"])] if node.get("kind") == "ctor" else []
        for child in node.get("args", []):
            names.extend(_ctor_names(child))
        return names
    if isinstance(node, list):
        names: list[str] = []
        for child in node:
            names.extend(_ctor_names(child))
        return names
    return []


def _compare_pairs(node: object) -> list[tuple[str, str, str]]:
    pairs: list[tuple[str, str, str]] = []
    if isinstance(node, dict):
        if node.get("kind") == "ctor" and node.get("name") == "python:compare":
            args = node["args"]
            pairs.append((args[0]["value"], args[1]["name"], args[2]["name"]))
        for child in node.get("args", []):
            pairs.extend(_compare_pairs(child))
    elif isinstance(node, list):
        for child in node:
            pairs.extend(_compare_pairs(child))
    return pairs


def _constant_dispatch_refusal_reason(value: object) -> str:
    node = ast.Constant(value=value)
    node.lineno = 1
    node.col_offset = 0
    emitter = _Emitter(
        fn_name="consts.f",
        locals_=set(),
        module_globals=set(),
        effects=_EffectSet(),
        source_path="consts.py",
        panic_loci=[],
    )
    with pytest.raises(_UnsupportedSyntax) as exc:
        emitter.constant(node)
    return exc.value.reason


def _assert_guard(
    term: object, expected_head: str, expected_arg: str
) -> dict[str, object]:
    assert isinstance(term, dict)
    assert term["kind"] == "ctor"
    assert term["name"] == "cf_guarded"
    args = term["args"]
    guard = args[0]
    assert guard == {
        "kind": "ctor",
        "name": expected_head,
        "args": [{"kind": "var", "name": expected_arg}],
    }
    return args[1]


def _assert_none_guarded_if(
    body: dict[str, object],
    *,
    op: str,
    then_head: str,
    else_head: str,
) -> None:
    assert body["kind"] == "ctor"
    assert body["name"] == "cf_ite"
    cond, then_branch, else_branch = body["args"]
    assert cond == {
        "kind": "ctor",
        "name": "python:compare",
        "args": [
            {
                "kind": "const",
                "value": op,
                "sort": {"kind": "primitive", "name": "String"},
            },
            {"kind": "var", "name": "x"},
            {
                "kind": "const",
                "value": None,
                "sort": {"kind": "primitive", "name": "Unit"},
            },
        ],
    }
    assert _assert_guard(then_branch, then_head, "x")["name"] == "python:return"
    assert _assert_guard(else_branch, else_head, "x")["name"] == "python:return"


def _function_body(result: object, suffix: str = ".f") -> dict[str, object]:
    assert hasattr(result, "ir")
    contract = _contract(result.ir, suffix)
    body = contract["post"]["args"][1]
    assert isinstance(body, dict), body
    return body


def _roundtrip_return_body(term: dict[str, object]) -> dict[str, object]:
    compiled = compile_body_term(_return(term))
    relifted = lift_source(compiled, "roundtrip_constants.py")
    assert relifted.refusals == []
    return _function_body(relifted)


def test_float_constant_lifts_to_tagged_floor_value() -> None:
    result = lift_source("def f():\n    return 1.5\n", "float_const.py")

    assert result.refusals == []
    assert _function_body(result) == _return(_float_const(1.5))


def test_float_floor_discriminates_unknown_constant_kind() -> None:
    assert _constant_dispatch_refusal_reason(object()) == "unsupported constant: object"


def test_float_constant_roundtrip_is_structurally_stable() -> None:
    assert _roundtrip_return_body(_float_const(1.5)) == _return(_float_const(1.5))


def test_bytes_constant_lifts_to_tagged_floor_value() -> None:
    result = lift_source("def f():\n    return b\"\\x00\\xff\"\n", "bytes_const.py")

    assert result.refusals == []
    assert _function_body(result) == _return(_bytes_const(b"\x00\xff"))


def test_bytes_floor_discriminates_unknown_constant_kind() -> None:
    assert _constant_dispatch_refusal_reason(object()) == "unsupported constant: object"


def test_bytes_constant_roundtrip_is_structurally_stable() -> None:
    assert _roundtrip_return_body(_bytes_const(b"\x00\xff")) == _return(
        _bytes_const(b"\x00\xff")
    )


def test_complex_constant_lifts_to_tagged_floor_value() -> None:
    result = lift_source("def f():\n    return 2j\n", "complex_const.py")

    assert result.refusals == []
    assert _function_body(result) == _return(_complex_const(2j))


def test_complex_floor_discriminates_unknown_constant_kind() -> None:
    assert _constant_dispatch_refusal_reason(object()) == "unsupported constant: object"


def test_complex_constant_roundtrip_is_structurally_stable() -> None:
    assert _roundtrip_return_body(_complex_const(2j)) == _return(_complex_const(2j))


def test_ellipsis_constant_lifts_to_tagged_floor_value() -> None:
    result = lift_source("def f():\n    ...\n", "ellipsis_const.py")

    assert result.refusals == []
    assert _function_body(result) == _expr_stmt(_ellipsis_const())


def test_ellipsis_floor_discriminates_unknown_constant_kind() -> None:
    assert _constant_dispatch_refusal_reason(object()) == "unsupported constant: object"


def test_ellipsis_constant_roundtrip_is_structurally_stable() -> None:
    assert _roundtrip_return_body(_ellipsis_const()) == _return(_ellipsis_const())


def test_lift_function_emits_source_unit_and_python_ops() -> None:
    source = "GLOBAL = 3\n\ndef add_one(x):\n    y = x + GLOBAL\n    return y\n"

    result = lift_source(source, "pkg/mod.py")

    assert result.refusals == []
    assert [item["fnName"] for item in result.ir] == [
        "<source-unit:pkg/mod.py>",
        "pkg.mod.add_one",
    ]

    source_unit = result.ir[0]["post"]["args"][1]
    assert source_unit["name"] == "python:source-unit"
    assert source_unit["args"][0]["value"] == source

    function_contract = result.ir[1]
    assert function_contract["formals"] == ["x"]
    # GLOBAL = 3 is a single-binding immutable literal: it value-pins, so the
    # body carries the value itself and no mutable-global read effect remains.
    assert function_contract["effects"] == []
    body = function_contract["post"]["args"][1]
    assert _ctor_names(body) == [
        "python:seq",
        "python:assign",
        "python:add",
        "python:return",
    ]
    assert json.dumps(int_const(3)) in json.dumps(body)
    assert all(not name.endswith(":unknown") for name in _ctor_names(result.ir))


@pytest.mark.parametrize(
    ("expr", "expected_pairs"),
    [
        ("a < b", [("<", "a", "b")]),
        ("a == b", [("==", "a", "b")]),
        ("a >= b", [(">=", "a", "b")]),
    ],
)
def test_compare_single_op_lifts_pairwise_discriminated_term(
    expr: str,
    expected_pairs: list[tuple[str, str, str]],
) -> None:
    result = lift_source(f"def f(a, b):\n    return {expr}\n", "compare_single.py")

    body = _contract(result.ir, ".f")["post"]["args"][1]

    assert result.refusals == []
    assert _compare_pairs(body) == expected_pairs
    assert "python:and" not in _ctor_names(body)


@pytest.mark.parametrize(
    ("expr", "expected_pairs"),
    [
        ("a < b < c", [("<", "a", "b"), ("<", "b", "c")]),
        ("a < b >= c", [("<", "a", "b"), (">=", "b", "c")]),
        ("a == b != c", [("==", "a", "b"), ("!=", "b", "c")]),
    ],
)
def test_compare_two_chain_lifts_to_pairwise_and_composition(
    expr: str,
    expected_pairs: list[tuple[str, str, str]],
) -> None:
    result = lift_source(f"def f(a, b, c):\n    return {expr}\n", "compare_two.py")

    body = _contract(result.ir, ".f")["post"]["args"][1]

    assert result.refusals == []
    assert _compare_pairs(body) == expected_pairs
    assert _ctor_names(body).count("python:and") == 1


@pytest.mark.parametrize(
    ("expr", "expected_pairs"),
    [
        ("a < b <= c != d", [("<", "a", "b"), ("<=", "b", "c"), ("!=", "c", "d")]),
        ("a > b >= c == d", [(">", "a", "b"), (">=", "b", "c"), ("==", "c", "d")]),
        ("a != b < c > d", [("!=", "a", "b"), ("<", "b", "c"), (">", "c", "d")]),
    ],
)
def test_compare_three_chain_mixed_ops_lifts_to_pairwise_and_composition(
    expr: str,
    expected_pairs: list[tuple[str, str, str]],
) -> None:
    result = lift_source(f"def f(a, b, c, d):\n    return {expr}\n", "compare_three.py")

    body = _contract(result.ir, ".f")["post"]["args"][1]

    assert result.refusals == []
    assert _compare_pairs(body) == expected_pairs
    assert _ctor_names(body).count("python:and") == 2


def test_walrus_literal_rhs_lifts_without_runtime_failure_loci_or_effects() -> None:
    source = "def f():\n    return (x := 42)\n"

    result = lift_source(source, "walrus_literal.py")

    contract = _contract(result.ir, ".f")
    body = contract["post"]["args"][1]
    assert result.refusals == []
    assert contract["effects"] == []
    assert contract.get("panicLoci", []) == []
    assert body == {
        "kind": "ctor",
        "name": "python:return",
        "args": [
            _walrus(
                _var("x"),
                {
                    "kind": "const",
                    "value": 42,
                    "sort": {"kind": "primitive", "name": "Int"},
                },
            )
        ],
    }


def test_walrus_name_rhs_lifts_to_expression_position_assignment() -> None:
    source = "def f(y):\n    return (x := y)\n"

    result = lift_source(source, "walrus_name.py")

    contract = _contract(result.ir, ".f")
    body = contract["post"]["args"][1]
    assert result.refusals == []
    assert contract["effects"] == []
    assert contract.get("panicLoci", []) == []
    assert body["args"][0] == _walrus(_var("x"), _var("y"))


def test_walrus_attribute_rhs_preserves_attribute_runtime_failure_locus() -> None:
    source = "def f(obj):\n    return (x := obj.name)\n"

    result = lift_source(source, "walrus_attr.py")

    contract = _contract(result.ir, ".f")
    target = _attr(_var("obj"), "name")
    loci = _runtime_failure_loci(contract)
    body = contract["post"]["args"][1]
    assert result.refusals == []
    assert contract["effects"] == [{"kind": "panics"}]
    assert [locus["subkind"] for locus in loci] == ["attribute-access"]
    assert [locus["argTerm"] for locus in loci] == [target]
    assert [(locus["line"], locus["col"]) for locus in loci] == [(2, 17)]
    assert [locus.get("exceptionClass") for locus in loci] == ["AttributeError"]
    assert body["args"][0] == _walrus(_var("x"), target)


def test_walrus_subscript_rhs_preserves_subscript_runtime_failure_locus() -> None:
    source = "def f(xs, key):\n    return (x := xs[key])\n"

    result = lift_source(source, "walrus_subscript.py")

    contract = _contract(result.ir, ".f")
    target = _subscript(_var("xs"), _var("key"))
    loci = _runtime_failure_loci(contract)
    body = contract["post"]["args"][1]
    assert result.refusals == []
    assert contract["effects"] == [{"kind": "panics"}]
    assert [locus["subkind"] for locus in loci] == ["subscript-access"]
    assert [locus["argTerm"] for locus in loci] == [target]
    assert [(locus["line"], locus["col"]) for locus in loci] == [(2, 17)]
    assert body["args"][0] == _walrus(_var("x"), target)


def test_walrus_slice_rhs_preserves_slice_runtime_failure_locus() -> None:
    source = "def f(xs, a, b):\n    return (x := xs[a:b])\n"

    result = lift_source(source, "walrus_slice.py")

    contract = _contract(result.ir, ".f")
    target = _subscript(_var("xs"), _slice(_var("a"), _var("b"), _none_const()))
    loci = _runtime_failure_loci(contract)
    body = contract["post"]["args"][1]
    assert result.refusals == []
    assert contract["effects"] == [{"kind": "panics"}]
    assert [locus["subkind"] for locus in loci] == ["subscript-access"]
    assert [locus["argTerm"] for locus in loci] == [target]
    assert [(locus["line"], locus["col"]) for locus in loci] == [(2, 17)]
    assert body["args"][0] == _walrus(_var("x"), target)


def test_walrus_if_condition_lifts_condition_as_expression() -> None:
    source = (
        "def f(compute, fallback):\n"
        "    if (x := compute()):\n"
        "        return x\n"
        "    return fallback\n"
    )

    result = lift_source(source, "walrus_if.py")

    contract = _contract(result.ir, ".f")
    body = contract["post"]["args"][1]
    assert result.refusals == []
    assert contract["effects"] == [{"kind": "unresolved_call", "name": "compute"}]
    assert contract.get("panicLoci", []) == []
    assert body["name"] == "python:seq"
    condition = body["args"][0]
    assert condition["name"] == "python:if"
    assert condition["args"][0] == _walrus(_var("x"), _call("compute"))


def test_walrus_while_condition_lifts_condition_as_expression() -> None:
    source = (
        "def f(next_value):\n"
        "    while (x := next_value()):\n"
        "        return x\n"
        "    return None\n"
    )

    result = lift_source(source, "walrus_while.py")

    contract = _contract(result.ir, ".f")
    body = contract["post"]["args"][1]
    assert result.refusals == []
    assert {"kind": "unresolved_call", "name": "next_value"} in contract["effects"]
    assert any(effect["kind"] == "opaque_loop" for effect in contract["effects"])
    assert contract.get("panicLoci", []) == []
    assert body["name"] == "python:seq"
    loop = body["args"][0]
    assert loop["name"] == "python:while"
    assert loop["args"][0] == _walrus(_var("x"), _call("next_value"))


@pytest.mark.parametrize(
    "source",
    [
        "def f(y):\n    return (x := y)\n",
        "def f(compute, fallback):\n    if (x := compute()):\n        return x\n    return fallback\n",
    ],
)
def test_compile_lift_roundtrip_preserves_walrus_body(source: str) -> None:
    lifted = lift_source(source, "roundtrip_walrus.py")
    assert lifted.refusals == []
    contract = _contract(lifted.ir, ".f")
    body = contract["post"]["args"][1]

    compiled = compile_body_term(
        body,
        fn_name="f",
        formals=[str(formal) for formal in contract["formals"]],
    )
    relifted = lift_source(compiled, "roundtrip_walrus.py")
    assert relifted.refusals == []
    relifted_body = _contract(relifted.ir, ".f")["post"]["args"][1]

    assert canonical_json_bytes(relifted_body) == canonical_json_bytes(body)
    assert ":=" in compiled


def test_tuple_unpack_names_emits_unpack_assign_runtime_failure_locus() -> None:
    source = "def f(pair):\n    a, b = pair\n    return a\n"

    result = lift_source(source, "tuple_unpack.py")

    contract = _contract(result.ir, ".f")
    body = contract["post"]["args"][1]
    unpack = _unpack_assign(
        "tuple", _unpack_targets(_var("a"), _var("b")), _var("pair")
    )
    assert result.refusals == []
    assert contract["effects"] == [{"kind": "panics"}]
    assert _runtime_failure_loci(contract) == [
        {
            "effectKind": PANIC_FREEDOM_EFFECT_KIND,
            "callee": RUNTIME_FAILURE_SITE_CONCEPT,
            "subkind": "iter-unpack",
            "argTerm": unpack,
            "file": "tuple_unpack.py",
            "line": 2,
            "col": 4,
        }
    ]
    assert body["name"] == "python:seq"
    assert body["args"][0] == unpack


def test_list_unpack_names_preserves_list_kind_in_unpack_assign() -> None:
    source = "def f(pair):\n    [a, b] = pair\n    return b\n"

    result = lift_source(source, "list_unpack.py")

    contract = _contract(result.ir, ".f")
    body = contract["post"]["args"][1]
    unpack = _unpack_assign("list", _unpack_targets(_var("a"), _var("b")), _var("pair"))
    assert result.refusals == []
    assert contract["effects"] == [{"kind": "panics"}]
    assert _runtime_failure_loci(contract) == [
        {
            "effectKind": PANIC_FREEDOM_EFFECT_KIND,
            "callee": RUNTIME_FAILURE_SITE_CONCEPT,
            "subkind": "iter-unpack",
            "argTerm": unpack,
            "file": "list_unpack.py",
            "line": 2,
            "col": 4,
        }
    ]
    assert body["name"] == "python:seq"
    assert body["args"][0] == unpack


def test_tuple_unpack_three_names_preserves_all_targets() -> None:
    source = "def f(triple):\n    a, b, c = triple\n    return c\n"

    result = lift_source(source, "tuple_unpack_three.py")

    contract = _contract(result.ir, ".f")
    body = contract["post"]["args"][1]
    unpack = _unpack_assign(
        "tuple",
        _unpack_targets(_var("a"), _var("b"), _var("c")),
        _var("triple"),
    )
    assert result.refusals == []
    assert contract["effects"] == [{"kind": "panics"}]
    assert _runtime_failure_loci(contract)[0]["argTerm"] == unpack
    assert _runtime_failure_loci(contract)[0]["subkind"] == "iter-unpack"
    assert body["args"][0] == unpack


def test_single_element_tuple_unpack_preserves_one_target() -> None:
    source = "def f(single):\n    (a,) = single\n    return a\n"

    result = lift_source(source, "tuple_unpack_single.py")

    contract = _contract(result.ir, ".f")
    unpack = _unpack_assign("tuple", _unpack_targets(_var("a")), _var("single"))
    assert result.refusals == []
    assert contract["effects"] == [{"kind": "panics"}]
    assert _runtime_failure_loci(contract) == [
        {
            "effectKind": PANIC_FREEDOM_EFFECT_KIND,
            "callee": RUNTIME_FAILURE_SITE_CONCEPT,
            "subkind": "iter-unpack",
            "argTerm": unpack,
            "file": "tuple_unpack_single.py",
            "line": 2,
            "col": 4,
        }
    ]


def test_tuple_unpack_rhs_attribute_composes_attribute_and_unpack_loci() -> None:
    source = "def f(obj):\n    a, b = obj.pair\n    return a\n"

    result = lift_source(source, "tuple_unpack_attr_rhs.py")

    contract = _contract(result.ir, ".f")
    rhs = _attr(_var("obj"), "pair")
    unpack = _unpack_assign("tuple", _unpack_targets(_var("a"), _var("b")), rhs)
    loci = _runtime_failure_loci(contract)
    assert result.refusals == []
    assert contract["effects"] == [{"kind": "panics"}]
    assert [locus["subkind"] for locus in loci] == ["attribute-access", "iter-unpack"]
    assert [locus["argTerm"] for locus in loci] == [rhs, unpack]
    assert [(locus["line"], locus["col"]) for locus in loci] == [(2, 11), (2, 4)]
    assert [locus.get("exceptionClass") for locus in loci] == ["AttributeError", None]


def test_tuple_unpack_rhs_subscript_composes_subscript_and_unpack_loci() -> None:
    source = "def f(xs, key):\n    a, b = xs[key]\n    return b\n"

    result = lift_source(source, "tuple_unpack_subscript_rhs.py")

    contract = _contract(result.ir, ".f")
    rhs = _subscript(_var("xs"), _var("key"))
    unpack = _unpack_assign("tuple", _unpack_targets(_var("a"), _var("b")), rhs)
    loci = _runtime_failure_loci(contract)
    assert result.refusals == []
    assert contract["effects"] == [{"kind": "panics"}]
    assert [locus["subkind"] for locus in loci] == ["subscript-access", "iter-unpack"]
    assert [locus["argTerm"] for locus in loci] == [rhs, unpack]
    assert [(locus["line"], locus["col"]) for locus in loci] == [(2, 11), (2, 4)]


def test_tuple_unpack_rhs_slice_composes_slice_and_unpack_loci() -> None:
    source = "def f(xs, i, j):\n    a, b = xs[i:j]\n    return b\n"

    result = lift_source(source, "tuple_unpack_slice_rhs.py")

    contract = _contract(result.ir, ".f")
    rhs = _subscript(_var("xs"), _slice(_var("i"), _var("j"), _none_const()))
    unpack = _unpack_assign("tuple", _unpack_targets(_var("a"), _var("b")), rhs)
    loci = _runtime_failure_loci(contract)
    assert result.refusals == []
    assert contract["effects"] == [{"kind": "panics"}]
    assert [locus["subkind"] for locus in loci] == ["subscript-access", "iter-unpack"]
    assert [locus["argTerm"] for locus in loci] == [rhs, unpack]
    assert [(locus["line"], locus["col"]) for locus in loci] == [(2, 11), (2, 4)]


@pytest.mark.parametrize(
    "source",
    [
        "def f(pair):\n    a, b = pair\n    return a\n",
        "def f(pair):\n    [a, b] = pair\n    return b\n",
    ],
)
def test_compile_lift_roundtrip_preserves_unpack_assign_body(source: str) -> None:
    lifted = lift_source(source, "roundtrip_unpack.py")
    assert lifted.refusals == []
    contract = _contract(lifted.ir, ".f")
    body = contract["post"]["args"][1]

    compiled = compile_body_term(
        body,
        fn_name="f",
        formals=[str(formal) for formal in contract["formals"]],
    )
    relifted = lift_source(compiled, "roundtrip_unpack.py")
    assert relifted.refusals == []
    relifted_body = _contract(relifted.ir, ".f")["post"]["args"][1]

    assert canonical_json_bytes(relifted_body) == canonical_json_bytes(body)


def test_if_is_none_lifts_to_cf_guarded_option_guards() -> None:
    source = (
        "def f(x):\n"
        "    if x is None:\n"
        "        return 0\n"
        "    else:\n"
        "        return 1\n"
    )

    result = lift_source(source, "none_guard.py")

    body = _contract(result.ir, ".f")["post"]["args"][1]
    assert result.refusals == []
    _assert_none_guarded_if(
        body,
        op="is",
        then_head="is_none",
        else_head="is_some",
    )
    assert "python:compare" in _ctor_names(body)


def test_if_is_not_none_lifts_to_cf_guarded_option_guards() -> None:
    source = (
        "def f(x):\n"
        "    if x is not None:\n"
        "        return 0\n"
        "    else:\n"
        "        return 1\n"
    )

    result = lift_source(source, "some_guard.py")

    body = _contract(result.ir, ".f")["post"]["args"][1]
    assert result.refusals == []
    _assert_none_guarded_if(
        body,
        op="is not",
        then_head="is_some",
        else_head="is_none",
    )
    assert "python:compare" in _ctor_names(body)


def test_simple_dict_literal_lifts_to_ordered_dict_entries() -> None:
    result = lift_source('def f():\n    return {"a": 1, "b": 2}\n', "dict_simple.py")

    assert result.refusals == []
    assert _function_body(result) == _return(
        _dict(
            _dict_entry(_str_const("a"), _int_const(1)),
            _dict_entry(_str_const("b"), _int_const(2)),
        )
    )


def test_dict_literal_with_computed_keys_and_values_lifts_terms() -> None:
    source = "def f(x, y):\n    return {x + 1: y * 2, \"seen\": x}\n"

    result = lift_source(source, "dict_computed.py")

    assert result.refusals == []
    assert _function_body(result) == _return(
        _dict(
            _dict_entry(
                {
                    "kind": "ctor",
                    "name": "python:add",
                    "args": [_var("x"), _int_const(1)],
                },
                {
                    "kind": "ctor",
                    "name": "python:mul",
                    "args": [_var("y"), _int_const(2)],
                },
            ),
            _dict_entry(_str_const("seen"), _var("x")),
        )
    )


def test_dict_literal_with_spread_uses_none_key_sentinel() -> None:
    source = 'def f(base):\n    return {"a": 1, **base, "b": 2}\n'

    result = lift_source(source, "dict_spread.py")

    assert result.refusals == []
    assert _function_body(result) == _return(
        _dict(
            _dict_entry(_str_const("a"), _int_const(1)),
            _dict_entry(_none_const(), _var("base")),
            _dict_entry(_str_const("b"), _int_const(2)),
        )
    )


def test_empty_dict_literal_lifts_to_empty_dict_term() -> None:
    result = lift_source("def f():\n    return {}\n", "dict_empty.py")

    assert result.refusals == []
    assert _function_body(result) == _return(_dict())


def test_dict_floor_discriminates_other_unhandled_expression_kinds() -> None:
    result = lift_source("def f():\n    return {1, 2}\n", "set_literal.py")

    assert [refusal["reason"] for refusal in result.refusals] == [
        "unhandled expression kind: Set"
    ]


def test_dict_roundtrip_is_structurally_stable_and_ordered() -> None:
    term = _dict(
        _dict_entry(_str_const("a"), _int_const(1)),
        _dict_entry(_str_const("b"), _var("x")),
    )

    compiled = compile_body_term(_return(term), formals=["x"])
    relifted = lift_source(compiled, "roundtrip_dict.py")

    assert relifted.refusals == []
    body = _function_body(relifted)
    assert body == _return(term)
    assert cid_of_json(body) == cid_of_json(_return(term))


def test_empty_dict_and_spread_entry_roundtrip_to_distinct_terms() -> None:
    empty = _dict()
    spread = _dict(_dict_entry(_none_const(), _var("base")))

    empty_compiled = compile_body_term(_return(empty))
    spread_compiled = compile_body_term(_return(spread), formals=["base"])
    empty_relifted = lift_source(empty_compiled, "roundtrip_empty_dict.py")
    spread_relifted = lift_source(spread_compiled, "roundtrip_spread_dict.py")

    assert empty_relifted.refusals == []
    assert spread_relifted.refusals == []
    empty_body = _function_body(empty_relifted)
    spread_body = _function_body(spread_relifted)
    assert empty_body == _return(empty)
    assert spread_body == _return(spread)
    assert cid_of_json(empty_body) != cid_of_json(spread_body)


def test_plain_fstring_with_one_interpolation_lifts_to_fstring_term() -> None:
    result = lift_source('def f(x):\n    return f"result: {x}"\n', "fstring_plain.py")

    assert result.refusals == []
    assert _function_body(result) == _return(
        _fstring(_str_const("result: "), _fstring_value(_var("x")))
    )


def test_fstring_multi_part_preserves_constant_and_value_order() -> None:
    source = 'def f(name, count):\n    return f"{name} has {count} items"\n'

    result = lift_source(source, "fstring_multi.py")

    assert result.refusals == []
    assert _function_body(result) == _return(
        _fstring(
            _fstring_value(_var("name")),
            _str_const(" has "),
            _fstring_value(_var("count")),
            _str_const(" items"),
        )
    )


def test_fstring_conversion_is_carried_not_dropped() -> None:
    result = lift_source('def f(x):\n    return f"value={x!r}"\n', "fstring_repr.py")

    assert result.refusals == []
    assert _function_body(result) == _return(
        _fstring(_str_const("value="), _fstring_value(_var("x"), _str_const("r")))
    )


def test_fstring_format_spec_is_carried_as_nested_fstring() -> None:
    result = lift_source('def f(x):\n    return f"{x:02x}"\n', "fstring_format.py")

    assert result.refusals == []
    assert _function_body(result) == _return(
        _fstring(_fstring_value(_var("x"), format_spec=_fstring(_str_const("02x"))))
    )


def test_nested_fstring_in_formatted_value_lifts_recursively() -> None:
    source = 'def f(x):\n    return f"outer {f\'inner {x}\'}"\n'

    result = lift_source(source, "fstring_nested.py")

    assert result.refusals == []
    assert _function_body(result) == _return(
        _fstring(
            _str_const("outer "),
            _fstring_value(
                _fstring(_str_const("inner "), _fstring_value(_var("x")))
            ),
        )
    )


def test_fstring_floor_discriminates_other_unhandled_expression_kinds() -> None:
    result = lift_source("def f(xs):\n    return (x for x in xs)\n", "generator.py")

    assert [refusal["reason"] for refusal in result.refusals] == [
        "unhandled expression kind: GeneratorExp"
    ]


def test_fstring_roundtrip_is_structurally_stable() -> None:
    term = _fstring(
        _str_const("value="),
        _fstring_value(_var("x"), _str_const("r")),
        _str_const(" hex="),
        _fstring_value(_var("y"), format_spec=_fstring(_str_const("02x"))),
    )

    compiled = compile_body_term(_return(term), formals=["x", "y"])
    relifted = lift_source(compiled, "roundtrip_fstring.py")

    assert relifted.refusals == []
    body = _function_body(relifted)
    assert body == _return(term)
    assert cid_of_json(body) == cid_of_json(_return(term))


def test_bare_assert_lifts_to_assert_statement_with_assertion_error_locus() -> None:
    source = "def f(x):\n    assert x\n"

    result = lift_source(source, "assert_bare.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    condition = _var("x")
    assert contract["post"]["args"][1] == _assert_stmt(condition, _none_const())
    assert contract["effects"] == [{"kind": "panics"}]
    assert _runtime_failure_loci(contract) == [
        {
            "effectKind": PANIC_FREEDOM_EFFECT_KIND,
            "callee": RUNTIME_FAILURE_SITE_CONCEPT,
            "subkind": "assert",
            "exceptionClass": "AssertionError",
            "argTerm": condition,
            "file": "assert_bare.py",
            "line": 2,
            "col": 4,
        }
    ]


def test_assert_with_message_lifts_message_term_and_locus_condition() -> None:
    source = 'def f(x):\n    assert x, "must hold"\n'

    result = lift_source(source, "assert_message.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    condition = _var("x")
    assert contract["post"]["args"][1] == _assert_stmt(
        condition, _str_const("must hold")
    )
    assert _runtime_failure_loci(contract)[0]["argTerm"] == condition
    assert _runtime_failure_loci(contract)[0]["exceptionClass"] == "AssertionError"


def test_assert_with_complex_condition_lifts_condition_tree() -> None:
    source = "def f(x, y):\n    assert x < y and y < 10\n"

    result = lift_source(source, "assert_complex.py")

    assert result.refusals == []
    condition = {
        "kind": "ctor",
        "name": "python:and",
        "args": [
            _compare("<", _var("x"), _var("y")),
            _compare("<", _var("y"), _int_const(10)),
        ],
    }
    assert _function_body(result) == _assert_stmt(condition, _none_const())
    assert _runtime_failure_loci(_contract(result.ir, ".f"))[0]["argTerm"] == condition


def test_assert_floor_discriminates_other_unhandled_statement_kinds() -> None:
    result = lift_source("def f(x):\n    del x\n", "delete.py")

    assert [refusal["reason"] for refusal in result.refusals] == [
        "unhandled statement kind: Delete"
    ]


def test_assert_roundtrip_is_structurally_stable() -> None:
    term = _assert_stmt(_var("x"), _str_const("must hold"))

    compiled = compile_body_term(term, formals=["x"])
    relifted = lift_source(compiled, "roundtrip_assert.py")

    assert relifted.refusals == []
    body = _function_body(relifted)
    assert body == term
    assert cid_of_json(body) == cid_of_json(term)


def test_raise_emits_runtime_failure_locus_without_changing_effect_set() -> None:
    source = "def f():\n    raise ValueError\n"

    result = lift_source(source, "raises.py")

    contract = _contract(result.ir, ".f")
    body = contract["post"]["args"][1]
    assert result.refusals == []
    assert body == {
        "kind": "ctor",
        "name": "python:raise",
        "args": [{"kind": "var", "name": "ValueError"}],
    }
    assert contract["effects"] == [{"kind": "panics"}]
    assert _runtime_failure_loci(contract) == [
        {
            "effectKind": PANIC_FREEDOM_EFFECT_KIND,
            "callee": RUNTIME_FAILURE_SITE_CONCEPT,
            "subkind": "explicit-raise",
            "exceptionClass": "ValueError",
            "argTerm": {"kind": "var", "name": "ValueError"},
            "file": "raises.py",
            "line": 2,
            "col": 4,
        }
    ]


def test_multiple_raise_sites_keep_distinct_runtime_failure_loci() -> None:
    source = (
        "def f(flag):\n"
        "    if flag:\n"
        "        raise ValueError\n"
        "    raise RuntimeError\n"
    )

    result = lift_source(source, "multi_raise.py")

    contract = _contract(result.ir, ".f")
    assert result.refusals == []
    assert contract["effects"] == [{"kind": "panics"}]
    loci = _runtime_failure_loci(contract)
    assert [locus["exceptionClass"] for locus in loci] == ["ValueError", "RuntimeError"]
    assert [(locus["line"], locus["col"]) for locus in loci] == [(3, 8), (4, 4)]
    assert all(locus["effectKind"] == PANIC_FREEDOM_EFFECT_KIND for locus in loci)
    assert all(locus["callee"] == RUNTIME_FAILURE_SITE_CONCEPT for locus in loci)
    assert all(locus["subkind"] == "explicit-raise" for locus in loci)


def test_bare_raise_emits_runtime_failure_locus_with_unit_arg() -> None:
    source = "def f():\n    raise\n"

    result = lift_source(source, "bare_raise.py")

    contract = _contract(result.ir, ".f")
    assert result.refusals == []
    assert _runtime_failure_loci(contract) == [
        {
            "effectKind": PANIC_FREEDOM_EFFECT_KIND,
            "callee": RUNTIME_FAILURE_SITE_CONCEPT,
            "subkind": "explicit-raise",
            "argTerm": {
                "kind": "const",
                "value": None,
                "sort": {"kind": "primitive", "name": "Unit"},
            },
            "file": "bare_raise.py",
            "line": 2,
            "col": 4,
        }
    ]


def test_attribute_load_emits_runtime_failure_locus_and_panics_effect() -> None:
    source = "def f(obj):\n    return obj.name\n"

    result = lift_source(source, "attr_access.py")

    contract = _contract(result.ir, ".f")
    assert result.refusals == []
    assert contract["effects"] == [{"kind": "panics"}]
    assert _runtime_failure_loci(contract) == [
        {
            "effectKind": PANIC_FREEDOM_EFFECT_KIND,
            "callee": RUNTIME_FAILURE_SITE_CONCEPT,
            "subkind": "attribute-access",
            "exceptionClass": "AttributeError",
            "argTerm": {
                "kind": "ctor",
                "name": "python:attribute",
                "args": [
                    {"kind": "var", "name": "obj"},
                    {
                        "kind": "const",
                        "value": "name",
                        "sort": {"kind": "primitive", "name": "String"},
                    },
                ],
            },
            "file": "attr_access.py",
            "line": 2,
            "col": 11,
        }
    ]


def test_subscript_load_emits_runtime_failure_locus_and_panics_effect() -> None:
    source = "def f(xs, key):\n    return xs[key]\n"

    result = lift_source(source, "subscript_access.py")

    contract = _contract(result.ir, ".f")
    assert result.refusals == []
    assert contract["effects"] == [{"kind": "panics"}]
    assert _runtime_failure_loci(contract) == [
        {
            "effectKind": PANIC_FREEDOM_EFFECT_KIND,
            "callee": RUNTIME_FAILURE_SITE_CONCEPT,
            "subkind": "subscript-access",
            "argTerm": {
                "kind": "ctor",
                "name": "python:subscript",
                "args": [
                    {"kind": "var", "name": "xs"},
                    {"kind": "var", "name": "key"},
                ],
            },
            "file": "subscript_access.py",
            "line": 2,
            "col": 11,
        }
    ]


def test_slice_load_emits_subscript_access_runtime_failure_locus() -> None:
    source = "def f(xs, a, b):\n    value = xs[a:b]\n    return value\n"

    result = lift_source(source, "slice_access.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    target = _subscript(_var("xs"), _slice(_var("a"), _var("b"), _none_const()))
    body = contract["post"]["args"][1]
    assert contract["effects"] == [{"kind": "panics"}]
    assert _runtime_failure_loci(contract) == [
        {
            "effectKind": PANIC_FREEDOM_EFFECT_KIND,
            "callee": RUNTIME_FAILURE_SITE_CONCEPT,
            "subkind": "subscript-access",
            "argTerm": target,
            "file": "slice_access.py",
            "line": 2,
            "col": 12,
        }
    ]
    assert body["args"][0] == {
        "kind": "ctor",
        "name": "python:assign",
        "args": [_var("value"), target],
    }


@pytest.mark.parametrize(
    ("source_expr", "expected_target"),
    [
        (
            "xs[a:b:c]",
            _subscript(_var("xs"), _slice(_var("a"), _var("b"), _var("c"))),
        ),
        (
            "xs[:b]",
            _subscript(_var("xs"), _slice(_none_const(), _var("b"), _none_const())),
        ),
        (
            "xs[a:]",
            _subscript(_var("xs"), _slice(_var("a"), _none_const(), _none_const())),
        ),
        (
            "xs[:]",
            _subscript(_var("xs"), _slice(_none_const(), _none_const(), _none_const())),
        ),
    ],
)
def test_slice_load_preserves_slice_shape_in_body_and_locus(
    source_expr: str,
    expected_target: dict[str, object],
) -> None:
    source = f"def f(xs, a, b, c):\n    value = {source_expr}\n    return value\n"

    result = lift_source(source, "slice_access_shape.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    loci = _runtime_failure_loci(contract)
    body = contract["post"]["args"][1]
    assert contract["effects"] == [{"kind": "panics"}]
    assert [locus["subkind"] for locus in loci] == ["subscript-access"]
    assert [locus["argTerm"] for locus in loci] == [expected_target]
    assert [(locus["line"], locus["col"]) for locus in loci] == [(2, 12)]
    assert "exceptionClass" not in loci[0]
    assert body["args"][0] == {
        "kind": "ctor",
        "name": "python:assign",
        "args": [_var("value"), expected_target],
    }


def test_nested_slice_load_receiver_emits_intermediate_access_and_slice_access() -> (
    None
):
    source = "def f(obj, a, b):\n    value = obj.inner[a:b]\n    return value\n"

    result = lift_source(source, "nested_slice_access.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    obj_inner = _attr(_var("obj"), "inner")
    target = _subscript(obj_inner, _slice(_var("a"), _var("b"), _none_const()))
    loci = _runtime_failure_loci(contract)
    body = contract["post"]["args"][1]
    assert contract["effects"] == [{"kind": "panics"}]
    assert [locus["subkind"] for locus in loci] == [
        "attribute-access",
        "subscript-access",
    ]
    assert [locus["argTerm"] for locus in loci] == [obj_inner, target]
    assert [(locus["line"], locus["col"]) for locus in loci] == [(2, 12), (2, 12)]
    assert loci[0]["exceptionClass"] == "AttributeError"
    assert "exceptionClass" not in loci[1]
    assert body["args"][0] == {
        "kind": "ctor",
        "name": "python:assign",
        "args": [_var("value"), target],
    }


def test_slice_load_bound_expressions_resurface_load_loci_before_slice_access() -> None:
    source = "def f(xs, obj):\n    value = xs[obj.i:obj.j]\n    return value\n"

    result = lift_source(source, "slice_access_bounds.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    obj_i = _attr(_var("obj"), "i")
    obj_j = _attr(_var("obj"), "j")
    target = _subscript(_var("xs"), _slice(obj_i, obj_j, _none_const()))
    loci = _runtime_failure_loci(contract)
    body = contract["post"]["args"][1]
    assert contract["effects"] == [{"kind": "panics"}]
    assert [locus["subkind"] for locus in loci] == [
        "attribute-access",
        "attribute-access",
        "subscript-access",
    ]
    assert [locus["argTerm"] for locus in loci] == [obj_i, obj_j, target]
    assert [(locus["line"], locus["col"]) for locus in loci] == [
        (2, 15),
        (2, 21),
        (2, 12),
    ]
    assert [locus.get("exceptionClass") for locus in loci] == [
        "AttributeError",
        "AttributeError",
        None,
    ]
    assert body["args"][0] == {
        "kind": "ctor",
        "name": "python:assign",
        "args": [_var("value"), target],
    }


def test_slice_load_receiver_is_evaluated_before_slice_bounds() -> None:
    source = (
        "def f(obj, other):\n"
        "    value = obj.inner[other.i:other.j]\n"
        "    return value\n"
    )

    result = lift_source(source, "slice_access_order.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    obj_inner = _attr(_var("obj"), "inner")
    other_i = _attr(_var("other"), "i")
    other_j = _attr(_var("other"), "j")
    target = _subscript(obj_inner, _slice(other_i, other_j, _none_const()))
    loci = _runtime_failure_loci(contract)
    body = contract["post"]["args"][1]
    assert contract["effects"] == [{"kind": "panics"}]
    assert [locus["subkind"] for locus in loci] == [
        "attribute-access",
        "attribute-access",
        "attribute-access",
        "subscript-access",
    ]
    assert [locus["argTerm"] for locus in loci] == [
        obj_inner,
        other_i,
        other_j,
        target,
    ]
    assert [(locus["line"], locus["col"]) for locus in loci] == [
        (2, 12),
        (2, 22),
        (2, 30),
        (2, 12),
    ]
    assert body["args"][0] == {
        "kind": "ctor",
        "name": "python:assign",
        "args": [_var("value"), target],
    }


@pytest.mark.parametrize(
    "source",
    [
        "def f(xs, a, b):\n    value = xs[a:b]\n    return value\n",
        "def f(xs, a, b):\n    lower = xs[:b]\n    upper = xs[a:]\n    all_items = xs[:]\n    return all_items\n",
        "def f(xs, a, b, c):\n    value = xs[a:b:c]\n    return value\n",
    ],
)
def test_compile_lift_roundtrip_preserves_slice_load_body(source: str) -> None:
    lifted = lift_source(source, "roundtrip_slice_access.py")
    assert lifted.refusals == []
    contract = _contract(lifted.ir, ".f")
    body = contract["post"]["args"][1]

    compiled = compile_body_term(
        body,
        fn_name="f",
        formals=[str(formal) for formal in contract["formals"]],
    )
    relifted = lift_source(compiled, "roundtrip_slice_access.py")
    assert relifted.refusals == []
    relifted_body = _contract(relifted.ir, ".f")["post"]["args"][1]

    assert canonical_json_bytes(relifted_body) == canonical_json_bytes(body)


def test_mixed_runtime_failure_sites_share_deduped_panics_effect() -> None:
    source = (
        "def f(obj, xs, key):\n"
        "    a = obj.name\n"
        "    b = xs[key]\n"
        "    raise RuntimeError\n"
    )

    result = lift_source(source, "mixed_runtime.py")

    contract = _contract(result.ir, ".f")
    loci = _runtime_failure_loci(contract)
    assert result.refusals == []
    assert contract["effects"] == [{"kind": "panics"}]
    assert [locus["subkind"] for locus in loci] == [
        "attribute-access",
        "subscript-access",
        "explicit-raise",
    ]
    assert [(locus["line"], locus["col"]) for locus in loci] == [(2, 8), (3, 8), (4, 4)]


def test_attribute_and_subscript_store_targets_emit_runtime_failure_loci() -> None:
    source = (
        "def f(obj, xs, key, value):\n"
        "    obj.name = value\n"
        "    xs[key] = value\n"
        "    return value\n"
    )

    result = lift_source(source, "store_targets.py")

    contract = _contract(result.ir, ".f")
    assert result.refusals == []
    assert contract["effects"] == [
        {"kind": "writes", "target": "obj.name"},
        {"kind": "writes", "target": "xs[key]"},
        {"kind": "panics"},
    ]
    assert _runtime_failure_loci(contract) == [
        {
            "effectKind": PANIC_FREEDOM_EFFECT_KIND,
            "callee": RUNTIME_FAILURE_SITE_CONCEPT,
            "subkind": "attribute-write",
            "exceptionClass": "AttributeError",
            "argTerm": {
                "kind": "ctor",
                "name": "python:attribute",
                "args": [
                    {"kind": "var", "name": "obj"},
                    {
                        "kind": "const",
                        "value": "name",
                        "sort": {"kind": "primitive", "name": "String"},
                    },
                ],
            },
            "file": "store_targets.py",
            "line": 2,
            "col": 4,
        },
        {
            "effectKind": PANIC_FREEDOM_EFFECT_KIND,
            "callee": RUNTIME_FAILURE_SITE_CONCEPT,
            "subkind": "subscript-write",
            "argTerm": {
                "kind": "ctor",
                "name": "python:subscript",
                "args": [
                    {"kind": "var", "name": "xs"},
                    {"kind": "var", "name": "key"},
                ],
            },
            "file": "store_targets.py",
            "line": 3,
            "col": 4,
        },
    ]


def test_nested_attribute_and_subscript_store_targets_resurface_load_loci() -> None:
    source = (
        "def f(obj, xs, ys, i, value):\n"
        "    obj.inner.name = value\n"
        "    xs[ys[i]] = value\n"
        "    return value\n"
    )

    result = lift_source(source, "nested_store_targets.py")

    contract = _contract(result.ir, ".f")
    assert result.refusals == []
    assert contract["effects"] == [
        {"kind": "writes", "target": "obj.inner.name"},
        {"kind": "writes", "target": "xs[ys[i]]"},
        {"kind": "panics"},
    ]
    assert _runtime_failure_loci(contract) == [
        {
            "effectKind": PANIC_FREEDOM_EFFECT_KIND,
            "callee": RUNTIME_FAILURE_SITE_CONCEPT,
            "subkind": "attribute-access",
            "exceptionClass": "AttributeError",
            "argTerm": {
                "kind": "ctor",
                "name": "python:attribute",
                "args": [
                    {"kind": "var", "name": "obj"},
                    {
                        "kind": "const",
                        "value": "inner",
                        "sort": {"kind": "primitive", "name": "String"},
                    },
                ],
            },
            "file": "nested_store_targets.py",
            "line": 2,
            "col": 4,
        },
        {
            "effectKind": PANIC_FREEDOM_EFFECT_KIND,
            "callee": RUNTIME_FAILURE_SITE_CONCEPT,
            "subkind": "attribute-write",
            "exceptionClass": "AttributeError",
            "argTerm": {
                "kind": "ctor",
                "name": "python:attribute",
                "args": [
                    {
                        "kind": "ctor",
                        "name": "python:attribute",
                        "args": [
                            {"kind": "var", "name": "obj"},
                            {
                                "kind": "const",
                                "value": "inner",
                                "sort": {"kind": "primitive", "name": "String"},
                            },
                        ],
                    },
                    {
                        "kind": "const",
                        "value": "name",
                        "sort": {"kind": "primitive", "name": "String"},
                    },
                ],
            },
            "file": "nested_store_targets.py",
            "line": 2,
            "col": 4,
        },
        {
            "effectKind": PANIC_FREEDOM_EFFECT_KIND,
            "callee": RUNTIME_FAILURE_SITE_CONCEPT,
            "subkind": "subscript-access",
            "argTerm": {
                "kind": "ctor",
                "name": "python:subscript",
                "args": [
                    {"kind": "var", "name": "ys"},
                    {"kind": "var", "name": "i"},
                ],
            },
            "file": "nested_store_targets.py",
            "line": 3,
            "col": 7,
        },
        {
            "effectKind": PANIC_FREEDOM_EFFECT_KIND,
            "callee": RUNTIME_FAILURE_SITE_CONCEPT,
            "subkind": "subscript-write",
            "argTerm": {
                "kind": "ctor",
                "name": "python:subscript",
                "args": [
                    {"kind": "var", "name": "xs"},
                    {
                        "kind": "ctor",
                        "name": "python:subscript",
                        "args": [
                            {"kind": "var", "name": "ys"},
                            {"kind": "var", "name": "i"},
                        ],
                    },
                ],
            },
            "file": "nested_store_targets.py",
            "line": 3,
            "col": 4,
        },
    ]


def test_slice_assign_emits_subscript_write_runtime_failure_locus() -> None:
    source = "def f(xs, a, b, value):\n    xs[a:b] = value\n    return xs\n"

    result = lift_source(source, "slice_assign.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    target = _subscript(_var("xs"), _slice(_var("a"), _var("b"), _none_const()))
    body = contract["post"]["args"][1]
    assert contract["effects"] == [
        {"kind": "writes", "target": "xs[a:b]"},
        {"kind": "panics"},
    ]
    assert _runtime_failure_loci(contract) == [
        {
            "effectKind": PANIC_FREEDOM_EFFECT_KIND,
            "callee": RUNTIME_FAILURE_SITE_CONCEPT,
            "subkind": "subscript-write",
            "argTerm": target,
            "file": "slice_assign.py",
            "line": 2,
            "col": 4,
        }
    ]
    assert body["args"][0] == {
        "kind": "ctor",
        "name": "python:assign",
        "args": [target, _var("value")],
    }


@pytest.mark.parametrize(
    ("source_target", "expected_target", "expected_write"),
    [
        (
            "xs[a:b:c]",
            _subscript(_var("xs"), _slice(_var("a"), _var("b"), _var("c"))),
            "xs[a:b:c]",
        ),
        (
            "xs[:b]",
            _subscript(_var("xs"), _slice(_none_const(), _var("b"), _none_const())),
            "xs[:b]",
        ),
        (
            "xs[a:]",
            _subscript(_var("xs"), _slice(_var("a"), _none_const(), _none_const())),
            "xs[a:]",
        ),
        (
            "xs[:]",
            _subscript(_var("xs"), _slice(_none_const(), _none_const(), _none_const())),
            "xs[:]",
        ),
    ],
)
def test_slice_assign_preserves_slice_shape_in_body_and_locus(
    source_target: str,
    expected_target: dict[str, object],
    expected_write: str,
) -> None:
    source = f"def f(xs, a, b, c, value):\n    {source_target} = value\n    return xs\n"

    result = lift_source(source, "slice_assign_shape.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    loci = _runtime_failure_loci(contract)
    body = contract["post"]["args"][1]
    assert contract["effects"] == [
        {"kind": "writes", "target": expected_write},
        {"kind": "panics"},
    ]
    assert [locus["subkind"] for locus in loci] == ["subscript-write"]
    assert [locus["argTerm"] for locus in loci] == [expected_target]
    assert [(locus["line"], locus["col"]) for locus in loci] == [(2, 4)]
    assert "exceptionClass" not in loci[0]
    assert body["args"][0] == {
        "kind": "ctor",
        "name": "python:assign",
        "args": [expected_target, _var("value")],
    }


def test_nested_slice_assign_receiver_emits_intermediate_access_and_slice_write() -> (
    None
):
    source = "def f(obj, a, b, value):\n    obj.inner[a:b] = value\n    return obj\n"

    result = lift_source(source, "nested_slice_assign.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    obj_inner = _attr(_var("obj"), "inner")
    target = _subscript(obj_inner, _slice(_var("a"), _var("b"), _none_const()))
    loci = _runtime_failure_loci(contract)
    body = contract["post"]["args"][1]
    assert contract["effects"] == [
        {"kind": "writes", "target": "obj.inner[a:b]"},
        {"kind": "panics"},
    ]
    assert [locus["subkind"] for locus in loci] == [
        "attribute-access",
        "subscript-write",
    ]
    assert [locus["argTerm"] for locus in loci] == [obj_inner, target]
    assert [(locus["line"], locus["col"]) for locus in loci] == [(2, 4), (2, 4)]
    assert loci[0]["exceptionClass"] == "AttributeError"
    assert "exceptionClass" not in loci[1]
    assert body["args"][0] == {
        "kind": "ctor",
        "name": "python:assign",
        "args": [target, _var("value")],
    }


def test_slice_assign_bound_expressions_resurface_load_loci_before_slice_write() -> (
    None
):
    source = "def f(xs, obj, value):\n    xs[obj.i:obj.j] = value\n    return xs\n"

    result = lift_source(source, "slice_assign_bounds.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    obj_i = _attr(_var("obj"), "i")
    obj_j = _attr(_var("obj"), "j")
    target = _subscript(_var("xs"), _slice(obj_i, obj_j, _none_const()))
    loci = _runtime_failure_loci(contract)
    body = contract["post"]["args"][1]
    assert contract["effects"] == [
        {"kind": "writes", "target": "xs[obj.i:obj.j]"},
        {"kind": "panics"},
    ]
    assert [locus["subkind"] for locus in loci] == [
        "attribute-access",
        "attribute-access",
        "subscript-write",
    ]
    assert [locus["argTerm"] for locus in loci] == [obj_i, obj_j, target]
    assert [(locus["line"], locus["col"]) for locus in loci] == [
        (2, 7),
        (2, 13),
        (2, 4),
    ]
    assert [locus.get("exceptionClass") for locus in loci] == [
        "AttributeError",
        "AttributeError",
        None,
    ]
    assert body["args"][0] == {
        "kind": "ctor",
        "name": "python:assign",
        "args": [target, _var("value")],
    }


@pytest.mark.parametrize(
    "source",
    [
        "def f(xs, a, b, value):\n    xs[a:b] = value\n    return xs\n",
        "def f(xs, a, b, value):\n    xs[:b] = value\n    xs[a:] = value\n    xs[:] = value\n    return xs\n",
        "def f(xs, a, b, c, value):\n    xs[a:b:c] = value\n    return xs\n",
    ],
)
def test_compile_lift_roundtrip_preserves_slice_assign_body(source: str) -> None:
    lifted = lift_source(source, "roundtrip_slice_assign.py")
    assert lifted.refusals == []
    contract = _contract(lifted.ir, ".f")
    body = contract["post"]["args"][1]

    compiled = compile_body_term(
        body,
        fn_name="f",
        formals=[str(formal) for formal in contract["formals"]],
    )
    relifted = lift_source(compiled, "roundtrip_slice_assign.py")
    assert relifted.refusals == []
    relifted_body = _contract(relifted.ir, ".f")["post"]["args"][1]

    assert canonical_json_bytes(relifted_body) == canonical_json_bytes(body)


def test_name_augassign_lifts_to_aug_assign_without_runtime_failure_loci() -> None:
    source = "def f(x, y):\n    x += y\n    return x\n"

    result = lift_source(source, "name_augassign.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    body = contract["post"]["args"][1]
    assert contract["effects"] == []
    assert contract.get("panicLoci", []) == []
    assert body["name"] == "python:seq"
    assert body["args"][0] == _aug_assign(_var("x"), "python:add", _var("y"))


def test_attribute_augassign_emits_access_and_write_runtime_failure_loci() -> None:
    source = "def f(obj, y):\n    obj.name += y\n    return obj\n"

    result = lift_source(source, "attribute_augassign.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    target = _attr(_var("obj"), "name")
    loci = _runtime_failure_loci(contract)
    body = contract["post"]["args"][1]
    assert contract["effects"] == [
        {"kind": "writes", "target": "obj.name"},
        {"kind": "panics"},
    ]
    assert [locus["subkind"] for locus in loci] == [
        "attribute-access",
        "attribute-write",
    ]
    assert [locus["argTerm"] for locus in loci] == [target, target]
    assert [(locus["line"], locus["col"]) for locus in loci] == [(2, 4), (2, 4)]
    assert all(locus["exceptionClass"] == "AttributeError" for locus in loci)
    assert body["args"][0] == _aug_assign(target, "python:add", _var("y"))


def test_subscript_augassign_emits_access_and_write_runtime_failure_loci() -> None:
    source = "def f(xs, key, y):\n    xs[key] += y\n    return xs\n"

    result = lift_source(source, "subscript_augassign.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    target = _subscript(_var("xs"), _var("key"))
    loci = _runtime_failure_loci(contract)
    body = contract["post"]["args"][1]
    assert contract["effects"] == [
        {"kind": "writes", "target": "xs[key]"},
        {"kind": "panics"},
    ]
    assert [locus["subkind"] for locus in loci] == [
        "subscript-access",
        "subscript-write",
    ]
    assert [locus["argTerm"] for locus in loci] == [target, target]
    assert [(locus["line"], locus["col"]) for locus in loci] == [(2, 4), (2, 4)]
    assert "exceptionClass" not in loci[0]
    assert "exceptionClass" not in loci[1]
    assert body["args"][0] == _aug_assign(target, "python:add", _var("y"))


def test_slice_augassign_emits_access_and_write_runtime_failure_loci() -> None:
    source = "def f(xs, a, b, value):\n    xs[a:b] += value\n    return xs\n"

    result = lift_source(source, "slice_augassign.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    target = _subscript(_var("xs"), _slice(_var("a"), _var("b"), _none_const()))
    loci = _runtime_failure_loci(contract)
    body = contract["post"]["args"][1]
    assert contract["effects"] == [
        {"kind": "writes", "target": "xs[a:b]"},
        {"kind": "panics"},
    ]
    assert [locus["subkind"] for locus in loci] == [
        "subscript-access",
        "subscript-write",
    ]
    assert [locus["argTerm"] for locus in loci] == [target, target]
    assert [(locus["line"], locus["col"]) for locus in loci] == [(2, 4), (2, 4)]
    assert "exceptionClass" not in loci[0]
    assert "exceptionClass" not in loci[1]
    assert body["args"][0] == _aug_assign(target, "python:add", _var("value"))


@pytest.mark.parametrize(
    ("source_target", "expected_target", "expected_write"),
    [
        (
            "xs[a:b:c]",
            _subscript(_var("xs"), _slice(_var("a"), _var("b"), _var("c"))),
            "xs[a:b:c]",
        ),
        (
            "xs[:b]",
            _subscript(_var("xs"), _slice(_none_const(), _var("b"), _none_const())),
            "xs[:b]",
        ),
        (
            "xs[a:]",
            _subscript(_var("xs"), _slice(_var("a"), _none_const(), _none_const())),
            "xs[a:]",
        ),
        (
            "xs[:]",
            _subscript(_var("xs"), _slice(_none_const(), _none_const(), _none_const())),
            "xs[:]",
        ),
    ],
)
def test_slice_augassign_preserves_slice_shape_in_body_and_locus(
    source_target: str,
    expected_target: dict[str, object],
    expected_write: str,
) -> None:
    source = (
        f"def f(xs, a, b, c, value):\n    {source_target} += value\n    return xs\n"
    )

    result = lift_source(source, "slice_augassign_shape.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    loci = _runtime_failure_loci(contract)
    body = contract["post"]["args"][1]
    assert contract["effects"] == [
        {"kind": "writes", "target": expected_write},
        {"kind": "panics"},
    ]
    assert [locus["subkind"] for locus in loci] == [
        "subscript-access",
        "subscript-write",
    ]
    assert [locus["argTerm"] for locus in loci] == [expected_target, expected_target]
    assert [(locus["line"], locus["col"]) for locus in loci] == [(2, 4), (2, 4)]
    assert "exceptionClass" not in loci[0]
    assert "exceptionClass" not in loci[1]
    assert body["args"][0] == _aug_assign(expected_target, "python:add", _var("value"))


def test_nested_slice_augassign_receiver_emits_intermediate_access_and_slice_loci() -> (
    None
):
    source = "def f(obj, a, b, value):\n    obj.inner[a:b] += value\n    return obj\n"

    result = lift_source(source, "nested_slice_augassign.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    obj_inner = _attr(_var("obj"), "inner")
    target = _subscript(obj_inner, _slice(_var("a"), _var("b"), _none_const()))
    loci = _runtime_failure_loci(contract)
    body = contract["post"]["args"][1]
    assert contract["effects"] == [
        {"kind": "writes", "target": "obj.inner[a:b]"},
        {"kind": "panics"},
    ]
    assert [locus["subkind"] for locus in loci] == [
        "attribute-access",
        "subscript-access",
        "subscript-write",
    ]
    assert [locus["argTerm"] for locus in loci] == [obj_inner, target, target]
    assert [(locus["line"], locus["col"]) for locus in loci] == [(2, 4), (2, 4), (2, 4)]
    assert loci[0]["exceptionClass"] == "AttributeError"
    assert "exceptionClass" not in loci[1]
    assert "exceptionClass" not in loci[2]
    assert body["args"][0] == _aug_assign(target, "python:add", _var("value"))


def test_slice_augassign_bound_expressions_resurface_load_loci_before_slice_loci() -> (
    None
):
    source = "def f(xs, obj, value):\n    xs[obj.i:obj.j] += value\n    return xs\n"

    result = lift_source(source, "slice_augassign_bounds.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    obj_i = _attr(_var("obj"), "i")
    obj_j = _attr(_var("obj"), "j")
    target = _subscript(_var("xs"), _slice(obj_i, obj_j, _none_const()))
    loci = _runtime_failure_loci(contract)
    body = contract["post"]["args"][1]
    assert contract["effects"] == [
        {"kind": "writes", "target": "xs[obj.i:obj.j]"},
        {"kind": "panics"},
    ]
    assert [locus["subkind"] for locus in loci] == [
        "attribute-access",
        "attribute-access",
        "subscript-access",
        "subscript-write",
    ]
    assert [locus["argTerm"] for locus in loci] == [obj_i, obj_j, target, target]
    assert [(locus["line"], locus["col"]) for locus in loci] == [
        (2, 7),
        (2, 13),
        (2, 4),
        (2, 4),
    ]
    assert [locus.get("exceptionClass") for locus in loci] == [
        "AttributeError",
        "AttributeError",
        None,
        None,
    ]
    assert body["args"][0] == _aug_assign(target, "python:add", _var("value"))


def test_slice_augassign_receiver_is_evaluated_before_slice_bounds() -> None:
    source = (
        "def f(obj, other, value):\n"
        "    obj.inner[other.i:other.j] += value\n"
        "    return obj\n"
    )

    result = lift_source(source, "slice_augassign_order.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    obj_inner = _attr(_var("obj"), "inner")
    other_i = _attr(_var("other"), "i")
    other_j = _attr(_var("other"), "j")
    target = _subscript(obj_inner, _slice(other_i, other_j, _none_const()))
    loci = _runtime_failure_loci(contract)
    body = contract["post"]["args"][1]
    assert contract["effects"] == [
        {"kind": "writes", "target": "obj.inner[other.i:other.j]"},
        {"kind": "panics"},
    ]
    assert [locus["subkind"] for locus in loci] == [
        "attribute-access",
        "attribute-access",
        "attribute-access",
        "subscript-access",
        "subscript-write",
    ]
    assert [locus["argTerm"] for locus in loci] == [
        obj_inner,
        other_i,
        other_j,
        target,
        target,
    ]
    assert [(locus["line"], locus["col"]) for locus in loci] == [
        (2, 4),
        (2, 14),
        (2, 22),
        (2, 4),
        (2, 4),
    ]
    assert body["args"][0] == _aug_assign(target, "python:add", _var("value"))


@pytest.mark.parametrize(
    "source",
    [
        "def f(xs, a, b, value):\n    xs[a:b] += value\n    return xs\n",
        "def f(xs, a, b, value):\n    xs[:b] += value\n    xs[a:] += value\n    xs[:] += value\n    return xs\n",
        "def f(xs, a, b, c, value):\n    xs[a:b:c] += value\n    return xs\n",
    ],
)
def test_compile_lift_roundtrip_preserves_slice_augassign_body(source: str) -> None:
    lifted = lift_source(source, "roundtrip_slice_augassign.py")
    assert lifted.refusals == []
    contract = _contract(lifted.ir, ".f")
    body = contract["post"]["args"][1]

    compiled = compile_body_term(
        body,
        fn_name="f",
        formals=[str(formal) for formal in contract["formals"]],
    )
    relifted = lift_source(compiled, "roundtrip_slice_augassign.py")
    assert relifted.refusals == []
    relifted_body = _contract(relifted.ir, ".f")["post"]["args"][1]

    assert canonical_json_bytes(relifted_body) == canonical_json_bytes(body)


def test_nested_augassign_targets_evaluate_navigation_once() -> None:
    source = (
        "def f(obj, xs, ys, i, y):\n"
        "    obj.inner.name += y\n"
        "    xs[ys[i]] += y\n"
        "    return y\n"
    )

    result = lift_source(source, "nested_augassign.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    loci = _runtime_failure_loci(contract)
    obj_inner = _attr(_var("obj"), "inner")
    obj_inner_name = _attr(obj_inner, "name")
    ys_i = _subscript(_var("ys"), _var("i"))
    xs_ys_i = _subscript(_var("xs"), ys_i)
    assert contract["effects"] == [
        {"kind": "writes", "target": "obj.inner.name"},
        {"kind": "writes", "target": "xs[ys[i]]"},
        {"kind": "panics"},
    ]
    assert [locus["subkind"] for locus in loci] == [
        "attribute-access",
        "attribute-access",
        "attribute-write",
        "subscript-access",
        "subscript-access",
        "subscript-write",
    ]
    assert [locus["argTerm"] for locus in loci] == [
        obj_inner,
        obj_inner_name,
        obj_inner_name,
        ys_i,
        xs_ys_i,
        xs_ys_i,
    ]
    assert [(locus["line"], locus["col"]) for locus in loci] == [
        (2, 4),
        (2, 4),
        (2, 4),
        (3, 7),
        (3, 4),
        (3, 4),
    ]
    assert [locus["argTerm"] for locus in loci].count(obj_inner) == 1
    assert [locus["argTerm"] for locus in loci].count(ys_i) == 1


def test_augassign_complex_rhs_emits_rhs_load_loci_after_target_loci() -> None:
    source = "def f(obj, xs, key):\n    obj.name += xs[key]\n    return obj\n"

    result = lift_source(source, "augassign_rhs.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    obj_name = _attr(_var("obj"), "name")
    xs_key = _subscript(_var("xs"), _var("key"))
    loci = _runtime_failure_loci(contract)
    assert contract["effects"] == [
        {"kind": "writes", "target": "obj.name"},
        {"kind": "panics"},
    ]
    assert [locus["subkind"] for locus in loci] == [
        "attribute-access",
        "attribute-write",
        "subscript-access",
    ]
    assert [locus["argTerm"] for locus in loci] == [obj_name, obj_name, xs_key]
    assert [(locus["line"], locus["col"]) for locus in loci] == [
        (2, 4),
        (2, 4),
        (2, 16),
    ]


def test_compile_lift_roundtrip_preserves_attribute_augassign_body() -> None:
    source = "def f(obj, y):\n    obj.name += y\n    return obj\n"
    lifted = lift_source(source, "roundtrip_aug_attr.py")
    assert lifted.refusals == []
    contract = _contract(lifted.ir, ".f")
    body = contract["post"]["args"][1]

    compiled = compile_body_term(
        body,
        fn_name="f",
        formals=[str(formal) for formal in contract["formals"]],
    )
    relifted = lift_source(compiled, "roundtrip_aug_attr.py")
    assert relifted.refusals == []
    relifted_body = _contract(relifted.ir, ".f")["post"]["args"][1]

    assert canonical_json_bytes(relifted_body) == canonical_json_bytes(body)


def test_compile_lift_roundtrip_preserves_subscript_augassign_body() -> None:
    source = "def f(xs, key, y):\n    xs[key] += y\n    return xs\n"
    lifted = lift_source(source, "roundtrip_aug_subscript.py")
    assert lifted.refusals == []
    contract = _contract(lifted.ir, ".f")
    body = contract["post"]["args"][1]

    compiled = compile_body_term(
        body,
        fn_name="f",
        formals=[str(formal) for formal in contract["formals"]],
    )
    relifted = lift_source(compiled, "roundtrip_aug_subscript.py")
    assert relifted.refusals == []
    relifted_body = _contract(relifted.ir, ".f")["post"]["args"][1]

    assert canonical_json_bytes(relifted_body) == canonical_json_bytes(body)


def test_name_annassign_without_value_has_no_runtime_failure_loci_or_effects() -> None:
    source = "def f():\n    x: int\n    return 0\n"

    result = lift_source(source, "name_annassign_no_value.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    body = contract["post"]["args"][1]
    assert contract["effects"] == []
    assert contract.get("panicLoci", []) == []
    assert body["name"] == "python:seq"
    assert body["args"][0] == _ann_assign(_var("x"), _var("int"), _no_value())


def test_name_annassign_with_value_has_no_runtime_failure_loci_or_effects() -> None:
    source = "def f(y):\n    x: int = y\n    return x\n"

    result = lift_source(source, "name_annassign_value.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    body = contract["post"]["args"][1]
    assert contract["effects"] == []
    assert contract.get("panicLoci", []) == []
    assert body["args"][0] == _ann_assign(_var("x"), _var("int"), _var("y"))


def test_direct_attribute_annassign_without_value_does_not_access_final_attribute() -> (
    None
):
    source = "def f(obj):\n    obj.name: int\n    return obj\n"

    result = lift_source(source, "attr_annassign_no_value.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    body = contract["post"]["args"][1]
    target = _attr(_var("obj"), "name")
    assert contract["effects"] == []
    assert contract.get("panicLoci", []) == []
    assert body["args"][0] == _ann_assign(target, _var("int"), _no_value())


def test_direct_attribute_annassign_with_value_emits_store_write_locus_only() -> None:
    source = "def f(obj, y):\n    obj.name: int = y\n    return obj\n"

    result = lift_source(source, "attr_annassign_value.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    target = _attr(_var("obj"), "name")
    loci = _runtime_failure_loci(contract)
    body = contract["post"]["args"][1]
    assert contract["effects"] == [
        {"kind": "writes", "target": "obj.name"},
        {"kind": "panics"},
    ]
    assert [locus["subkind"] for locus in loci] == ["attribute-write"]
    assert [locus["argTerm"] for locus in loci] == [target]
    assert [(locus["line"], locus["col"]) for locus in loci] == [(2, 4)]
    assert loci[0]["exceptionClass"] == "AttributeError"
    assert body["args"][0] == _ann_assign(target, _var("int"), _var("y"))


def test_direct_subscript_annassign_without_value_does_not_access_final_subscript() -> (
    None
):
    source = "def f(xs, key):\n    xs[key]: int\n    return xs\n"

    result = lift_source(source, "subscript_annassign_no_value.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    body = contract["post"]["args"][1]
    target = _subscript(_var("xs"), _var("key"))
    assert contract["effects"] == []
    assert contract.get("panicLoci", []) == []
    assert body["args"][0] == _ann_assign(target, _var("int"), _no_value())


def test_direct_subscript_annassign_with_value_emits_store_write_locus_only() -> None:
    source = "def f(xs, key, y):\n    xs[key]: int = y\n    return xs\n"

    result = lift_source(source, "subscript_annassign_value.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    target = _subscript(_var("xs"), _var("key"))
    loci = _runtime_failure_loci(contract)
    body = contract["post"]["args"][1]
    assert contract["effects"] == [
        {"kind": "writes", "target": "xs[key]"},
        {"kind": "panics"},
    ]
    assert [locus["subkind"] for locus in loci] == ["subscript-write"]
    assert [locus["argTerm"] for locus in loci] == [target]
    assert [(locus["line"], locus["col"]) for locus in loci] == [(2, 4)]
    assert "exceptionClass" not in loci[0]
    assert body["args"][0] == _ann_assign(target, _var("int"), _var("y"))


def test_direct_slice_annassign_without_value_does_not_access_final_subscript() -> None:
    source = "def f(xs, a, b):\n    xs[a:b]: int\n    return xs\n"

    result = lift_source(source, "slice_annassign_no_value.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    body = contract["post"]["args"][1]
    target = _subscript(_var("xs"), _slice(_var("a"), _var("b"), _none_const()))
    assert contract["effects"] == []
    assert contract.get("panicLoci", []) == []
    assert body["args"][0] == _ann_assign(target, _var("int"), _no_value())


def test_direct_slice_annassign_with_value_emits_store_write_locus_only() -> None:
    source = "def f(xs, a, b, value):\n    xs[a:b]: int = value\n    return xs\n"

    result = lift_source(source, "slice_annassign_value.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    target = _subscript(_var("xs"), _slice(_var("a"), _var("b"), _none_const()))
    loci = _runtime_failure_loci(contract)
    body = contract["post"]["args"][1]
    assert contract["effects"] == [
        {"kind": "writes", "target": "xs[a:b]"},
        {"kind": "panics"},
    ]
    assert [locus["subkind"] for locus in loci] == ["subscript-write"]
    assert [locus["argTerm"] for locus in loci] == [target]
    assert [(locus["line"], locus["col"]) for locus in loci] == [(2, 4)]
    assert "exceptionClass" not in loci[0]
    assert body["args"][0] == _ann_assign(target, _var("int"), _var("value"))


@pytest.mark.parametrize(
    ("source_target", "expected_target", "expected_write"),
    [
        (
            "xs[a:b:c]",
            _subscript(_var("xs"), _slice(_var("a"), _var("b"), _var("c"))),
            "xs[a:b:c]",
        ),
        (
            "xs[:b]",
            _subscript(_var("xs"), _slice(_none_const(), _var("b"), _none_const())),
            "xs[:b]",
        ),
        (
            "xs[a:]",
            _subscript(_var("xs"), _slice(_var("a"), _none_const(), _none_const())),
            "xs[a:]",
        ),
        (
            "xs[:]",
            _subscript(_var("xs"), _slice(_none_const(), _none_const(), _none_const())),
            "xs[:]",
        ),
    ],
)
def test_slice_annassign_preserves_slice_shape_with_and_without_value(
    source_target: str,
    expected_target: dict[str, object],
    expected_write: str,
) -> None:
    no_value_source = f"def f(xs, a, b, c):\n    {source_target}: int\n    return xs\n"
    with_value_source = (
        f"def f(xs, a, b, c, value):\n    {source_target}: int = value\n    return xs\n"
    )

    no_value = lift_source(no_value_source, "slice_annassign_shape_no_value.py")
    with_value = lift_source(with_value_source, "slice_annassign_shape_value.py")

    assert no_value.refusals == []
    no_value_contract = _contract(no_value.ir, ".f")
    no_value_body = no_value_contract["post"]["args"][1]
    assert no_value_contract["effects"] == []
    assert no_value_contract.get("panicLoci", []) == []
    assert no_value_body["args"][0] == _ann_assign(
        expected_target, _var("int"), _no_value()
    )

    assert with_value.refusals == []
    with_value_contract = _contract(with_value.ir, ".f")
    with_value_loci = _runtime_failure_loci(with_value_contract)
    with_value_body = with_value_contract["post"]["args"][1]
    assert with_value_contract["effects"] == [
        {"kind": "writes", "target": expected_write},
        {"kind": "panics"},
    ]
    assert [locus["subkind"] for locus in with_value_loci] == ["subscript-write"]
    assert [locus["argTerm"] for locus in with_value_loci] == [expected_target]
    assert [(locus["line"], locus["col"]) for locus in with_value_loci] == [(2, 4)]
    assert with_value_body["args"][0] == _ann_assign(
        expected_target, _var("int"), _var("value")
    )


def test_nested_slice_annassign_without_value_emits_only_intermediate_receiver_locus() -> (
    None
):
    source = "def f(obj, a, b):\n    obj.inner[a:b]: int\n    return obj\n"

    result = lift_source(source, "nested_slice_annassign_no_value.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    obj_inner = _attr(_var("obj"), "inner")
    target = _subscript(obj_inner, _slice(_var("a"), _var("b"), _none_const()))
    loci = _runtime_failure_loci(contract)
    body = contract["post"]["args"][1]
    assert contract["effects"] == [{"kind": "panics"}]
    assert [locus["subkind"] for locus in loci] == ["attribute-access"]
    assert [locus["argTerm"] for locus in loci] == [obj_inner]
    assert [(locus["line"], locus["col"]) for locus in loci] == [(2, 4)]
    assert loci[0]["exceptionClass"] == "AttributeError"
    assert body["args"][0] == _ann_assign(target, _var("int"), _no_value())


def test_nested_slice_annassign_with_value_reuses_store_target_navigation_once() -> (
    None
):
    source = (
        "def f(obj, a, b, value):\n    obj.inner[a:b]: int = value\n    return obj\n"
    )

    result = lift_source(source, "nested_slice_annassign_value.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    obj_inner = _attr(_var("obj"), "inner")
    target = _subscript(obj_inner, _slice(_var("a"), _var("b"), _none_const()))
    loci = _runtime_failure_loci(contract)
    body = contract["post"]["args"][1]
    assert contract["effects"] == [
        {"kind": "writes", "target": "obj.inner[a:b]"},
        {"kind": "panics"},
    ]
    assert [locus["subkind"] for locus in loci] == [
        "attribute-access",
        "subscript-write",
    ]
    assert [locus["argTerm"] for locus in loci] == [obj_inner, target]
    assert [(locus["line"], locus["col"]) for locus in loci] == [(2, 4), (2, 4)]
    assert loci[0]["exceptionClass"] == "AttributeError"
    assert "exceptionClass" not in loci[1]
    assert body["args"][0] == _ann_assign(target, _var("int"), _var("value"))


def test_slice_annassign_bound_expressions_resurface_load_loci_without_final_no_value_access() -> (
    None
):
    source = "def f(xs, obj):\n    xs[obj.i:obj.j]: int\n    return xs\n"

    result = lift_source(source, "slice_annassign_bounds_no_value.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    obj_i = _attr(_var("obj"), "i")
    obj_j = _attr(_var("obj"), "j")
    target = _subscript(_var("xs"), _slice(obj_i, obj_j, _none_const()))
    loci = _runtime_failure_loci(contract)
    body = contract["post"]["args"][1]
    assert contract["effects"] == [{"kind": "panics"}]
    assert [locus["subkind"] for locus in loci] == [
        "attribute-access",
        "attribute-access",
    ]
    assert [locus["argTerm"] for locus in loci] == [obj_i, obj_j]
    assert [(locus["line"], locus["col"]) for locus in loci] == [(2, 7), (2, 13)]
    assert all(locus["exceptionClass"] == "AttributeError" for locus in loci)
    assert body["args"][0] == _ann_assign(target, _var("int"), _no_value())


def test_slice_annassign_bound_expressions_resurface_load_loci_before_write() -> None:
    source = "def f(xs, obj, value):\n    xs[obj.i:obj.j]: int = value\n    return xs\n"

    result = lift_source(source, "slice_annassign_bounds_value.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    obj_i = _attr(_var("obj"), "i")
    obj_j = _attr(_var("obj"), "j")
    target = _subscript(_var("xs"), _slice(obj_i, obj_j, _none_const()))
    loci = _runtime_failure_loci(contract)
    body = contract["post"]["args"][1]
    assert contract["effects"] == [
        {"kind": "writes", "target": "xs[obj.i:obj.j]"},
        {"kind": "panics"},
    ]
    assert [locus["subkind"] for locus in loci] == [
        "attribute-access",
        "attribute-access",
        "subscript-write",
    ]
    assert [locus["argTerm"] for locus in loci] == [obj_i, obj_j, target]
    assert [(locus["line"], locus["col"]) for locus in loci] == [
        (2, 7),
        (2, 13),
        (2, 4),
    ]
    assert [locus.get("exceptionClass") for locus in loci] == [
        "AttributeError",
        "AttributeError",
        None,
    ]
    assert body["args"][0] == _ann_assign(target, _var("int"), _var("value"))


def test_slice_annassign_receiver_is_evaluated_before_slice_bounds() -> None:
    source = (
        "def f(obj, other, value):\n"
        "    obj.inner[other.i:other.j]: int = value\n"
        "    return obj\n"
    )

    result = lift_source(source, "slice_annassign_order.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    obj_inner = _attr(_var("obj"), "inner")
    other_i = _attr(_var("other"), "i")
    other_j = _attr(_var("other"), "j")
    target = _subscript(obj_inner, _slice(other_i, other_j, _none_const()))
    loci = _runtime_failure_loci(contract)
    body = contract["post"]["args"][1]
    assert contract["effects"] == [
        {"kind": "writes", "target": "obj.inner[other.i:other.j]"},
        {"kind": "panics"},
    ]
    assert [locus["subkind"] for locus in loci] == [
        "attribute-access",
        "attribute-access",
        "attribute-access",
        "subscript-write",
    ]
    assert [locus["argTerm"] for locus in loci] == [
        obj_inner,
        other_i,
        other_j,
        target,
    ]
    assert [(locus["line"], locus["col"]) for locus in loci] == [
        (2, 4),
        (2, 14),
        (2, 22),
        (2, 4),
    ]
    assert body["args"][0] == _ann_assign(target, _var("int"), _var("value"))


@pytest.mark.parametrize(
    "source",
    [
        "def f(xs, a, b):\n    xs[a:b]: int\n    return xs\n",
        "def f(xs, a, b, value):\n    xs[a:b]: int = value\n    return xs\n",
        "def f(xs, a, b, value):\n    xs[:b]: int = value\n    xs[a:]: int = value\n    xs[:]: int = value\n    return xs\n",
        "def f(xs, a, b, c, value):\n    xs[a:b:c]: int = value\n    return xs\n",
    ],
)
def test_compile_lift_roundtrip_preserves_slice_annassign_body(source: str) -> None:
    lifted = lift_source(source, "roundtrip_slice_annassign.py")
    assert lifted.refusals == []
    contract = _contract(lifted.ir, ".f")
    body = contract["post"]["args"][1]

    compiled = compile_body_term(
        body,
        fn_name="f",
        formals=[str(formal) for formal in contract["formals"]],
    )
    relifted = lift_source(compiled, "roundtrip_slice_annassign.py")
    assert relifted.refusals == []
    relifted_body = _contract(relifted.ir, ".f")["post"]["args"][1]

    assert canonical_json_bytes(relifted_body) == canonical_json_bytes(body)


def test_nested_annassign_without_value_emits_only_intermediate_navigation_loci() -> (
    None
):
    source = (
        "def f(obj, xs, ys, i):\n"
        "    obj.inner.name: int\n"
        "    xs[ys[i]]: int\n"
        "    return obj\n"
    )

    result = lift_source(source, "nested_annassign_no_value.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    loci = _runtime_failure_loci(contract)
    obj_inner = _attr(_var("obj"), "inner")
    ys_i = _subscript(_var("ys"), _var("i"))
    body = contract["post"]["args"][1]
    assert contract["effects"] == [{"kind": "panics"}]
    assert [locus["subkind"] for locus in loci] == [
        "attribute-access",
        "subscript-access",
    ]
    assert [locus["argTerm"] for locus in loci] == [obj_inner, ys_i]
    assert [(locus["line"], locus["col"]) for locus in loci] == [(2, 4), (3, 7)]
    statements = body["args"][0]["args"]
    assert statements[0] == _ann_assign(
        _attr(obj_inner, "name"), _var("int"), _no_value()
    )
    assert statements[1] == _ann_assign(
        _subscript(_var("xs"), ys_i), _var("int"), _no_value()
    )


def test_annassign_missing_value_and_explicit_none_have_distinct_body_terms() -> None:
    source = (
        "def f():\n    missing: int\n    explicit: int = None\n    return explicit\n"
    )

    result = lift_source(source, "annassign_none_discrimination.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    body = contract["post"]["args"][1]
    statements = body["args"][0]["args"]
    missing = _ann_assign(_var("missing"), _var("int"), _no_value())
    explicit_none = _ann_assign(_var("explicit"), _var("int"), _none_const())
    assert statements[0] == missing
    assert statements[1] == explicit_none
    assert missing != explicit_none


def test_nested_annassign_with_value_reuses_store_target_navigation_once() -> None:
    source = (
        "def f(obj, xs, ys, i, value):\n"
        "    obj.inner.name: int = value\n"
        "    xs[ys[i]]: int = value\n"
        "    return value\n"
    )

    result = lift_source(source, "nested_annassign_value.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    loci = _runtime_failure_loci(contract)
    obj_inner = _attr(_var("obj"), "inner")
    obj_inner_name = _attr(obj_inner, "name")
    ys_i = _subscript(_var("ys"), _var("i"))
    xs_ys_i = _subscript(_var("xs"), ys_i)
    assert contract["effects"] == [
        {"kind": "writes", "target": "obj.inner.name"},
        {"kind": "writes", "target": "xs[ys[i]]"},
        {"kind": "panics"},
    ]
    assert [locus["subkind"] for locus in loci] == [
        "attribute-access",
        "attribute-write",
        "subscript-access",
        "subscript-write",
    ]
    assert [locus["argTerm"] for locus in loci] == [
        obj_inner,
        obj_inner_name,
        ys_i,
        xs_ys_i,
    ]
    assert [(locus["line"], locus["col"]) for locus in loci] == [
        (2, 4),
        (2, 4),
        (3, 7),
        (3, 4),
    ]
    assert [locus["argTerm"] for locus in loci].count(obj_inner) == 1
    assert [locus["argTerm"] for locus in loci].count(ys_i) == 1


def test_no_value_annassign_evaluates_receiver_but_not_final_attribute() -> None:
    source = "def f(make):\n    make().name: int\n    return 0\n"

    result = lift_source(source, "annassign_receiver_call.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    assert contract["effects"] == [{"kind": "unresolved_call", "name": "make"}]
    assert contract.get("panicLoci", []) == []


def test_compile_lift_roundtrip_preserves_attribute_annassign_body_with_value() -> None:
    source = "def f(obj, y):\n    obj.name: int = y\n    return obj\n"
    lifted = lift_source(source, "roundtrip_ann_attr_value.py")
    assert lifted.refusals == []
    contract = _contract(lifted.ir, ".f")
    body = contract["post"]["args"][1]

    compiled = compile_body_term(
        body,
        fn_name="f",
        formals=[str(formal) for formal in contract["formals"]],
    )
    relifted = lift_source(compiled, "roundtrip_ann_attr_value.py")
    assert relifted.refusals == []
    relifted_body = _contract(relifted.ir, ".f")["post"]["args"][1]

    assert canonical_json_bytes(relifted_body) == canonical_json_bytes(body)


def test_compile_lift_roundtrip_preserves_attribute_annassign_body_without_value() -> (
    None
):
    source = "def f(obj):\n    obj.name: int\n    return obj\n"
    lifted = lift_source(source, "roundtrip_ann_attr_no_value.py")
    assert lifted.refusals == []
    contract = _contract(lifted.ir, ".f")
    body = contract["post"]["args"][1]

    compiled = compile_body_term(
        body,
        fn_name="f",
        formals=[str(formal) for formal in contract["formals"]],
    )
    relifted = lift_source(compiled, "roundtrip_ann_attr_no_value.py")
    assert relifted.refusals == []
    relifted_body = _contract(relifted.ir, ".f")["post"]["args"][1]

    assert canonical_json_bytes(relifted_body) == canonical_json_bytes(body)


def test_compile_lift_roundtrip_preserves_name_annassign_without_value() -> None:
    source = "def f():\n    x: int\n    return 0\n"
    lifted = lift_source(source, "roundtrip_ann_name_no_value.py")
    assert lifted.refusals == []
    contract = _contract(lifted.ir, ".f")
    body = contract["post"]["args"][1]

    compiled = compile_body_term(
        body,
        fn_name="f",
        formals=[str(formal) for formal in contract["formals"]],
    )
    relifted = lift_source(compiled, "roundtrip_ann_name_no_value.py")
    assert relifted.refusals == []
    relifted_body = _contract(relifted.ir, ".f")["post"]["args"][1]

    assert canonical_json_bytes(relifted_body) == canonical_json_bytes(body)
    assert "x: int = None" not in compiled


def test_compile_lift_roundtrip_preserves_name_annassign_explicit_none_value() -> None:
    source = "def f():\n    x: int = None\n    return x\n"
    lifted = lift_source(source, "roundtrip_ann_name_explicit_none.py")
    assert lifted.refusals == []
    contract = _contract(lifted.ir, ".f")
    body = contract["post"]["args"][1]

    compiled = compile_body_term(
        body,
        fn_name="f",
        formals=[str(formal) for formal in contract["formals"]],
    )
    relifted = lift_source(compiled, "roundtrip_ann_name_explicit_none.py")
    assert relifted.refusals == []
    relifted_body = _contract(relifted.ir, ".f")["post"]["args"][1]

    assert canonical_json_bytes(relifted_body) == canonical_json_bytes(body)
    assert "x: int = None" in compiled


@pytest.mark.parametrize(
    ("source", "module", "reason"),
    [
        (
            "def f(pair):\n    (a, (b, c)) = pair\n    return c\n",
            "nested_unpacking_refusal.py",
            "unsupported assignment target: Tuple",
        ),
        (
            "def f(pair):\n    a, *rest = pair\n    return rest\n",
            "starred_unpacking_refusal.py",
            "unsupported assignment target: Tuple",
        ),
        (
            "def f(obj, pair):\n    obj.a, b = pair\n    return b\n",
            "attribute_unpack_target_refusal.py",
            "unsupported assignment target: Tuple",
        ),
        (
            "def f(xs, pair):\n    xs[0], b = pair\n    return b\n",
            "subscript_unpack_target_refusal.py",
            "unsupported assignment target: Tuple",
        ),
    ],
)
def test_slice_13_keeps_complex_unpacking_out_of_scope(
    source: str,
    module: str,
    reason: str,
) -> None:
    result = lift_source(source, module)

    assert result.refusals == [
        {
            "kind": "unhandled-syntax",
            "function": f"{module.removesuffix('.py')}.f",
            "line": 2,
            "reason": reason,
        }
    ]


def test_b1_tuple_and_list_literals_lift_as_faithful_body_terms() -> None:
    source = (
        "def f(a, b):\n" "    pair = (a, b)\n" "    xs = [a, b]\n" "    return pair\n"
    )

    result = lift_source(source, "b1_literals.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    body = contract["post"]["args"][1]
    statements = body["args"][0]["args"]
    assert statements[0] == {
        "kind": "ctor",
        "name": "python:assign",
        "args": [_var("pair"), _tuple(_var("a"), _var("b"))],
    }
    assert statements[1] == {
        "kind": "ctor",
        "name": "python:assign",
        "args": [_var("xs"), _list(_var("a"), _var("b"))],
    }


def test_b1_keyword_call_arguments_preserve_names_and_order() -> None:
    source = "def f(a, b):\n    return make(a, dtype=b, copy=False)\n"

    result = lift_source(source, "b1_kwargs.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    body = contract["post"]["args"][1]
    assert body == {
        "kind": "ctor",
        "name": "python:return",
        "args": [
            _call(
                "make",
                _var("a"),
                _kwarg("dtype", _var("b")),
                _kwarg("copy", _bool_const(False)),
            )
        ],
    }


def test_b1_signature_forms_lift_body_and_preserve_parameter_shape() -> None:
    source = (
        "def f(a, /, b=None, *items, c=True, d=(1, 'x'), **kwargs):\n"
        "    return (a, b, items, c, d, kwargs)\n"
    )

    result = lift_source(source, "b1_signature.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    assert contract["formals"] == ["a", "b", "items", "c", "d", "kwargs"]
    assert contract["parameterShape"] == [
        {"name": "a", "kind": "positional-only"},
        {"name": "b", "kind": "positional-or-keyword", "default": _none_const()},
        {"name": "items", "kind": "vararg"},
        {"name": "c", "kind": "keyword-only", "default": _bool_const(True)},
        {
            "name": "d",
            "kind": "keyword-only",
            "default": _tuple(_int_const(1), _str_const("x")),
        },
        {"name": "kwargs", "kind": "kwarg"},
    ]
    body = contract["post"]["args"][1]
    assert body == {
        "kind": "ctor",
        "name": "python:return",
        "args": [
            _tuple(
                _var("a"),
                _var("b"),
                _var("items"),
                _var("c"),
                _var("d"),
                _var("kwargs"),
            )
        ],
    }

    compiled = compile_ir_document([contract])
    relifted = lift_source(compiled, "b1_signature.py")
    relifted_contract = _contract(relifted.ir, ".f")
    assert relifted.refusals == []
    assert relifted_contract["formals"] == contract["formals"]
    assert relifted_contract["parameterShape"] == contract["parameterShape"]


def test_b1_signed_integer_defaults_are_literal_parameter_shape() -> None:
    source = "def f(axis=-1, *, step=+2):\n    return (axis, step)\n"

    result = lift_source(source, "b1_signed_defaults.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    assert contract["parameterShape"] == [
        {"name": "axis", "kind": "positional-or-keyword", "default": _int_const(-1)},
        {"name": "step", "kind": "keyword-only", "default": _int_const(2)},
    ]


def test_dict_literal_defaults_are_literal_parameter_shape() -> None:
    source = "def f(mapping={'a': 1}, *, options={}):\n    return mapping\n"

    result = lift_source(source, "dict_default.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    assert contract["parameterShape"] == [
        {
            "name": "mapping",
            "kind": "positional-or-keyword",
            "default": _dict(_dict_entry(_str_const("a"), _int_const(1))),
        },
        {"name": "options", "kind": "keyword-only", "default": _dict()},
    ]

    compiled = compile_ir_document([contract])
    relifted = lift_source(compiled, "dict_default.py")
    relifted_contract = _contract(relifted.ir, ".f")
    assert relifted.refusals == []
    assert relifted_contract["parameterShape"] == contract["parameterShape"]


def test_b1_nonliteral_default_remains_refused_as_definition_time_hazard() -> None:
    result = lift_source("def f(x=make()):\n    return x\n", "b1_default_refusal.py")

    assert result.refusals == [
        {
            "kind": "unhandled-syntax",
            "function": "b1_default_refusal.f",
            "line": 1,
            "reason": "non-literal default parameter values are refused",
        }
    ]


@pytest.mark.parametrize(
    ("source", "module"),
    [
        ("def f(x=-y):\n    return x\n", "b1_unary_name_default_refusal.py"),
        ("def f(x=~0):\n    return x\n", "b1_unary_invert_default_refusal.py"),
    ],
)
def test_b1_unary_defaults_remain_refused_unless_signed_integer_literal(
    source: str,
    module: str,
) -> None:
    result = lift_source(source, module)

    assert result.refusals == [
        {
            "kind": "unhandled-syntax",
            "function": f"{module.removesuffix('.py')}.f",
            "line": 1,
            "reason": "non-literal default parameter values are refused",
        }
    ]


def test_b1_try_lifts_opaque_and_retains_inner_raise_locus() -> None:
    source = (
        "def f(flag):\n"
        "    try:\n"
        "        if flag:\n"
        "            raise ValueError\n"
        "    except ValueError:\n"
        "        return 0\n"
        "    return 1\n"
    )

    result = lift_source(source, "b1_try.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    body = contract["post"]["args"][1]
    first_stmt = body["args"][0]
    assert first_stmt["name"] == "python:try"
    loci = _runtime_failure_loci(contract)
    assert [locus["subkind"] for locus in loci] == ["explicit-raise"]
    assert loci[0]["exceptionClass"] == "ValueError"


def test_b1_except_handler_name_is_handler_local_not_module_global() -> None:
    source = (
        "err = 'module'\n"
        "def f():\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError as err:\n"
        "        return err\n"
    )

    result = lift_source(source, "b1_except_alias.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    assert {"kind": "reads", "target": "err"} not in contract["effects"]


def test_b1_except_handler_name_does_not_leak_after_handler() -> None:
    source = (
        "err = 'module'\n"
        "def f():\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError as err:\n"
        "        pass\n"
        "    return err\n"
    )

    result = lift_source(source, "b1_except_alias_after.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    # The handler alias is scoped to the handler: after it, `err` resolves
    # module-ward. The module binding `err = 'module'` value-pins, so the
    # post-handler read carries the pinned value rather than a fog read --
    # which still proves the alias did not leak past the handler.
    assert {"kind": "reads", "target": "err"} not in contract["effects"]
    assert json.dumps(str_const("module")) in json.dumps(contract)


def test_with_open_lifts_body_and_records_io_effect() -> None:
    source = "def f(path):\n    with open(path):\n        return path\n"

    result = lift_source(source, "with_open.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    assert _function_body(result) == _with_stmt(_return(_var("path")))
    assert {"kind": "io"} in contract["effects"]
    assert {"kind": "unresolved_call", "name": "open"} in contract["effects"]


def test_with_as_name_binds_opaque_local_for_body() -> None:
    source = "def f(ctx):\n    with ctx() as handle:\n        return handle\n"

    result = lift_source(source, "with_as_name.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    assert _function_body(result) == _with_stmt(_return(_var("handle")))
    assert {"kind": "io"} in contract["effects"]
    assert {"kind": "unresolved_call", "name": "ctx"} in contract["effects"]
    assert {"kind": "reads", "target": "handle"} not in contract["effects"]


def test_with_open_as_handle_lifts_body_claims_under_opaque_binding() -> None:
    source = (
        "def f(path):\n"
        "    with open(path) as handle:\n"
        "        data = handle.read()\n"
        "        return data\n"
    )

    result = lift_source(source, "with_open_as_handle.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    assert _function_body(result) == _with_stmt(
        _seq(
            _assign(_var("data"), _call("handle.read")),
            _return(_var("data")),
        )
    )
    assert {"kind": "io"} in contract["effects"]
    assert {"kind": "unresolved_call", "name": "open"} in contract["effects"]
    assert {"kind": "unresolved_call", "name": "handle.read"} in contract["effects"]
    assert {"kind": "reads", "target": "handle"} not in contract["effects"]


def test_nested_with_statements_lift_nested_body_terms() -> None:
    source = (
        "def f(outer, inner):\n"
        "    with outer():\n"
        "        with inner():\n"
        "            return 1\n"
    )

    result = lift_source(source, "with_nested.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    assert _function_body(result) == _with_stmt(_with_stmt(_return(_int_const(1))))
    assert {"kind": "io"} in contract["effects"]
    assert {"kind": "unresolved_call", "name": "outer"} in contract["effects"]
    assert {"kind": "unresolved_call", "name": "inner"} in contract["effects"]


def test_with_multiple_items_lifts_single_body_with_each_context_effect() -> None:
    source = (
        "def f(first, second):\n"
        "    with first(), second() as value:\n"
        "        return value\n"
    )

    result = lift_source(source, "with_multiple.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    assert _function_body(result) == _with_stmt(_return(_var("value")))
    assert {"kind": "io"} in contract["effects"]
    assert {"kind": "unresolved_call", "name": "first"} in contract["effects"]
    assert {"kind": "unresolved_call", "name": "second"} in contract["effects"]
    assert {"kind": "reads", "target": "value"} not in contract["effects"]


def test_with_floor_discriminates_match_statement() -> None:
    source = (
        "def f(x):\n"
        "    match x:\n"
        "        case 0:\n"
        "            return 0\n"
    )

    result = lift_source(source, "match_statement.py")

    assert [refusal["reason"] for refusal in result.refusals] == [
        "unhandled statement kind: Match"
    ]


def test_with_roundtrip_is_structurally_stable() -> None:
    term = _with_stmt(_return(_var("x")))

    compiled = compile_body_term(term, formals=["x"])
    relifted = lift_source(compiled, "roundtrip_with.py")

    assert relifted.refusals == []
    body = _function_body(relifted)
    assert body == term
    assert cid_of_json(body) == cid_of_json(term)


def test_with_as_non_name_target_is_named_refusal() -> None:
    source = "def f(ctx):\n    with ctx() as (left, right):\n        return left\n"

    result = lift_source(source, "with_tuple_target.py")

    assert [refusal["reason"] for refusal in result.refusals] == [
        "unsupported with-as target: Tuple"
    ]


def test_b1_decorated_functions_remain_deferred() -> None:
    source = (
        "def dispatcher(a):\n"
        "    return (a,)\n"
        "\n"
        "@array_function_dispatch(dispatcher)\n"
        "def f(a):\n"
        "    return a.name\n"
    )

    result = lift_source(source, "b1_decorator_refusal.py")

    assert result.refusals == [
        {
            "kind": "unhandled-syntax",
            "function": "b1_decorator_refusal.f",
            "line": 5,
            "reason": "decorated functions are refused",
        }
    ]


def test_b1_starred_call_arguments_remain_refused() -> None:
    starred = lift_source("def f(xs):\n    return make(*xs)\n", "b1_starred_call.py")

    assert starred.refusals == [
        {
            "kind": "unhandled-syntax",
            "function": "b1_starred_call.f",
            "line": 2,
            "reason": "starred call arguments are refused",
        }
    ]


def test_simple_chained_call_lifts_with_unresolved_chained_effect() -> None:
    result = lift_source("def f(factory, x):\n    return factory()(x)\n", "chain.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    assert _function_body(result) == _return(
        _call_term(_call("factory"), _var("x"))
    )
    assert {"kind": "unresolved_call", "name": "factory"} in contract["effects"]
    assert {"kind": "unresolved_call", "name": "(chained)"} in contract["effects"]


def test_method_chain_from_call_result_lifts_dynamic_attribute_callee() -> None:
    result = lift_source(
        "def f(factory, x):\n    return factory().method(x)\n",
        "method_chain.py",
    )

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    assert _function_body(result) == _return(
        _call_term(_attr(_call("factory"), "method"), _var("x"))
    )
    assert {"kind": "panics"} in contract["effects"]
    assert {"kind": "unresolved_call", "name": "factory"} in contract["effects"]
    assert {"kind": "unresolved_call", "name": "(chained)"} in contract["effects"]


def test_triple_chained_call_lifts_nested_dynamic_callees() -> None:
    result = lift_source("def f(factory):\n    return factory()()()\n", "triple_chain.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    assert _function_body(result) == _return(
        _call_term(_call_term(_call("factory")))
    )
    assert {"kind": "unresolved_call", "name": "factory"} in contract["effects"]
    assert {"kind": "unresolved_call", "name": "(chained)"} in contract["effects"]


def test_chained_call_floor_discriminates_subscript_callee() -> None:
    dynamic = lift_source(
        "def f(table):\n    return table[0](1)\n", "subscript_callee.py"
    )

    assert dynamic.refusals == [
        {
            "kind": "unhandled-syntax",
            "function": "subscript_callee.f",
            "line": 2,
            "reason": "unsupported callee kind: Subscript",
        }
    ]


def test_chained_call_roundtrip_is_structurally_stable() -> None:
    term = _call_term(_call_term(_call("factory"), _var("x")), _var("y"))

    compiled = compile_body_term(_return(term), formals=["factory", "x", "y"])
    relifted = lift_source(compiled, "roundtrip_chain.py")

    assert relifted.refusals == []
    body = _function_body(relifted)
    assert body == _return(term)
    assert cid_of_json(body) == cid_of_json(_return(term))


def test_simple_listcomp_lifts_element_generator_and_opaque_loop_effect() -> None:
    source = "def f(xs):\n    return [f(x) for x in xs]\n"

    result = lift_source(source, "listcomp_simple.py")

    term = _listcomp(_call("f", _var("x")), _comprehension(_var("x"), _var("xs")))
    contract = _contract(result.ir, ".f")
    loop_cid = cid_of_json(term)
    assert result.refusals == []
    assert _function_body(result) == _return(term)
    assert {"kind": "unresolved_call", "name": "f"} in contract["effects"]
    assert {"kind": "opaque_loop", "loopCid": loop_cid} in contract["effects"]
    assert result.opacity_report == [
        {
            "file": "listcomp_simple.py",
            "line": 2,
            "col": 11,
            "kind": "opaque_loop",
            "cid": loop_cid,
        }
    ]


def test_listcomp_with_if_filter_binds_target_for_filter_and_element() -> None:
    source = "def f(xs):\n    return [x * 2 for x in xs if x > 0]\n"

    result = lift_source(source, "listcomp_filter.py")

    term = _listcomp(
        _binary("python:mul", _var("x"), _int_const(2)),
        _comprehension(
            _var("x"),
            _var("xs"),
            _compare(">", _var("x"), _int_const(0)),
        ),
    )
    assert result.refusals == []
    assert _function_body(result) == _return(term)


def test_nested_listcomp_generators_bind_prior_targets_for_later_iters() -> None:
    source = "def f(m):\n    return [x for row in m for x in row]\n"

    result = lift_source(source, "listcomp_nested.py")

    term = _listcomp(
        _var("x"),
        _comprehension(_var("row"), _var("m")),
        _comprehension(_var("x"), _var("row")),
    )
    assert result.refusals == []
    assert _function_body(result) == _return(term)


def test_listcomp_tuple_target_unpack_binds_each_name_opaquely() -> None:
    source = "def f(pairs):\n    return [a + b for (a, b) in pairs]\n"

    result = lift_source(source, "listcomp_tuple_target.py")

    term = _listcomp(
        _binary("python:add", _var("a"), _var("b")),
        _comprehension(_tuple(_var("a"), _var("b")), _var("pairs")),
    )
    assert result.refusals == []
    assert _function_body(result) == _return(term)


def test_listcomp_target_binding_does_not_leak_to_following_statement() -> None:
    source = (
        'x = "global"\n'
        "def f(xs):\n"
        "    values = [x for x in xs]\n"
        "    return x\n"
    )

    result = lift_source(source, "listcomp_scope.py")

    term = _listcomp(_var("x"), _comprehension(_var("x"), _var("xs")))
    assert result.refusals == []
    assert _function_body(result) == _seq(
        _assign(_var("values"), term),
        _return(_str_const("global")),
    )


def test_listcomp_floor_discriminates_set_and_dict_comprehensions() -> None:
    set_result = lift_source(
        "def f(xs):\n    return {x for x in xs}\n",
        "setcomp_refusal.py",
    )
    dict_result = lift_source(
        "def f(xs):\n    return {x: x for x in xs}\n",
        "dictcomp_refusal.py",
    )

    assert set_result.refusals == [
        {
            "kind": "unhandled-syntax",
            "function": "setcomp_refusal.f",
            "line": 2,
            "reason": "unhandled expression kind: SetComp",
        }
    ]
    assert dict_result.refusals == [
        {
            "kind": "unhandled-syntax",
            "function": "dictcomp_refusal.f",
            "line": 2,
            "reason": "unhandled expression kind: DictComp",
        }
    ]


def test_listcomp_roundtrip_is_structurally_stable() -> None:
    term = _listcomp(
        _binary("python:add", _var("a"), _var("b")),
        _comprehension(
            _tuple(_var("a"), _var("b")),
            _var("pairs"),
            _compare(">", _var("a"), _int_const(0)),
        ),
    )

    compiled = compile_body_term(_return(term), formals=["pairs"])
    relifted = lift_source(compiled, "roundtrip_listcomp.py")

    assert relifted.refusals == []
    body = _function_body(relifted)
    assert body == _return(term)
    assert cid_of_json(body) == cid_of_json(_return(term))


def test_local_import_statement_lifts_as_opaque_io_binding() -> None:
    source = "def f():\n    import os\n    return os.getcwd()\n"

    result = lift_source(source, "local_import.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    assert _function_body(result) == _seq(
        _import_stmt("os"),
        _return(_call("os.getcwd")),
    )
    assert {"kind": "io"} in contract["effects"]
    assert {"kind": "unresolved_call", "name": "os.getcwd"} in contract["effects"]


def test_local_import_asname_binds_alias_opaquely_for_following_body() -> None:
    source = (
        'np = "global"\n'
        "def f():\n"
        "    import numpy as np\n"
        "    value = np.array(1)\n"
        "    return np\n"
    )

    result = lift_source(source, "local_import_alias.py")

    assert result.refusals == []
    contract = _contract(result.ir, ".f")
    array_access = _attr(_var("np"), "array")
    assert _function_body(result) == _seq(
        _seq(
            _import_stmt("np"),
            _assign(_var("value"), _call("np.array", _int_const(1))),
        ),
        _return(_var("np")),
    )
    assert _runtime_failure_loci(contract)[0]["argTerm"] == array_access
    assert {"kind": "io"} in contract["effects"]
    assert {"kind": "unresolved_call", "name": "np.array"} in contract["effects"]


def test_local_import_from_binds_imported_name_but_not_module() -> None:
    source = (
        'pkg = "global-pkg"\n'
        'y = "global-y"\n'
        "def f():\n"
        "    from pkg import y\n"
        "    return (y, pkg)\n"
    )

    result = lift_source(source, "local_import_from.py")

    assert result.refusals == []
    assert _function_body(result) == _seq(
        _import_stmt("y"),
        _return(_tuple(_var("y"), _str_const("global-pkg"))),
    )
    assert {"kind": "io"} in _contract(result.ir, ".f")["effects"]


def test_local_import_from_asname_binds_alias_not_original_name() -> None:
    source = (
        'y = "global-y"\n'
        'z = "global-z"\n'
        "def f():\n"
        "    from pkg import y as z\n"
        "    return (z, y)\n"
    )

    result = lift_source(source, "local_import_from_alias.py")

    assert result.refusals == []
    assert _function_body(result) == _seq(
        _import_stmt("z"),
        _return(_tuple(_var("z"), _str_const("global-y"))),
    )


def test_dotted_local_import_binds_head_name_only() -> None:
    source = (
        'pkg = "global-pkg"\n'
        "def f():\n"
        "    import pkg.sub\n"
        "    return pkg\n"
    )

    result = lift_source(source, "local_import_dotted.py")

    assert result.refusals == []
    assert _function_body(result) == _seq(
        _import_stmt("pkg"),
        _return(_var("pkg")),
    )


def test_import_floor_discriminates_delete_statement() -> None:
    result = lift_source("def f(x):\n    del x\n", "import_delete_refusal.py")

    assert result.refusals == [
        {
            "kind": "unhandled-syntax",
            "function": "import_delete_refusal.f",
            "line": 2,
            "reason": "unhandled statement kind: Delete",
        }
    ]


def test_import_roundtrip_is_structurally_stable() -> None:
    term = _seq(
        _import_stmt("os", "np"),
        _return(_call("np.array", _int_const(1))),
    )

    compiled = compile_body_term(term)
    relifted = lift_source(compiled, "roundtrip_import.py")

    assert relifted.refusals == []
    body = _function_body(relifted)
    assert body == term
    assert cid_of_json(body) == cid_of_json(term)


def test_simple_nested_function_lifts_contract_and_local_callback_binding() -> None:
    source = (
        'x = "global"\n'
        "def outer(x, runner):\n"
        "    def inner(y):\n"
        "        return x + y\n"
        "    return runner(inner)\n"
    )

    result = lift_source(source, "nested_simple.py")

    assert result.refusals == []
    outer = _contract(result.ir, ".outer")
    inner = _contract(result.ir, ".outer.<locals>.inner")
    assert outer["post"]["args"][1] == _seq(
        _nested_funcdef("inner"),
        _return(_call("runner", _var("inner"))),
    )
    assert inner["post"]["args"][1] == _return(
        _binary("python:add", _var("x"), _var("y"))
    )
    assert inner["effects"] == []
    assert {"kind": "unresolved_call", "name": "runner"} in outer["effects"]
    assert {"kind": "unresolved_call", "name": "inner"} not in outer["effects"]


def test_decorated_nested_function_uses_opaque_fork_and_local_binding() -> None:
    source = (
        "def deco(fn):\n"
        "    return fn\n"
        "\n"
        "def outer():\n"
        "    @deco\n"
        "    def inner():\n"
        "        return 1\n"
        "    return inner\n"
    )

    result = lift_source(source, "nested_decorated.py")

    assert result.refusals == []
    outer = _contract(result.ir, ".outer")
    assert outer["post"]["args"][1] == _seq(
        _nested_funcdef("inner"),
        _return(_var("inner")),
    )
    assert {"kind": "unresolved_call", "name": "inner"} in outer["effects"]
    assert not any(
        str(item.get("fnName", "")).endswith(".outer.<locals>.inner")
        for item in result.ir
    )


def test_nested_function_refused_control_uses_opaque_fork_without_outer_refusal() -> None:
    source = (
        "def outer():\n"
        "    def inner():\n"
        "        yield 1\n"
        "    return inner\n"
    )

    result = lift_source(source, "nested_refused_control.py")

    assert result.refusals == []
    outer = _contract(result.ir, ".outer")
    assert outer["post"]["args"][1] == _seq(
        _nested_funcdef("inner"),
        _return(_var("inner")),
    )
    assert {"kind": "unresolved_call", "name": "inner"} in outer["effects"]
    assert not any(
        str(item.get("fnName", "")).endswith(".outer.<locals>.inner")
        for item in result.ir
    )


def test_nested_function_body_refusal_is_reported_without_swallowing_outer() -> None:
    source = (
        "def outer():\n"
        "    def inner(x):\n"
        "        del x\n"
        "    return inner\n"
    )

    result = lift_source(source, "nested_refusal.py")

    assert result.refusals == [
        {
            "kind": "unhandled-syntax",
            "function": "nested_refusal.outer.<locals>.inner",
            "line": 3,
            "reason": "unhandled statement kind: Delete",
        }
    ]
    outer = _contract(result.ir, ".outer")
    assert outer["post"]["args"][1] == _seq(
        _nested_funcdef("inner"),
        _return(_var("inner")),
    )
    assert {"kind": "unresolved_call", "name": "inner"} in outer["effects"]
    assert not any(
        str(item.get("fnName", "")).endswith(".outer.<locals>.inner")
        for item in result.ir
    )


def test_nested_function_name_used_after_definition_is_local_binding() -> None:
    source = (
        'inner = "global"\n'
        "def outer():\n"
        "    def inner():\n"
        "        return 1\n"
        "    return inner\n"
    )

    result = lift_source(source, "nested_binding.py")

    assert result.refusals == []
    assert _function_body(result, ".outer") == _seq(
        _nested_funcdef("inner"),
        _return(_var("inner")),
    )
    assert _function_body(result, ".outer.<locals>.inner") == _return(_int_const(1))


def test_nested_function_floor_discriminates_classdef_statement() -> None:
    result = lift_source(
        "def outer():\n    class C:\n        pass\n    return C\n",
        "nested_class_refusal.py",
    )

    assert result.refusals == [
        {
            "kind": "unhandled-syntax",
            "function": "nested_class_refusal.outer",
            "line": 2,
            "reason": "unhandled statement kind: ClassDef",
        }
    ]


def test_nested_function_roundtrip_is_structurally_stable() -> None:
    term = _seq(_nested_funcdef("inner"), _return(_var("inner")))

    compiled = compile_body_term(term)
    relifted = lift_source(compiled, "roundtrip_nested_funcdef.py")

    assert relifted.refusals == []
    body = _function_body(relifted)
    assert body == term
    assert cid_of_json(body) == cid_of_json(term)


def test_simple_key_lambda_lifts_formal_scope_and_body_term() -> None:
    source = "def f(xs):\n    return sorted(xs, key=lambda x: x[0])\n"

    result = lift_source(source, "lambda_key.py")

    assert result.refusals == []
    assert _function_body(result) == _return(
        _call(
            "sorted",
            _var("xs"),
            _kwarg(
                "key",
                _lambda_expr(
                    _str_const("x"),
                    _subscript(_var("x"), _int_const(0)),
                ),
            ),
        )
    )


def test_lambda_captures_enclosing_locals_symbolically_without_global_read() -> None:
    source = (
        'x = "global"\n'
        "def f(scale):\n"
        "    return lambda x: x + scale\n"
    )

    result = lift_source(source, "lambda_capture.py")

    contract = _contract(result.ir, ".f")
    assert result.refusals == []
    assert _function_body(result) == _return(
        _lambda_expr(
            _str_const("x"),
            _binary("python:add", _var("x"), _var("scale")),
        )
    )
    assert {"kind": "reads", "target": "x"} not in contract["effects"]


def test_lambda_default_and_keyword_only_parameters_are_carried() -> None:
    source = "def f():\n    return lambda x=1, *, y=2: x + y\n"

    result = lift_source(source, "lambda_defaults.py")

    assert result.refusals == []
    assert _function_body(result) == _return(
        _lambda_expr(
            _lambda_param("x", "positional-or-keyword", _int_const(1)),
            _lambda_param("y", "keyword-only", _int_const(2)),
            _binary("python:add", _var("x"), _var("y")),
        )
    )


def test_lambda_nonliteral_default_refuses_on_parameter_default() -> None:
    result = lift_source(
        "def f(make):\n    return lambda x=make(): x\n",
        "lambda_nonliteral_default.py",
    )

    assert result.refusals == [
        {
            "kind": "unhandled-syntax",
            "function": "lambda_nonliteral_default.f",
            "line": 2,
            "reason": "non-literal default parameter values are refused",
        }
    ]


def test_lambda_variadic_parameters_are_carried_and_bound() -> None:
    source = "def f():\n    return lambda *items, **kwargs: (items, kwargs)\n"

    result = lift_source(source, "lambda_variadic.py")

    assert result.refusals == []
    assert _function_body(result) == _return(
        _lambda_expr(
            _lambda_param("items", "vararg"),
            _lambda_param("kwargs", "kwarg"),
            _tuple(_var("items"), _var("kwargs")),
        )
    )


def test_lambda_body_refusal_propagates_without_swallowing_outer() -> None:
    result = lift_source(
        "def f(xs):\n    return lambda x: (y for y in x)\n",
        "lambda_body_refusal.py",
    )

    assert result.refusals == [
        {
            "kind": "unhandled-syntax",
            "function": "lambda_body_refusal.f",
            "line": 2,
            "reason": "unhandled expression kind: GeneratorExp",
        }
    ]


def test_lambda_roundtrip_is_structurally_stable() -> None:
    term = _lambda_expr(
        _lambda_param("x", "positional-or-keyword", _int_const(1)),
        _lambda_param("y", "keyword-only", _int_const(2)),
        _binary("python:add", _var("x"), _var("y")),
    )

    compiled = compile_body_term(_return(term))
    relifted = lift_source(compiled, "roundtrip_lambda.py")

    assert relifted.refusals == []
    body = _function_body(relifted)
    assert body == _return(term)
    assert cid_of_json(body) == cid_of_json(_return(term))


def test_none_guarded_attribute_access_emits_one_runtime_failure_locus() -> None:
    source = (
        "def f(obj):\n"
        "    if obj.name is None:\n"
        "        return 0\n"
        "    return 1\n"
    )

    result = lift_source(source, "attr_guard.py")

    contract = _contract(result.ir, ".f")
    loci = _runtime_failure_loci(contract)
    assert result.refusals == []
    assert contract["effects"] == [{"kind": "panics"}]
    assert [locus["subkind"] for locus in loci] == ["attribute-access"]
    assert [(locus["line"], locus["col"]) for locus in loci] == [(2, 7)]


def test_none_guarded_subscript_access_emits_one_runtime_failure_locus() -> None:
    source = (
        "def f(xs, key):\n"
        "    if xs[key] is None:\n"
        "        return 0\n"
        "    return 1\n"
    )

    result = lift_source(source, "subscript_guard.py")

    contract = _contract(result.ir, ".f")
    loci = _runtime_failure_loci(contract)
    assert result.refusals == []
    assert contract["effects"] == [{"kind": "panics"}]
    assert [locus["subkind"] for locus in loci] == ["subscript-access"]
    assert [(locus["line"], locus["col"]) for locus in loci] == [(2, 7)]


def test_method_call_callee_attribute_emits_runtime_failure_locus() -> None:
    source = "def f(obj):\n    return obj.method()\n"

    result = lift_source(source, "method_call.py")

    contract = _contract(result.ir, ".f")
    loci = _runtime_failure_loci(contract)
    assert result.refusals == []
    assert {"kind": "panics"} in contract["effects"]
    assert {"kind": "unresolved_call", "name": "obj.method"} in contract["effects"]
    assert [locus["subkind"] for locus in loci] == ["attribute-access"]
    assert loci[0]["exceptionClass"] == "AttributeError"
    assert loci[0]["argTerm"] == {
        "kind": "ctor",
        "name": "python:attribute",
        "args": [
            {"kind": "var", "name": "obj"},
            {
                "kind": "const",
                "value": "method",
                "sort": {"kind": "primitive", "name": "String"},
            },
        ],
    }
    assert (loci[0]["line"], loci[0]["col"]) == (2, 11)


def test_compile_lift_roundtrip_preserves_cf_guarded_none_if_body() -> None:
    source = (
        "def f(x):\n"
        "    if x is None:\n"
        "        return 0\n"
        "    else:\n"
        "        return 1\n"
    )
    lifted = lift_source(source, "roundtrip_none.py")
    contract = _contract(lifted.ir, ".f")
    body = contract["post"]["args"][1]

    compiled = compile_body_term(
        body,
        fn_name="f",
        formals=[str(formal) for formal in contract["formals"]],
    )
    relifted = lift_source(compiled, "roundtrip_none.py")
    relifted_body = _contract(relifted.ir, ".f")["post"]["args"][1]

    assert canonical_json_bytes(relifted_body) == canonical_json_bytes(body)


def test_refuses_unhandled_syntax_without_unknown_ops() -> None:
    source = "def bad(xs):\n    return {x for x in xs}\n"

    result = lift_source(source, "badmodule.py")

    assert len(result.ir) == 1
    assert result.ir[0]["fnName"] == "<source-unit:badmodule.py>"
    assert result.ir[0]["post"]["args"][1]["name"] == "python:source-unit"
    assert result.ir[0]["post"]["args"][1]["args"][1]["name"] == "python:pass"
    assert len(result.refusals) == 1
    refusal = result.refusals[0]
    assert refusal["kind"] == "unhandled-syntax"
    assert refusal["function"] == "badmodule.bad"
    assert refusal["line"] == 2
    assert "SetComp" in refusal["reason"]
    assert "python:unknown" not in _canon(result.refusals)
    assert "python:skip" not in _canon(result.refusals)


def test_set_comprehension_refusal_does_not_fire_different_variant() -> None:
    source = "def bad(xs):\n    return {x for x in xs}\n"

    result = lift_source(source, "badmodule.py")

    assert [refusal["kind"] for refusal in result.refusals] == ["unhandled-syntax"]
    assert "syntax-error" not in _canon(result.refusals)


def test_effects_are_sorted_and_loop_cid_is_blake3_512() -> None:
    source = (
        "def total(xs):\n"
        "    acc = 0\n"
        "    for x in xs:\n"
        "        acc = acc + x\n"
        "    print(acc)\n"
        "    return acc\n"
    )

    result = lift_source(source, "loops.py")

    contract = _contract(result.ir, ".total")
    effects = contract["effects"]
    assert [effect["kind"] for effect in effects] == ["io", "opaque_loop"]
    loop_cid = effects[1]["loopCid"]
    assert loop_cid.startswith("blake3-512:")
    assert len(loop_cid) == len("blake3-512:") + 128


def test_while_loop_populates_opacity_report() -> None:
    source = (
        "def countdown(n):\n"
        "    while n:\n"
        "        n = n - 1\n"
        "    return n\n"
    )

    result = lift_source(source, "opaque_loop.py")

    contract = _contract(result.ir, ".countdown")
    loop_cid = next(
        effect["loopCid"]
        for effect in contract["effects"]
        if effect["kind"] == "opaque_loop"
    )
    assert result.opacity_report == [
        {
            "file": "opaque_loop.py",
            "line": 2,
            "col": 4,
            "kind": "opaque_loop",
            "cid": loop_cid,
        }
    ]


def test_source_without_loops_keeps_opacity_report_empty() -> None:
    source = "def add_one(n):\n    return n + 1\n"

    result = lift_source(source, "transparent.py")

    assert result.opacity_report == []


def test_cid_of_json_uses_protocol_jcs_control_char_escaping() -> None:
    value = {"source": "def f():\n  return 1\n"}
    expected = (
        "blake3-512:17778ed1c9bbda5f202e07c2e35c3e9009c03cb314229818cb34b895b1f66fe1e"
        "25347b433538cf3a3848d07ebae051728fe5996cd408f067476ae97c943be05"
    )

    assert jcs_hash(vobj([("source", vstr(value["source"]))])) == expected
    assert cid_of_json(value) == expected


def test_compile_lift_roundtrip_ir_document_is_byte_identical() -> None:
    source = "def f(x):\n    y = x + 1\n    return y\n"

    first = lift_source(source, "roundtrip.py")
    compiled = compile_ir_document(first.ir)
    second = lift_source(compiled, "roundtrip.py")

    assert _canon(second.ir) == _canon(first.ir)


def test_compile_function_contract_without_source_unit_uses_ast_unparse() -> None:
    source = "def f(x):\n    y = x + 1\n    return y\n"
    lifted = lift_source(source, "roundtrip.py")
    contract = _contract(lifted.ir, ".f")

    compiled = compile_ir_document([contract])

    assert "def f(x):" in compiled
    assert "y = x + 1" in compiled
    assert "return y" in compiled


def test_compile_lift_roundtrip_body_term_is_byte_identical() -> None:
    source = "def f(x):\n    y = x + 1\n    return y\n"
    lifted = lift_source(source, "roundtrip.py")
    contract = _contract(lifted.ir, ".f")
    body = contract["post"]["args"][1]

    compiled = compile_body_term(
        body,
        fn_name="f",
        formals=[str(formal) for formal in contract["formals"]],
    )
    relifted = lift_source(compiled, "roundtrip.py")
    relifted_body = _contract(relifted.ir, ".f")["post"]["args"][1]

    assert canonical_json_bytes(relifted_body) == canonical_json_bytes(body)


def test_class_shapes_catalog_records_guaranteed_slots_and_method_receivers() -> None:
    source = (
        "class Box:\n"
        "    species = 'container'\n"
        "    __slots__ = ('value', 'declared_only')\n"
        "\n"
        "    def __init__(self):\n"
        "        self.value = 1\n"
        "\n"
        "    def get(self):\n"
        "        return self.value\n"
        "\n"
        "    @classmethod\n"
        "    def from_value(cls, value):\n"
        "        return cls(value)\n"
        "\n"
        "    @staticmethod\n"
        "    def accepts(value):\n"
        "        return value is not None\n"
    )

    result = lift_source(source, "shape.py")

    box = _class_shape(result.ir, "Box")
    assert box["status"] == "closed"
    assert box["openReasons"] == []
    assert box["assumptions"] == [
        "presence-guaranteed-assuming-standard-construction-via-__init__",
        "not-robust-to-__new__-or-pickle-bypass",
        "not-robust-to-cross-module-monkey-patch-or-delete",
    ]

    attrs = _entries_by_name(box["attributes"])
    assert attrs["species"]["memberKind"] == "class-attribute"
    assert attrs["species"]["presenceSource"] == "class-body-assignment"
    assert attrs["value"]["memberKind"] == "instance-attribute"
    assert attrs["value"]["presenceSource"] == "unconditional-init-assignment"
    assert attrs["value"]["slotBacked"] is True
    assert "declared_only" not in attrs

    slots = _entries_by_name(box["permittedAttributes"])
    assert slots["value"]["memberKind"] == "slot"
    assert slots["value"]["guaranteesPresence"] is False
    assert slots["declared_only"]["memberKind"] == "slot"
    assert slots["declared_only"]["guaranteesPresence"] is False
    assert (
        slots["declared_only"]["note"]
        == "slot-membership alone does not discharge presence"
    )

    methods = _entries_by_name(box["methods"])
    assert methods["__init__"]["methodKind"] == "instance"
    assert methods["__init__"]["instanceReceiver"] == "self"
    assert methods["from_value"]["methodKind"] == "classmethod"
    assert methods["from_value"]["instanceReceiver"] is None
    assert methods["from_value"]["classReceiver"] == "cls"
    assert methods["accepts"]["methodKind"] == "staticmethod"
    assert methods["accepts"]["instanceReceiver"] is None
    assert "attribute_present" not in _canon(result.ir)


def test_class_shape_taxonomy_opens_soundness_boundary_cases() -> None:
    source = (
        "class External(Base):\n"
        "    def __init__(self):\n"
        "        self.value = 1\n"
        "\n"
        "class OverrideSetattr:\n"
        "    def __setattr__(self, name, value):\n"
        "        object.__setattr__(self, name, value)\n"
        "\n"
        "    def __init__(self):\n"
        "        self.value = 1\n"
        "\n"
        "class DeletedElsewhere:\n"
        "    def __init__(self):\n"
        "        self.value = 1\n"
        "\n"
        "    def drop(self, flag):\n"
        "        if flag:\n"
        "            del self.value\n"
        "\n"
        "class DynamicMutation:\n"
        "    def __init__(self):\n"
        "        self.value = 1\n"
        "\n"
        "    def mutate(self):\n"
        "        setattr(self, 'late', 2)\n"
        "        delattr(self, 'value')\n"
        "\n"
        "class WithProperty:\n"
        "    @property\n"
        "    def value(self):\n"
        "        return 1\n"
        "\n"
        "class ReceiverKinds:\n"
        "    def __init__(self):\n"
        "        self.value = 1\n"
        "\n"
        "    @classmethod\n"
        "    def bad(cls):\n"
        "        cls.class_value = 2\n"
        "        return cls.class_value\n"
        "\n"
        "    @staticmethod\n"
        "    def helper(obj):\n"
        "        obj.static_value = 3\n"
    )

    result = lift_source(source, "taxonomy.py")

    external = _class_shape(result.ir, "External")
    assert external["status"] == "open"
    assert "non-local-base" in external["openReasons"]

    override = _class_shape(result.ir, "OverrideSetattr")
    assert override["status"] == "open"
    assert "setattr-override-in-mro" in override["openReasons"]

    deleted = _class_shape(result.ir, "DeletedElsewhere")
    assert deleted["status"] == "open"
    assert "deleted-instance-attribute" in deleted["openReasons"]
    assert "value" not in _entries_by_name(deleted["attributes"])
    deleted_open_attrs = _entries_by_name(deleted["openAttributes"])
    assert "deleted-in-method" in deleted_open_attrs["value"]["reasons"]

    dynamic = _class_shape(result.ir, "DynamicMutation")
    assert dynamic["status"] == "open"
    assert "dynamic-setattr" in dynamic["openReasons"]
    assert "dynamic-delattr" in dynamic["openReasons"]
    assert "late" not in _entries_by_name(dynamic["attributes"])
    assert "value" not in _entries_by_name(dynamic["attributes"])

    prop = _class_shape(result.ir, "WithProperty")
    assert prop["status"] == "open"
    assert "property-descriptor" in prop["openReasons"]
    assert "value" not in _entries_by_name(prop["attributes"])

    receivers = _class_shape(result.ir, "ReceiverKinds")
    receiver_attrs = _entries_by_name(receivers["attributes"])
    assert set(receiver_attrs) == {"value"}
    receiver_methods = _entries_by_name(receivers["methods"])
    assert receiver_methods["bad"]["methodKind"] == "classmethod"
    assert receiver_methods["bad"]["instanceReceiver"] is None
    assert receiver_methods["helper"]["methodKind"] == "staticmethod"
    assert receiver_methods["helper"]["instanceReceiver"] is None

    for shape in _class_shapes(result.ir):
        assert (
            "presence-guaranteed-assuming-standard-construction-via-__init__"
            in shape["assumptions"]
        )
        assert "not-robust-to-__new__-or-pickle-bypass" in shape["assumptions"]
        assert (
            "not-robust-to-cross-module-monkey-patch-or-delete" in shape["assumptions"]
        )


def test_class_shape_lift_is_soundness_inert_for_attribute_panic_loci() -> None:
    source = (
        "class Safe:\n"
        "    def __init__(self):\n"
        "        self.value = 1\n"
        "\n"
        "    def read(self):\n"
        "        return self.value\n"
    )

    result = lift_source(source, "inert.py")

    read_contract = _contract(result.ir, ".Safe.read")
    read_body = read_contract["post"]["args"][1]
    loci = _runtime_failure_loci(read_contract)
    assert [locus["subkind"] for locus in loci] == ["attribute-access"]
    assert [locus.get("exceptionClass") for locus in loci] == ["AttributeError"]
    assert read_contract["effects"] == [{"kind": "panics"}]
    assert "attribute_present" not in _canon(result.ir)
    assert "cf_guarded" not in _ctor_names(read_body)


def test_known_receiver_attribute_access_carries_attribute_safety_obligation() -> None:
    source = (
        "class Safe:\n"
        "    def __init__(self):\n"
        "        self.value = 1\n"
        "\n"
        "    def read(self):\n"
        "        return self.value\n"
    )

    result = lift_source(source, "shape.py")

    loci = _runtime_failure_loci(_contract(result.ir, ".Safe.read"))
    assert len(loci) == 1
    assert loci[0]["subkind"] == "attribute-access"
    assert loci[0]["attributeSafety"] == {
        "schemaVersion": "1",
        "kind": "python:attribute-safety-obligation",
        "receiverClass": "shape.Safe",
        "receiverQualname": "Safe",
        "receiverName": "self",
        "attribute": "value",
    }


def test_unknown_receiver_attribute_access_stays_untyped_and_unproven() -> None:
    result = lift_source("def read(obj):\n    return obj.value\n", "unknown.py")

    loci = _runtime_failure_loci(_contract(result.ir, ".read"))
    assert len(loci) == 1
    assert loci[0]["subkind"] == "attribute-access"
    assert "attributeSafety" not in loci[0]


def test_hasattr_known_receiver_lifts_attribute_present_cf_guarded_fact() -> None:
    source = (
        "class Maybe:\n"
        "    def __init__(self, flag):\n"
        "        if flag:\n"
        "            self.maybe = 1\n"
        "\n"
        "    def read(self):\n"
        "        if hasattr(self, 'maybe'):\n"
        "            return self.maybe\n"
        "        return 0\n"
    )

    result = lift_source(source, "maybe.py")

    body = _contract(result.ir, ".Maybe.read")["post"]["args"][1]
    assert isinstance(body, dict)
    assert body["name"] == "python:seq"
    guarded_if = body["args"][0]
    assert guarded_if["name"] == "cf_ite"
    condition, then_branch, else_branch = guarded_if["args"]
    assert condition["name"] == "python:call"
    assert then_branch["name"] == "cf_guarded"
    assert then_branch["args"][0] == {
        "kind": "ctor",
        "name": "attribute_present",
        "args": [
            {"kind": "var", "name": "self"},
            {
                "kind": "const",
                "value": "maybe",
                "sort": {"kind": "primitive", "name": "String"},
            },
        ],
    }
    assert else_branch["name"] == "python:pass"
    assert body["args"][1]["name"] == "python:return"
    loci = _runtime_failure_loci(_contract(result.ir, ".Maybe.read"))
    assert len(loci) == 1
    assert loci[0]["attributeSafety"]["receiverClass"] == "maybe.Maybe"
    assert loci[0]["attributeSafety"]["attribute"] == "maybe"


def test_class_shapes_are_absent_for_class_free_units() -> None:
    result = lift_source("def f(x):\n    return x + 1\n", "plain.py")

    source_unit = _source_unit_contract(result.ir)
    assert "classShapes" not in source_unit


def test_class_shapes_are_strippably_additive_for_class_units() -> None:
    result = lift_source(
        "class Box:\n"
        "    species = 'container'\n"
        "\n"
        "    def __init__(self):\n"
        "        self.value = 1\n",
        "additive.py",
    )

    source_unit = _source_unit_contract(result.ir)
    assert "classShapes" in source_unit
    stripped_ir = [
        (
            {key: value for key, value in item.items() if key != "classShapes"}
            if item is source_unit
            else item
        )
        for item in result.ir
    ]
    assert canonical_json_bytes(result.ir) != canonical_json_bytes(stripped_ir)
    assert "classShapes" not in _source_unit_contract(stripped_ir)


def test_rpc_initialize_declares_python_source_draft() -> None:
    result = initialize_result()

    assert result["version"] == "0.1.0-draft"
    assert result["protocol_version"] == "sugar-lift/1"
    assert result["dialect"] == "python-source"
    assert result["capabilities"]["authoring_surfaces"] == ["python-source"]
    assert result["capabilities"]["emits_signed_mementos"] is False


def test_checked_in_project_registers_python_source_lift_surface() -> None:
    entries = _plugin_entries(ROOT / "implementations/python/.sugar/config.toml")

    assert {
        "name": "python-source",
        "kind": "lift",
        "surface": "python-source",
    } in entries


def test_checked_in_python_source_manifest_invokes_module_form_and_declares_kit() -> (
    None
):
    manifest = _python_source_manifest()

    assert manifest["command"] == [
        "python3",
        "-m",
        "sugar_lift_python_source",
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
    assert declaration["result"]["kit"]["id"] == "python-source"
    assert declaration["result"]["effectLeaves"] == RUNTIME_FAILURE_EFFECT_LEAVES


def test_kit_declaration_returns_python_source_lift_surface() -> None:
    response = dispatch(
        {"jsonrpc": "2.0", "id": 2, "method": KIT_DECLARATION_RPC_METHOD}
    )

    assert "error" not in response, response
    result = response["result"]
    assert result["kit"] == {
        "id": "python-source",
        "language": "python",
        "version": "0.1.0-draft",
    }
    required_by_name = {
        method["name"]: method["required"] for method in result["rpc"]["methods"]
    }
    assert required_by_name == {
        "initialize": True,
        KIT_DECLARATION_RPC_METHOD: True,
        "lift": True,
        "compile": False,
        "shutdown": False,
    }
    assert result["proofResolution"] == {"strategy": "pip"}
    assert result["effectKinds"] == ["panic-freedom"]
    assert result["effectLeaves"] == RUNTIME_FAILURE_EFFECT_LEAVES
    assert all("subkind" not in leaf for leaf in result["effectLeaves"])
    assert result["guardPredicates"] == [
        {
            "surface": "python-source",
            "local": "is_some",
            "concept": "concept:panic-freedom.option.some",
        },
        {
            "surface": "python-source",
            "local": "is_none",
            "concept": "concept:panic-freedom.option.none",
        },
    ]
    assert result["controlCarriers"] == [
        {
            "surface": "python-source",
            "local": "cf_guarded",
            "concept": "concept:panic-freedom.guard",
        },
        {
            "surface": "python-source",
            "local": "cf_ite",
            "concept": "concept:panic-freedom.choice",
        },
    ]
    assert result["residueCategories"] == []
