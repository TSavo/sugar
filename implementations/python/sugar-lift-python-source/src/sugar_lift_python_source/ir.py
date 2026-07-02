from __future__ import annotations

from typing import Any

Json = dict[str, Any]


def prim_sort(name: str) -> Json:
    return {"kind": "primitive", "name": name}


def true_formula() -> Json:
    return {"kind": "atomic", "name": "true", "args": []}


def eq_formula(lhs: Json, rhs: Json) -> Json:
    return {"kind": "atomic", "name": "=", "args": [lhs, rhs]}


def var(name: str) -> Json:
    return {"kind": "var", "name": name}


def const(value: object, sort_name: str) -> Json:
    return {"kind": "const", "value": value, "sort": prim_sort(sort_name)}


def int_const(value: int) -> Json:
    return const(int(value), "Int")


def bool_const(value: bool) -> Json:
    return const(bool(value), "Bool")


def str_const(value: str) -> Json:
    return const(value, "String")


def float_const(value: float) -> Json:
    return {"kind": "const", "value": {"type": "float", "repr": repr(float(value))}}


def bytes_const(value: bytes) -> Json:
    return {"kind": "const", "value": {"type": "bytes", "repr": bytes(value).hex()}}


def complex_const(re: float, im: float) -> Json:
    return {
        "kind": "const",
        "value": {
            "type": "complex",
            "re": repr(float(re)),
            "im": repr(float(im)),
        },
    }


def ellipsis_const() -> Json:
    return {"kind": "const", "value": {"type": "ellipsis"}}


def none_const() -> Json:
    return const(None, "Unit")


def ctor(name: str, *args: Json) -> Json:
    if not name.startswith("python:"):
        raise ValueError(f"operation name must use the Python namespace: {name}")
    local_name = name.removeprefix("python:")
    if local_name in {"unknown", "binop", "skip"}:
        raise ValueError(f"operation name is forbidden: {name}")
    return {"kind": "ctor", "name": name, "args": list(args)}


def substrate_ctor(name: str, *args: Json) -> Json:
    allowed = {"cf_ite", "cf_guarded", "is_none", "is_some", "attribute_present"}
    if name not in allowed:
        raise ValueError(f"unsupported substrate operation name: {name}")
    return {"kind": "ctor", "name": name, "args": list(args)}


def pass_stmt() -> Json:
    return ctor("python:pass", none_const())


def seq(first: Json, second: Json) -> Json:
    return ctor("python:seq", first, second)


def fold_seq(statements: list[Json]) -> Json:
    if not statements:
        return pass_stmt()
    result = statements[0]
    for statement in statements[1:]:
        result = seq(result, statement)
    return result


def locus(path: str, line: int, col: int = 1) -> Json:
    return {"file": path, "line": int(line), "col": int(col)}


def function_contract(
    *,
    fn_name: str,
    formals: list[str],
    body_term: Json,
    effects: list[Json],
    source_path: str,
    line: int,
    precondition: Json | None = None,
    panic_loci: list[Json] | None = None,
    parameter_shape: list[Json] | None = None,
) -> Json:
    contract = {
        "schemaVersion": "1",
        "kind": "function-contract",
        "fnName": fn_name,
        "formals": list(formals),
        "formalSorts": [prim_sort("Value") for _ in formals],
        "returnSort": prim_sort("Value"),
        "pre": precondition if precondition is not None else true_formula(),
        "post": eq_formula(var("return_value"), body_term),
        "bodyCid": None,
        "effects": effects,
        "locus": locus(source_path, line, 1),
        "autoMintedMementos": [],
    }
    if panic_loci:
        contract["panicLoci"] = list(panic_loci)
    if parameter_shape:
        contract["parameterShape"] = list(parameter_shape)
    return contract


def source_unit_contract(
    *,
    source_path: str,
    source: str,
    operational_term: Json,
    class_shapes: list[Json] | None = None,
) -> Json:
    contract = {
        "schemaVersion": "1",
        "kind": "function-contract",
        "fnName": f"<source-unit:{source_path}>",
        "formals": [],
        "formalSorts": [],
        "returnSort": prim_sort("Stmt"),
        "pre": true_formula(),
        "post": eq_formula(
            var("return_value"),
            ctor("python:source-unit", str_const(source), operational_term),
        ),
        "bodyCid": None,
        "effects": [],
        "locus": locus(source_path, 1, 1),
        "autoMintedMementos": [],
    }
    if class_shapes is not None:
        contract["classShapes"] = list(class_shapes)
    return contract
