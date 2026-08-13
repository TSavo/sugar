"""``X.attr = v`` mutates X; it does not BIND X (#7394).

``module_direct_bindings`` collected every ``Name`` anywhere under a
module-level assignment target, so the pandas 3.0.3 pin's

    950| get_option.__module__ = "pandas"

published a SECOND module-scope binding of ``get_option`` beside its
``FunctionDef`` at 143.  The by-name authority that must refuse a name with
several module-scope bindings then refused a name that has exactly one.

Two facts -- "assigns to an attribute OF this name" and "binds this name" --
were sharing one table.  These teeth pin the separation, and the FALSIFIABILITY
arm is the point of the file: a name that genuinely IS bound twice at module
scope must still be refused as ambiguous.  A repair that cannot refuse anything
is a tautology, so the lying twin runs beside the truthful one and the two must
disagree.
"""

from __future__ import annotations

import pytest
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.binding_state import _callee_definition_by_name_in_its_unit
from sugar_source_tree.nodes import Assign, FunctionDef
from sugar_source_tree.panic import BackendDefect
from sugar_source_tree.tree import SourceFile


def _sf(source: str, name: str) -> SourceFile:
    return SourceFile((source, name, blake3_512_of(source.encode("utf-8"))))


def _bindings(tree: SourceFile, name: str):
    return (tree.unit.module_direct_bindings or {}).get(name, ())


def _fn(tree: SourceFile, name: str) -> FunctionDef:
    return next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == name
    )


# The pin's shape, reduced: one definition and five ``__module__`` patches.
_PIN_SHAPE = '''\
def get_option(pat):
    return pat


def set_option(pat, value):
    return value


# import set_module here would cause circular import
get_option.__module__ = "pandas"
set_option.__module__ = "pandas"
'''


def test_attribute_target_does_not_bind_its_base_name() -> None:
    """The pin's own shape: ONE binding for ``get_option``, the FunctionDef."""
    tree = _sf(_PIN_SHAPE, "pin_attribute_target.py")
    bindings = _bindings(tree, "get_option")
    assert len(bindings) == 1, [type(row).__name__ for row in bindings]
    assert isinstance(bindings[0], FunctionDef)
    assert bindings[0].name == "get_option"
    # And the patching statement is not silently absent from the module either
    # -- it is simply not a BINDING of that name.
    assert not any(isinstance(row, Assign) for row in bindings)


def test_subscript_target_does_not_bind_its_base_name() -> None:
    """``registry[key] = v`` mutates the mapping; the name keeps one binding."""
    tree = _sf(
        "registry = {}\nregistry['a'] = 1\nregistry['b'] = 2\n",
        "pin_subscript_target.py",
    )
    bindings = _bindings(tree, "registry")
    assert len(bindings) == 1
    assert isinstance(bindings[0], Assign)


def test_the_value_side_of_an_attribute_assignment_binds_nothing() -> None:
    """The base ``Name`` under a chained attribute target is still not bound."""
    tree = _sf(
        "import types\nns = types.SimpleNamespace()\nns.inner.deep = 1\n",
        "pin_chained_attribute.py",
    )
    assert len(_bindings(tree, "ns")) == 1
    assert "inner" not in (tree.unit.module_direct_bindings or {})


def test_destructuring_targets_still_bind_every_name() -> None:
    """The repair must NOT be a filter that loses real bindings."""
    tree = _sf(
        "a, (b, c) = 1, (2, 3)\nfirst, *rest = [1, 2, 3]\n[p, q] = (4, 5)\n",
        "pin_destructuring.py",
    )
    table = tree.unit.module_direct_bindings or {}
    for name in ("a", "b", "c", "first", "rest", "p", "q"):
        assert len(table.get(name, ())) == 1, f"{name} -> {table.get(name, ())}"


def test_mixed_target_binds_the_name_and_not_the_attribute_base() -> None:
    """One statement, both shapes: ``obj.attr = value = 1``."""
    tree = _sf(
        "class Holder:\n    attr = 0\n\n\nobj = Holder()\nobj.attr = value = 1\n",
        "pin_mixed_target.py",
    )
    table = tree.unit.module_direct_bindings or {}
    assert len(table.get("value", ())) == 1
    # ``obj`` keeps ONLY its real binding, the ``obj = Holder()`` assignment.
    assert len(table.get("obj", ())) == 1
    assert isinstance(table["obj"][0], Assign)
    assert table["obj"][0].line_col_span().start_line == 5


def test_augmented_attribute_target_does_not_bind_its_base_name() -> None:
    """``AugAssign``/``AnnAssign`` go through the same closed decision."""
    tree = _sf(
        "import types\ncount = 0\nns = types.SimpleNamespace()\n"
        "ns.total += 1\nns.label: str = 'x'\n",
        "pin_aug_attribute.py",
    )
    table = tree.unit.module_direct_bindings or {}
    assert len(table.get("ns", ())) == 1
    assert "total" not in table and "label" not in table
    assert len(table.get("count", ())) == 1


# ---------------------------------------------------------------------------
# FALSIFIABILITY -- the corrected table must still REFUSE a genuine ambiguity.
# ---------------------------------------------------------------------------

_LYING_TWIN = '''\
def find_level(depth):
    return depth


def find_level(depth):
    return depth + 1


find_level.__module__ = "pandas"
'''

_TRUTHFUL = '''\
def find_level(depth):
    return depth


find_level.__module__ = "pandas"
'''


def test_a_genuinely_doubly_bound_name_is_STILL_refused_as_ambiguous() -> None:
    """LYING TWIN: two real module-scope ``def``s, plus the same attribute patch.

    Everything the truthful arm has, and one more real binding.  If the repair
    were "drop the second entry" or "take the first binding", this would resolve
    -- and it must not.
    """
    tree = _sf(_LYING_TWIN, "twin_two_real_bindings.py")
    callee = _fn(tree, "find_level")
    assert _callee_definition_by_name_in_its_unit(callee) is None, (
        "a name with two module-scope bindings has no by-name answer"
    )


def test_the_lying_twins_table_holds_exactly_the_two_REAL_bindings() -> None:
    """The twin's SHAPE, kept apart from the twin's REFUSAL.

    Asserting both in one test made a tooth that dies for two unrelated
    reasons: restoring the attribute-target defect reddens it because the
    count becomes three, which says nothing about whether the ambiguity is
    still refused.  Split, each fact has its own lever.
    """
    tree = _sf(_LYING_TWIN, "twin_two_real_bindings.py")
    bindings = _bindings(tree, "find_level")
    assert len(bindings) == 2, [type(row).__name__ for row in bindings]
    assert all(isinstance(row, FunctionDef) for row in bindings)


def test_the_truthful_arm_resolves_to_exactly_one_definition() -> None:
    """TRUTHFUL: same file minus the second ``def`` -- the authority answers."""
    tree = _sf(_TRUTHFUL, "twin_one_real_binding.py")
    bindings = _bindings(tree, "find_level")
    assert len(bindings) == 1

    callee = _fn(tree, "find_level")
    resolved = _callee_definition_by_name_in_its_unit(callee)
    assert resolved is not None
    assert resolved.fragment.seal() == callee.fragment.seal()


def test_an_unassignable_target_PANICS_rather_than_binding_nothing() -> None:
    """Closed set: an unrecognised target is a producer defect, named loudly.

    A silently empty answer for an unknown target shape is indistinguishable
    from a legitimately non-binding one, which is the exact conflation this
    repair exists to end.
    """
    from sugar_source_tree.nodes import SourceUnit

    tree = _sf("value = 1\n", "pin_closed_set.py")
    statement = tree.unit.typed_module.body[0]
    # A Constant is never an assignment target; hand one over directly.
    not_a_target = statement.value
    with pytest.raises(BackendDefect) as raised:
        SourceUnit._assignment_target_bound_names(not_a_target, statement)
    assert "not an assignable construct" in str(raised.value)
    assert not_a_target.kind in str(raised.value)
