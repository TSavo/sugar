"""A unit without its typed tree is not a second kind of unit (#7757).

The one door (``Backend.materialize_module``) always binds the typed tree on
the unit it reads (``SourceUnit.bind_typed_module``).  A unit that never went
through that door has no tree, and every reader that used to answer ``None``,
``False`` or an empty set for it now refuses by name instead
(``SourceUnit._require_typed_module``): an absent tree changed answers
(#8056: a builtin read became a free name).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.context_manager_resolution import (
    TreeConstructionContextV1,
)
from sugar_source_tree.formal_manager_head import _with_item_expr
from sugar_source_tree.locals_snapshot import locals_snapshot_shape
from sugar_source_tree.nodes import Call, GeneratorExp, SourceUnit
from sugar_source_tree.panic import SourceTreePanic
from sugar_source_tree.spans import LineColSpan
from sugar_source_tree.tree import SourceFile

SOURCE = "def f(x):\n    return len(x)\n"
READ = LineColSpan(2, 11, 2, 14)
READ_KEY = (2, 11, 2, 14)


def _unit_without_typed_tree() -> SourceUnit:
    return SourceUnit("no-typed-tree.py", SOURCE, "no-typed-tree-cid")


@pytest.mark.parametrize(
    ("owner", "read"),
    (
        (
            "SourceUnit.builtin_reference_at",
            lambda unit: unit.builtin_reference_at("len", READ),
        ),
        (
            "SourceUnit.interpreter_reference_at",
            lambda unit: unit.interpreter_reference_at("__builtins__", READ),
        ),
        (
            "SourceUnit.name_bound_nowhere",
            lambda unit: unit.name_bound_nowhere("undefined_name"),
        ),
        (
            "SourceUnit.class_body_holding",
            lambda unit: unit.class_body_holding(READ),
        ),
        (
            "SourceUnit._module_global_rows",
            lambda unit: unit.module_threaded_names(),
        ),
        (
            "SourceUnit._module_global_rows",
            lambda unit: unit.module_unthreaded_names(),
        ),
        (
            "SourceUnit.lexical_call_enrollment",
            lambda unit: unit.lexical_call_enrollment(
                SimpleNamespace(fragment="len(x)")
            ),
        ),
        # The import table: the door binds the tree before any reader runs,
        # so there is no "no typed root yet" window to answer None in.
        (
            "SourceUnit._lexical_import_pass",
            lambda unit: unit.import_reference_target(READ_KEY),
        ),
        (
            "SourceUnit._lexical_import_pass",
            lambda unit: unit.import_binding_reference(SimpleNamespace(), "x"),
        ),
        (
            "SourceUnit.import_value_use_receipt",
            lambda unit: unit.import_value_use_receipt(READ_KEY),
        ),
        (
            "SourceUnit.module_execution_site",
            lambda unit: unit.module_execution_site(SimpleNamespace()),
        ),
        (
            "SourceUnit.source_allocation_definition_for_call",
            lambda unit: unit.source_allocation_definition_for_call(
                SimpleNamespace()
            ),
        ),
        (
            "GeneratorExp._consumed_whole_in_place",
            lambda unit: GeneratorExp._consumed_whole_in_place(
                SimpleNamespace(unit=unit, fragment="(y for y in x)")
            ),
        ),
        (
            "formal_manager_head._with_item_expr",
            lambda unit: _with_item_expr(unit, 2, 11),
        ),
        (
            "locals_snapshot.locals_snapshot_shape",
            lambda unit: locals_snapshot_shape(unit, 2, 11),
        ),
    ),
)
def test_a_reader_on_a_unit_with_no_typed_tree_refuses_by_name(owner, read) -> None:
    unit = _unit_without_typed_tree()
    assert unit.typed_module is None

    with pytest.raises(SourceTreePanic) as refused:
        read(unit)

    assert refused.value.owner == owner
    assert refused.value.observed == "typed Module is not bound on this SourceUnit"


def test_the_door_binds_the_tree_before_any_reader_runs() -> None:
    """The window the import table used to answer ``None`` in does not exist:
    the door builds the tree structurally and binds it before any reader."""
    source = "import os\nos.getcwd()\n"
    tree = SourceFile(
        (source, "door-binds.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    assert tree.unit.typed_module is tree.root
    call = next(node for node in tree.nodes() if isinstance(node, Call))
    assert tree.unit.module_execution_site(call) is not None
