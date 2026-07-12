from __future__ import annotations

import ast

import pytest

from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    GuardedRaise,
    GuardedReturn,
    SymbolicValue,
)
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.ir import atomic, ctor, make_var, not_, str_const
from sugar_lift_py_tests.lift_rpc import audit_lift_file
from sugar_lift_py_tests.sugar.try_sugar import TrySugar

VENDOR_SHAPE = (
    "try:\n"
    "    fmt = specs[timespec]\n"
    "except KeyError:\n"
    "    raise ValueError('Unknown timespec value')\n"
    "else:\n"
    "    return fmt\n"
)


def _site(source: str) -> SourceFragment:
    return SourceFragment.from_node(ast.parse(source).body[0], "Lib/datetime.py")


def test_try_except_else_keeps_both_exception_faces_guarded() -> None:
    block = compose_block(
        "    " + VENDOR_SHAPE.replace("\n", "\n    "),
        {
            "specs": SymbolicValue(make_var("specs")),
            "timespec": SymbolicValue(make_var("timespec")),
        },
    )

    exception_guard = atomic("py.except", [str_const("KeyError")])
    assert len(block.statements) == 2
    guarded_raise = block.statements[0]
    assert isinstance(guarded_raise, GuardedRaise)
    assert guarded_raise.guards == (exception_guard,)
    assert guarded_raise.effect.exception_name == "ValueError"
    guarded_return = block.statements[1]
    assert isinstance(guarded_return, GuardedReturn)
    assert guarded_return.guards == (not_(exception_guard),)
    assert isinstance(guarded_return.value, CallSiteValue)
    assert guarded_return.value.term == ctor(
        "py.subscript", [make_var("specs"), make_var("timespec")]
    )


@pytest.mark.parametrize(
    "source",
    (
        "try:\n    x = 1\nexcept KeyError:\n    x = 2\nexcept TypeError:\n    x = 3\nelse:\n    x = 4\n",
        "try:\n    x = 1\nexcept KeyError:\n    x = 2\nelse:\n    return x\n",
        "try:\n    x = 1\nexcept KeyError:\n    x = 2\nelse:\n    x = 3\nfinally:\n    x = 4\n",
        "try:\n    x = 1\nexcept:\n    x = 2\nelse:\n    x = 3\n",
    ),
)
def test_general_try_else_shapes_have_one_structural_owner(source: str) -> None:
    result = build_node(
        ast.parse(source).body[0],
        filename="t.py",
        role=SugarRole.STATEMENT,
        ctx=FactoryBuildContext(filename="t.py", catalog=default_catalog()),
    )

    assert type(result.sugar).__name__ == "TrySugar"
    assert result.audit_row.candidates == ["TrySugar"]


def test_try_else_owner_structurally_carries_every_face() -> None:
    site = _site(VENDOR_SHAPE)
    result = build_node(
        site.node,
        filename="Lib/datetime.py",
        role=SugarRole.STATEMENT,
        ctx=FactoryBuildContext(filename="Lib/datetime.py", catalog=default_catalog()),
    )

    assert TrySugar.owns(site)
    assert type(result.sugar).__name__ == "TrySugar"
    assert result.sugar.else_body is not None
    assert len(result.sugar.handlers) == 1
    assert len(result.sugar.walk_children()) == 4


def test_full_datetime_removes_try_gap_and_names_next_projection_blocker(
    cpython_311_datetime_path,
) -> None:
    path = cpython_311_datetime_path
    source = path.read_text(encoding="utf-8")
    assert len(source.splitlines()) == 2635

    payload, gaps = audit_lift_file(source, str(path), hold_panic=True)
    assertions = account_lift_coverage(
        census_source(source, file=str(path)), payload.to_rpc()
    ).to_json()["assertions"]

    assert assertions["stated"] == 45
    assert assertions["lifted_cited"] == 14
    assert assertions["refused_loud"] == 31
    assert assertions["silently_unaccounted"] == 0
    assert not any(gap.info.get("observed") == "Try" for gap in gaps)
    assert any(
        gap.label.endswith(":182:0") and gap.info.get("observed") == "GuardedValue"
        for gap in gaps
    )
