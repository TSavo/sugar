from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.floor import ClassDefinitionValue, SymbolicValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Complete
from sugar_source_tree.nodes import ClassDef
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _class(tmp_path: Path, source: str) -> ClassDef:
    path = tmp_path / "module.py"
    path.write_text(source, encoding="utf-8")
    tree = SourceFile.from_path(path)
    return next(node for node in tree.nodes() if isinstance(node, ClassDef))


def test_builtin_class_member_coordinate_constructs_real_class_field(
    tmp_path: Path,
) -> None:
    definition = _class(
        tmp_path,
        "class Renamed:\n"
        "    carried = object.__str__\n",
    )

    outcome = definition.sugar().desugar(
        ReduceContext.root(owner="builtin class member class field")
    )

    assert type(outcome) is Complete
    assert type(outcome.value) is ClassDefinitionValue
    fields = {field.name: field.value for field in outcome.value.class_fields}
    assert tuple(fields) == ("carried",)
    assert type(fields["carried"]) is not SymbolicValue


def test_shadowed_class_coordinate_cannot_borrow_builtin_member_authority(
    tmp_path: Path,
) -> None:
    definition = _class(
        tmp_path,
        "class Renamed:\n"
        "    carried = substitute.member\n",
    )
    ctx = ReduceContext.root(owner="shadowed class member").with_temporal(
        ReduceContext.root(owner="shadow source").temporal.bind_value(
            "substitute", SymbolicValue(make_var("foreign-class-coordinate"))
        )
    )

    with pytest.raises(SugarNotWritten) as raised:
        definition.sugar().desugar(ctx)
    assert raised.value.owner == "SymbolicValue.attribute"
