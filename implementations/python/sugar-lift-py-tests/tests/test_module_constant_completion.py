from __future__ import annotations

from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import audit_lift_file
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.context.reduce_context import ReduceContext
from sugar_lift_py_tests.factory.build import default_catalog

SAME_MODULE_TABLE_DIG = (
    "TABLE = (10, 20)\n"
    "\n"
    "def lookup(index):\n"
    "    value = TABLE[index]\n"
    "    return value\n"
    "\n"
    "def caller(index):\n"
    "    return lookup(index) + 1\n"
)

COMPOSED_MODULE_CONSTANTS = (
    "BASE = 10\n"
    "OFFSET = BASE + 2\n"
    "TABLE = [BASE, OFFSET]\n"
    "\n"
    "def select(index):\n"
    "    return TABLE[index] + OFFSET\n"
)

GROUND_BINDING_DIG_DISCRIMINATION = (
    "def days(year):\n"
    "    y = year - 1\n"
    "    return y * 365 + y // 4 - y // 100 + y // 400\n"
    "\n"
    "DI4 = days(5)\n"
    "DI100 = days(101)\n"
    "DI400 = days(401)\n"
    "assert DI4 == 4 * 365 + 1\n"
    "assert DI400 == 4 * DI100 + 1\n"
)


def _expand_term(term, table):
    if isinstance(term, list):
        return [_expand_term(item, table) for item in term]
    if not isinstance(term, dict):
        return term
    if term.get("kind") == "term-ref":
        return _expand_term(table[term["cid"]], table)
    return {key: _expand_term(value, table) for key, value in term.items()}


def test_reduce_context_carries_module_rewrite_testimony_state() -> None:
    build_ctx = FactoryBuildContext(filename="nested.py", catalog=default_catalog())
    build_ctx.module_rewrite_log.append(("A", "f(1)", "nested.py", 1, None))
    reduce_ctx = ReduceContext.derived(build_ctx, owner="nested dig")

    assert reduce_ctx.module_rewrite_log is build_ctx.module_rewrite_log
    assert reduce_ctx.with_temporal(reduce_ctx.temporal).module_rewrite_log is (
        build_ctx.module_rewrite_log
    )
    assert reduce_ctx.prefer_ground_module_bindings is False


def test_same_module_callee_dig_preserves_module_constant_temporal() -> None:
    payload, gaps = audit_lift_file(SAME_MODULE_TABLE_DIG, "module_table.py")

    assert not gaps
    caller = next(row for row in payload.ir if row.name == "caller")
    assert "call:lookup" in repr(caller.post)
    assert "TABLE" not in repr(gaps)


def test_same_module_tuple_constant_uses_factory_built_tuple_floor() -> None:
    payload, _gaps = audit_lift_file(SAME_MODULE_TABLE_DIG, "module_table.py")
    lookup = next(row for row in payload.ir if row.name == "lookup")

    assert "py.subscript" in repr(lookup.post)
    assert "tuple" in repr(lookup.post)
    assert "python:module" not in repr(lookup.post)


def test_module_constants_compose_arithmetic_and_list_tables_in_order() -> None:
    payload, gaps = audit_lift_file(COMPOSED_MODULE_CONSTANTS, "composed.py")

    assert not gaps
    select = next(row for row in payload.ir if row.name == "select")
    assert "py.subscript" in repr(select.post)
    assert "array" in repr(select.post)
    assert "python:module" not in repr(select.post)


def test_module_constant_dig_keeps_call_literal_and_records_testimony() -> None:
    payload, gaps = audit_lift_file(
        GROUND_BINDING_DIG_DISCRIMINATION, "ground_binding.py"
    )
    wire = payload.to_rpc()
    assertion = next(
        row
        for row in wire["ir"]
        if row.get("proofirProvenance", {}).get("constructionSite", {}).get("line") == 8
    )
    inv = _expand_term(assertion["inv"], wire["termTable"])

    assert not gaps
    assert inv["name"] == "py.eq"
    assert "call:days" in repr(inv)
    assert assertion["proofirProvenance"]["warrants"][1]["floorChain"] == [
        "DI4 = days(5)"
    ]


def test_ground_module_bindings_are_operands_when_definition_dig_loses_groundness() -> (
    None
):
    payload, gaps = audit_lift_file(
        GROUND_BINDING_DIG_DISCRIMINATION, "ground_binding.py"
    )
    wire = payload.to_rpc()
    assertion = next(
        row
        for row in wire["ir"]
        if row.get("proofirProvenance", {}).get("constructionSite", {}).get("line") == 9
    )
    inv = _expand_term(assertion["inv"], wire["termTable"])
    floor_chains = [
        warrant["floorChain"]
        for warrant in assertion["proofirProvenance"]["warrants"]
        if warrant["kind"] == "Derived"
    ]

    assert not gaps
    assert inv["name"] == "="
    assert inv["name"] != "py.eq"
    assert "call:days" not in repr(inv)
    assert "146097" in repr(inv)
    assert "36524" in repr(inv)
    assert floor_chains == [["DI400 = days(401)"], ["DI100 = days(101)"]]


def test_datetime_93_and_97_discriminate_call_literal_from_ground_binding(
    cpython_311_datetime_path,
) -> None:
    source = "".join(
        cpython_311_datetime_path.read_text(encoding="utf-8").splitlines(keepends=True)[
            :97
        ]
    )
    payload, gaps = audit_lift_file(source, str(cpython_311_datetime_path))
    wire = payload.to_rpc()
    rows = {
        row["proofirProvenance"]["constructionSite"]["line"]: row
        for row in wire["ir"]
        if row.get("proofirProvenance", {}).get("constructionSite", {}).get("line")
        in {93, 97}
    }
    inv_93 = _expand_term(rows[93]["inv"], wire["termTable"])
    inv_97 = _expand_term(rows[97]["inv"], wire["termTable"])

    assert not gaps
    assert inv_93["name"] == "py.eq"
    assert inv_97["name"] == "="
    assert inv_97["name"] != "py.eq"
    assert "call:_days_before_year" in repr(inv_93)
    assert "call:_days_before_year" not in repr(inv_97)
    assert "146097" in repr(inv_97)
    assert "36524" in repr(inv_97)
    assert [
        warrant["floorChain"]
        for warrant in rows[93]["proofirProvenance"]["warrants"]
        if warrant["kind"] == "Derived"
    ] == [["_DI4Y = _days_before_year(5)"]]
    assert [
        warrant["floorChain"]
        for warrant in rows[97]["proofirProvenance"]["warrants"]
        if warrant["kind"] == "Derived"
    ] == [
        ["_DI400Y = _days_before_year(401)"],
        ["_DI100Y = _days_before_year(101)"],
    ]
    assert [
        warrant["locus"]["line"]
        for warrant in rows[97]["proofirProvenance"]["warrants"]
        if warrant["kind"] == "Derived"
    ] == [87, 88]


def test_full_datetime_module_globals_survive_same_module_dig(
    cpython_311_datetime_path,
) -> None:
    path = cpython_311_datetime_path
    source = path.read_text(encoding="utf-8")
    payload, gaps = audit_lift_file(source, str(path), hold_panic=True)
    assertions = account_lift_coverage(
        census_source(source, file=str(path)), payload.to_rpc()
    ).to_json()["assertions"]
    messages = [gap.message for gap in gaps]

    assert assertions["lifted_cited"] == 14
    assert assertions["refused_loud"] == 31
    assert assertions["silently_unaccounted"] == 0
    assert not any("observed=_DAYS_BEFORE_MONTH" in message for message in messages)
    assert any(
        ":175:4" in message and "observed=Try requested=statement" in message
        for message in messages
    )
