"""Concrete comprehensions dissolve to displays; symbolic/lazy shapes stay loud."""

import tempfile

import pytest

from sugar_lift_python_source.source_oracle import path_source
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


def test_setcomp_over_concrete_range_dissolves():
    term = _out("def A():\n    return {x + 1 for x in range(3)}\n")
    assert term.name == "python:set"
    assert [arg.value for arg in term.args] == [1, 2, 3]


def test_setcomp_preserves_duplicate_elimination():
    term = _out("def A():\n    return {x % 2 for x in range(4)}\n")
    assert [arg.value for arg in term.args] == [0, 1]


def test_dictcomp_preserves_last_value_for_duplicate_key():
    term = _out("def A():\n    return {0: x for x in range(3)}\n")
    assert len(term.args) == 1
    assert (term.args[0].args[0].value, term.args[0].args[1].value) == (0, 2)


@pytest.mark.parametrize(
    "source",
    [
        "[x for x in xs]",
        "{x for x in xs}",
        "{x: x for x in xs}",
    ],
)
def test_symbolic_iterable_comprehensions_stay_loud(source):
    with pytest.raises(SugarNotWritten):
        _fn(f"def A(xs):\n    return {source}\n").sugar()


def test_generator_directly_consumed_by_sum_stays_loud_without_builtin_identity():
    with pytest.raises(SugarNotWritten):
        _fn("def A():\n    return sum(x + 1 for x in range(3))\n").sugar()


def test_generator_directly_consumed_by_list_stays_loud_without_builtin_identity():
    with pytest.raises(SugarNotWritten):
        _fn("def A():\n    return list(x + 1 for x in range(3))\n").sugar()


def test_bare_generator_stays_loud():
    with pytest.raises(SugarNotWritten):
        _fn("def A():\n    return (x for x in range(3))\n").sugar()


def test_generator_passed_to_unknown_call_stays_loud():
    with pytest.raises(SugarNotWritten):
        _fn("def A():\n    return consume(x for x in range(3))\n").sugar()


def test_shadowed_range_stays_loud():
    with pytest.raises(SugarNotWritten):
        _fn("def A(range):\n    return [x for x in range(3)]\n").sugar()


def test_shadowed_materializer_stays_loud():
    with pytest.raises(SugarNotWritten):
        _fn("def A(sum):\n    return sum(x for x in [1, 2])\n").sugar()


def test_locally_rebound_materializer_stays_loud():
    with pytest.raises(SugarNotWritten):
        _fn(
            "def A(consume):\n"
            "    sum = consume\n"
            "    return sum(x for x in [1, 2])\n"
        ).sugar()


def test_module_rebound_materializer_stays_loud():
    with pytest.raises(SugarNotWritten):
        _fn(
            "sum = consume\n"
            "def A():\n"
            "    return sum(x for x in [1, 2])\n"
        ).sugar()


@pytest.mark.parametrize("consumer", ["any", "all"])
def test_short_circuit_generator_consumer_stays_loud(consumer):
    with pytest.raises(SugarNotWritten):
        _fn(f"def A():\n    return {consumer}(x for x in [0, 1])\n").sugar()


def test_every_filter_must_be_ground_decidable():
    with pytest.raises(SugarNotWritten):
        _fn(
            "def A(limit):\n"
            "    return [x for x in [0] if x > 0 if x > limit]\n"
        ).sugar()


@pytest.mark.parametrize(
    "source",
    [
        "[y for x in [[1]] for y in x]",
        "[[y for y in [1]] for x in [1]]",
        "[(y := x) for x in [1]]",
        "[x for x in range(129)]",
    ],
)
def test_unsupported_comprehension_structures_stay_loud(source):
    with pytest.raises(SugarNotWritten):
        _fn(f"def A():\n    return {source}\n").sugar()
