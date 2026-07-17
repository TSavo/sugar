from __future__ import annotations

from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import audit_lift_file
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

MODULE_BINDINGS = (
    "GOOD = 7\n"
    "BAD = (yield 1)\n"
    "\n"
    "def good():\n"
    "    return GOOD\n"
    "\n"
    "def bad():\n"
    "    return BAD\n"
)


def _module_file_post(filename: str) -> dict:
    source = "def module_path():\n    return __file__\n"
    payload, gaps = audit_lift_file(source, filename)
    assert gaps == []
    return next(row for row in payload.ir if row.name.endswith(".module_path")).post[
        "args"
    ][1]


def test_module_file_seeds_the_exact_source_filename() -> None:
    assert _module_file_post("known/module.py") == {
        "kind": "const",
        "sort": {"kind": "primitive", "name": "String"},
        "value": "known/module.py",
    }


def test_module_file_binding_discriminates_source_filenames() -> None:
    assert _module_file_post("left.py") != _module_file_post("right.py")


def test_module_file_assertion_conserves_mass() -> None:
    source = 'def test_module_file():\n    assert __file__ == "known/module.py"\n'
    payload, _gaps = audit_lift_file(source, "known/module.py")
    assertions = account_lift_coverage(
        census_source(source, file="known/module.py"), payload.to_rpc()
    ).to_json()["assertions"]
    assert assertions["stated"] == 1
    assert assertions["silently_unaccounted"] == 0


def _module_builtins_post() -> dict:
    source = "def builtin_namespace():\n    return __builtins__\n"
    payload, gaps = audit_lift_file(source, "builtins_module.py")
    assert gaps == []
    return next(
        row for row in payload.ir if row.name.endswith(".builtin_namespace")
    ).post["args"][1]


def test_module_builtins_seeds_the_interpreter_namespace_alias() -> None:
    assert _module_builtins_post() == {
        "kind": "ctor",
        "name": "python:import_alias",
        "args": [
            {
                "kind": "const",
                "sort": {"kind": "primitive", "name": "String"},
                "value": "__builtins__",
            },
            {
                "kind": "const",
                "sort": {"kind": "primitive", "name": "String"},
                "value": "builtins",
            },
        ],
    }


def test_module_builtins_assertion_conserves_mass() -> None:
    source = (
        "def test_builtin_namespace():\n" "    assert __builtins__ == __builtins__\n"
    )
    payload, gaps = audit_lift_file(source, "builtins_module.py")
    rpc = payload.to_rpc()
    assertions = account_lift_coverage(
        census_source(source, file="builtins_module.py"), rpc
    ).to_json()["assertions"]

    assert gaps == []
    assert rpc["effects"] == []
    assert assertions["stated"] == 1
    assert assertions["lifted_cited"] == 1
    assert assertions["silently_unaccounted"] == 0


def test_module_builtins_truthful_and_lying_twins_refute(tmp_path) -> None:
    truthful = run_source_through_real_solver(
        tmp_path / "truthful",
        "def test_builtin_namespace(value):\n"
        "    assert (__builtins__ == __builtins__)"
        " & (value == 1) & (value == 1)\n",
    )
    lying = run_source_through_real_solver(
        tmp_path / "lying",
        "def test_builtin_namespace(value):\n"
        "    assert (__builtins__ == __builtins__)"
        " & (value == 1) & (not (value == 1))\n",
    )

    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"
    assert "NameSugar" in truthful.selected_sugars
    assert "NameSugar" in lying.selected_sugars


def test_liftable_module_assignment_seeds_constructed_floor_value() -> None:
    payload, gaps = audit_lift_file(MODULE_BINDINGS, "module_constants.py")

    good = next(row for row in payload.ir if row.name == "good")
    assert good.post["args"][1] == {
        "kind": "const",
        "sort": {"kind": "primitive", "name": "Int"},
        "value": 7,
    }
    assert not any(gap.label.endswith(":4:0") for gap in gaps)


def test_unliftable_module_rhs_does_not_bind_name_or_poison_sibling() -> None:
    payload, gaps = audit_lift_file(MODULE_BINDINGS, "module_constants.py")

    assert any(row.name == "good" for row in payload.ir)
    bad_gap = next(gap for gap in gaps if gap.label.endswith(":7:0"))
    assert "observed=BAD requested=value" in bad_gap.message


def test_module_binding_uses_factory_floor_not_parallel_symbolic_spelling() -> None:
    payload, _gaps = audit_lift_file(MODULE_BINDINGS, "module_constants.py")
    good = next(row for row in payload.ir if row.name == "good")

    assert good.post["args"][1]["kind"] == "const"
    assert good.post["args"][1]["value"] == 7
    assert "python:module" not in repr(good.post)


def test_full_datetime_module_constants_expose_target_assertions(
    cpython_311_datetime_path,
) -> None:
    path = cpython_311_datetime_path
    source = path.read_text(encoding="utf-8")
    payload, gaps = audit_lift_file(source, str(path))
    assertions = account_lift_coverage(
        census_source(source, file=str(path)), payload.to_rpc()
    ).to_json()["assertions"]

    assert assertions["stated"] == 45
    assert assertions["lifted_cited"] == 45
    assert assertions["refused_loud"] == 0
    assert assertions["silently_unaccounted"] == 0
    # Module/helper range + ord calendar asserts (SHA-pinned artifact loci).
    assert {
        locus["line"]
        for locus in assertions["lifted_loci"]
        if locus["line"] in {67, 75, 160}
    } == {67, 75, 160}
    assert {
        locus["line"]
        for locus in assertions["lifted_loci"]
        if locus["line"] in {147, 153}
    } == {147, 153}
    assert gaps == []
