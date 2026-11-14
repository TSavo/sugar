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

from sugar_source_tree.nodes import SourceUnit
from sugar_source_tree.panic import SourceTreePanic
from sugar_source_tree.spans import LineColSpan

SOURCE = "def f(x):\n    return len(x)\n"
READ = LineColSpan(2, 11, 2, 14)


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
    ),
)
def test_a_reader_on_a_unit_with_no_typed_tree_refuses_by_name(owner, read) -> None:
    unit = _unit_without_typed_tree()
    assert unit.typed_module is None

    with pytest.raises(SourceTreePanic) as refused:
        read(unit)

    assert refused.value.owner == owner
    assert refused.value.observed == "typed Module is not bound on this SourceUnit"
