from __future__ import annotations

import ast

import pytest

from factory_reduce import reduce_value

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import ListValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import complete_value


def _reduce_with_module(source: str, expression: str):
    module = ast.parse(source)
    resolver = {
        statement.name: statement
        for statement in module.body
        if isinstance(statement, (ast.ClassDef, ast.FunctionDef))
    }
    context = FactoryBuildContext(
        filename="t.py",
        catalog=default_catalog(),
        name_resolver=resolver,
    )
    node = ast.parse(expression, mode="eval").body
    return complete_value(
        context.build_body(node, SugarRole.TERM).reduce(context),
        owner="exact len result test",
    )


@pytest.mark.parametrize(
    ("receiver", "expected_length"),
    (("[]", 0), ("[True]", 1), ("[1, 2, 3]", 3)),
)
def test_builtin_len_of_exact_list_constructs_integer_term(
    receiver: str, expected_length: int
) -> None:
    value = reduce_value(f"len({receiver})")

    assert value == TermValue(expected_length)
    assert type(value.value) is int


@pytest.mark.parametrize(
    ("receiver", "expected"),
    (
        ("[]", ()),
        ("[10, 20]", (7, 7)),
        ("[10, 20, 30]", (7, 7, 7)),
    ),
)
def test_exact_list_len_drives_exact_list_repetition_through_real_ast(
    receiver: str, expected: tuple[int, ...]
) -> None:
    value = reduce_value(f"[7] * len({receiver})")

    assert value == ListValue(tuple(TermValue(item) for item in expected))


def test_symbolic_len_receiver_cannot_construct_a_repetition_count() -> None:
    with pytest.raises(
        FactoryPanic,
        match="ListValue.*stand on the multiplication floor",
    ):
        reduce_value(
            "[7] * len(items)",
            {"items": SymbolicValue(make_var("items"))},
        )


def test_object_without_owned_exact_len_stays_loud_despite_same_leaf_elsewhere() -> (
    None
):
    source = """\
class HasLen:
    def __len__(self):
        return 2

class MissingLen:
    pass
"""

    with pytest.raises(
        FactoryPanic,
        match=r"MissingLen\.__len__.*constructor-bound method",
    ):
        _reduce_with_module(source, "[7] * len(MissingLen())")
