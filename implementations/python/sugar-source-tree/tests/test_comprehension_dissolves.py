"""Concrete comprehensions dissolve; simple symbolic forms retain coordinates."""

import json
import tempfile

import pytest

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.ir import (
    ctor,
    encode_jcs,
    make_var,
    num,
    str_const,
    subst_var_in_term,
    term_to_value,
)
from sugar_lift_py_tests.proofir.formulas import _free_vars_in_ir_term
from sugar_lift_py_tests.proofir.sorts import Sort
from sugar_lift_py_tests.proofir.terms import term_from_ir
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _fn(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return next(SourceFile(path_source(path)).functions())


def _out(src):
    return _fn(src).sugar().desugar().value.post().args[1]


def test_filtered_listcomp_keeps_ground_true_elements():
    term = _out("def A():\n    return [x for x in [1, 2, 3, 4] if x > 2]\n")
    assert term.name == "array"
    assert [arg.value for arg in term.args] == [3, 4]


def test_undecidable_filtered_listcomp_stays_loud():
    with pytest.raises(SugarNotWritten):
        _fn("def A(limit):\n    return [x for x in [1, 2] if x > limit]\n").sugar()


def test_dictcomp_over_concrete_range_dissolves():
    term = _out("def A():\n    return {x: x + 10 for x in range(2)}\n")
    assert term.name == "python:dict"
    assert [(item.args[0].value, item.args[1].value) for item in term.args] == [
        (0, 10),
        (1, 11),
    ]


def test_filtered_dictcomp_keeps_only_ground_true_entries():
    term = _out(
        "def A():\n"
        "    return {item: item + 10 for item in [0, 1, 2, 3] if item % 2 == 0}\n"
    )
    assert term.name == "python:dict"
    assert [(item.args[0].value, item.args[1].value) for item in term.args] == [
        (0, 10),
        (2, 12),
    ]


def test_setcomp_over_concrete_range_dissolves():
    term = _out("def A():\n    return {x + 1 for x in range(3)}\n")
    assert term.name == "python:set"
    assert [arg.value for arg in term.args] == [1, 2, 3]


def test_filtered_setcomp_keeps_only_ground_true_members():
    term = _out("def A():\n" "    return {item for item in [0, 1, 2, 3] if item > 1}\n")
    assert term.name == "python:set"
    assert [arg.value for arg in term.args] == [2, 3]


@pytest.mark.parametrize(
    "source",
    [
        "{item for item in [0, 1, 2, 3] if keep(item)}",
        "{item: item + 10 for item in [0, 1, 2, 3] if keep(item)}",
    ],
)
def test_filtered_set_and_dict_do_not_fabricate_symbolic_guard_verdict(source):
    with pytest.raises(SugarNotWritten):
        _fn(f"def A(keep):\n    return {source}\n").sugar()


def test_setcomp_preserves_duplicate_elimination():
    term = _out("def A():\n    return {x % 2 for x in range(4)}\n")
    assert [arg.value for arg in term.args] == [0, 1]


def test_dictcomp_preserves_last_value_for_duplicate_key():
    term = _out("def A():\n    return {0: x for x in range(3)}\n")
    assert len(term.args) == 1
    assert (term.args[0].args[0].value, term.args[0].args[1].value) == (0, 2)


@pytest.mark.parametrize(
    ("source", "coordinate", "transform"),
    [
        ("[f(x) for x in xs]", "py.listcomp", "call:f"),
        ("{f(x) for x in xs}", "py.setcomp", "call:f"),
        ("{x: f(x) for x in xs}", "py.dictcomp", "call:f"),
        ("(f(x) for x in xs)", "py.generatorexp", "call:f"),
    ],
)
def test_simple_symbolic_comprehension_builds_coordinate(source, coordinate, transform):
    term = _out(f"def A(xs):\n    return {source}\n")
    assert term.name == coordinate
    assert term.args[0].name == "xs"
    assert term.args[1].param_name == "x"
    assert term.args[1].param_sort.name == "Value"
    body = term.args[1].body
    if coordinate == "py.dictcomp":
        assert body.name == "python:dict_entry"
        assert body.args[1].name == transform
    else:
        assert body.name == transform


def test_symbolic_comprehension_serializes_transform_as_real_lambda():
    term = _out("def A(xs, y):\n    return [f(x, y) for x in xs]\n")
    wire = json.loads(encode_jcs(term_to_value(term)))
    transform = wire["args"][1]

    assert transform == {
        "kind": "lambda",
        "paramName": "x",
        "paramSort": {"kind": "primitive", "name": "Value"},
        "body": {
            "kind": "ctor",
            "name": "call:f",
            "args": [
                {"kind": "var", "name": "x"},
                {"kind": "var", "name": "y"},
            ],
        },
    }
    assert _free_vars_in_ir_term(term.args[1]) == frozenset({"y"})
    assert _free_vars_in_ir_term(term) == frozenset({"xs", "y"})

    value_sort = Sort(name="Value", ir_sort=term.args[1].param_sort)
    wrapped = term_from_ir(term.args[1], sort=value_sort)
    assert wrapped.free_vars == frozenset({"y"})
    assert wrapped.free_var_sorts == {"y": value_sort}


def test_old_bound_transform_ctor_is_nonbinding_lying_twin():
    lying = ctor(
        "py.bound_transform",
        [str_const("x"), ctor("call:f", [make_var("x")])],
    )
    wire = json.loads(encode_jcs(term_to_value(lying)))

    assert wire["kind"] == "ctor"
    assert _free_vars_in_ir_term(lying) == frozenset({"x"})


def test_bound_target_is_absent_from_coordinate_free_variables():
    term = _out("def A(xs):\n    return [f(x) for x in xs]\n")
    assert _free_vars_in_ir_term(term) == frozenset({"xs"})


def test_same_spelled_outer_iterable_remains_free_while_element_is_bound():
    term = _out("def A(x):\n    return [f(x) for x in x]\n")
    assert _free_vars_in_ir_term(term) == frozenset({"x"})
    transform = term.args[1]
    assert _free_vars_in_ir_term(transform) == frozenset()
    assert transform.body.name == "call:f"
    assert transform.body.args[0].name == "x"


def test_nested_lambda_same_name_does_not_escape_comprehension_transform():
    term = _out("def A(xs):\n    return [(lambda x: x) for x in xs]\n")
    assert _free_vars_in_ir_term(term) == frozenset({"xs"})


def test_nested_symbolic_listcomp_builds_composed_lambda_binders():
    term = _out(
        "def A(xs, ys, z):\n" "    return [[f(x, y, z) for y in ys] for x in xs]\n"
    )

    assert term.name == "py.listcomp"
    assert term.args[1].param_name == "x"
    inner = term.args[1].body
    assert inner.name == "py.listcomp"
    assert inner.args[1].param_name == "y"
    assert inner.args[1].body.name == "call:f"
    assert _free_vars_in_ir_term(term) == frozenset({"xs", "ys", "z"})


def test_nested_comprehension_iterable_builds_without_flattening():
    term = _out("def A(ys):\n" "    return [f(x) for x in [g(y) for y in ys]]\n")

    assert term.name == "py.listcomp"
    assert term.args[0].name == "py.listcomp"
    assert term.args[0].args[1].param_name == "y"
    assert term.args[1].param_name == "x"
    assert _free_vars_in_ir_term(term) == frozenset({"ys"})


def test_nested_generator_expression_retains_both_lazy_coordinates():
    term = _out("def A(xs, ys):\n" "    return ((f(x, y) for y in ys) for x in xs)\n")

    assert term.name == "py.generatorexp"
    assert term.args[1].param_name == "x"
    inner = term.args[1].body
    assert inner.name == "py.generatorexp"
    assert inner.args[1].param_name == "y"
    assert _free_vars_in_ir_term(term) == frozenset({"xs", "ys"})


@pytest.mark.parametrize(
    ("source", "outer", "inner", "free"),
    [
        (
            "[{f(y) for y in ys} for x in xs]",
            "py.listcomp",
            "py.setcomp",
            {"xs", "ys"},
        ),
        (
            "({y: f(y) for y in ys} for x in xs)",
            "py.generatorexp",
            "py.dictcomp",
            {"xs", "ys"},
        ),
        ("[x for x in {f(y) for y in ys}]", "py.listcomp", "py.setcomp", {"ys"}),
    ],
)
def test_nested_arm_composes_already_built_comprehension_kinds(
    source, outer, inner, free
):
    term = _out(f"def A(xs, ys):\n    return {source}\n")

    assert term.name == outer
    assert inner in {term.args[0].name, term.args[1].body.name}
    assert _free_vars_in_ir_term(term) == frozenset(free)


def test_nested_comprehension_does_not_admit_an_inner_filtered_gap():
    with pytest.raises(SugarNotWritten):
        _fn(
            "def A(xs, ys):\n" "    return [[y for y in ys if keep(y)] for x in xs]\n"
        ).sugar()


@pytest.mark.parametrize(
    "source",
    [
        "{x for x in [y for y in ys]}",
        "{x: x for x in [y for y in ys]}",
    ],
)
def test_list_generator_nested_arm_does_not_widen_set_or_dict(source):
    with pytest.raises(SugarNotWritten):
        _fn(f"def A(ys):\n    return {source}\n").sugar()


def test_bound_target_masks_outer_same_spelling_and_keeps_call_coordinate():
    term = _out("def A(xs):\n" "    x = 999\n" "    return [f(x) for x in xs]\n")
    assert term.name == "py.listcomp"
    assert term.args[1].param_name == "x"
    assert term.args[1].body.name == "call:f"
    assert term.args[1].body.args[0].name == "x"


def test_concrete_generator_builds_lazy_coordinate_without_materializing():
    term = _out("def A():\n    return (f(x) for x in [1, 2])\n")
    assert term.name == "py.generatorexp"
    assert term.args[0].name == "array"
    assert term.args[1].param_name == "x"
    assert term.args[1].body.name == "call:f"


@pytest.mark.parametrize("consumer", ["sum", "list", "consume", "any", "all"])
def test_generator_consumer_points_at_lazy_coordinate(consumer):
    term = _out(f"def A():\n    return {consumer}(x for x in [0, 1])\n")
    assert term.name == f"call:{consumer}"
    assert term.args[0].name == "py.generatorexp"


def test_shadowed_consumer_does_not_materialize_generator():
    term = _out(
        "def A(materialize):\n"
        "    list = materialize\n"
        "    return list(x for x in [0, 1])\n"
    )
    assert term.name == "call:materialize"
    assert term.args[0].name == "py.generatorexp"


def test_list_and_generator_keep_distinct_eager_and_lazy_coordinates():
    eager = _out("def A(xs):\n    return [f(x) for x in xs]\n")
    lazy = _out("def A(xs):\n    return (f(x) for x in xs)\n")
    assert eager.name == "py.listcomp"
    assert lazy.name == "py.generatorexp"
    assert eager.args[1] == lazy.args[1]
    assert eager != lazy


def test_generator_creation_keeps_call_inside_unexecuted_transform_template():
    term = _out("def A(xs):\n    return (f(x) for x in xs)\n")
    transform = term.args[1]
    assert transform.param_name == "x"
    assert transform.body.name == "call:f"
    assert _free_vars_in_ir_term(term) == frozenset({"xs"})


def test_over_fuel_concrete_comprehension_builds_lambda_transform_coordinate():
    term = _out("def A():\n    return [f(x) for x in range(129)]\n")
    assert term.name == "py.listcomp"
    assert term.args[1].param_name == "x"


def test_lambda_substitution_alpha_renames_to_avoid_capture():
    term = _out("def A(xs, y):\n    return [y for x in xs]\n")
    transform = term.args[1]

    substituted = subst_var_in_term(transform, "y", make_var("x"))

    assert substituted.param_name != "x"
    assert substituted.param_sort.name == "Value"
    assert substituted.body.name == "x"
    assert _free_vars_in_ir_term(substituted) == frozenset({"x"})


def test_shadowed_range_is_not_unrolled_but_builds_symbolic_coordinate():
    term = _out("def A(range):\n    return [x for x in range(3)]\n")
    assert term.name == "py.listcomp"
    assert term.args[0].name == "call:range"


def test_every_filter_must_be_ground_decidable():
    with pytest.raises(SugarNotWritten):
        _fn(
            "def A(limit):\n" "    return [x for x in [0] if x > 0 if x > limit]\n"
        ).sugar()


@pytest.mark.parametrize(
    "source",
    [
        "[(y := x) for x in [1]]",
    ],
)
def test_unsupported_comprehension_structures_stay_loud(source):
    with pytest.raises(SugarNotWritten):
        _fn(f"def A():\n    return {source}\n").sugar()


def test_nested_comprehension_substitutes_outer_capture_before_building():
    fn = _fn(
        "def A():\n"
        "    values = [1]\n"
        "    return [[y for y in values] for x in [1]]\n"
    )
    expression = fn.substitute({}).body[-1].value
    nested = expression.elt
    assert nested.generators[0].iter.kind == "List"
    value = expression.sugar().desugar().value
    assert value.term.name == "py.listcomp"
    assert value.term.args[1].body.name == "py.listcomp"
    assert value.term.args[1].body.args[0].name == "array"


def test_walrus_comprehension_substitutes_outer_capture_before_own_gap():
    fn = _fn(
        "def A():\n" "    value = 7\n" "    return [(captured := value) for x in [1]]\n"
    )
    expression = fn.substitute({}).body[-1].value
    assert expression.elt.value.value == 7
    with pytest.raises(SugarNotWritten):
        expression.sugar()


def test_existing_concrete_displays_keep_exact_terms():
    filtered = _out("def A():\n    return [x for x in [1, 2, 3] if x > 1]\n")
    destructured = _out("def A():\n    return [a + b for a, b in [(1, 2), (3, 4)]]\n")
    assert filtered == ctor("array", [num(2), num(3)])
    assert destructured == ctor("array", [num(3), num(7)])
