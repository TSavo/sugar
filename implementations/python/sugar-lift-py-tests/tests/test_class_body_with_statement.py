"""A ``with`` in a class body is the one ``with`` statement, its body's rows read.

pandas ``tests/dtypes/test_dtypes.py`` builds a decorator argument in the
class body of ``TestCategoricalDtype``::

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore")
        c = Categorical([0, 1], dtype=dtype1)

The class statement stopped at construction (step 5) with "unsupported class
member With": the tree was never built.  The ``with`` is now built by its own
sugar (``With._construct_sugar``), as in a module or function body, and each
statement of its body is a row of the class body where it stands: ``c`` is a
field read under the key its assignment binds it under.  Its body runs on
every face the ``with`` completes on; a face where the manager suppressed a
raise leaves a later row unbound, which the namespace refuses by name
(``ClassDefinitionSugar._namespace``).

Twins:
  truthful -- the class constructs, ``c`` its field, the ``with`` one
              statement of its block;
  lying    -- a name ``as`` binds has no key the namespace reads: refused by
              name, never a field read from nowhere; a ``def`` in the ``with``
              is in no method roster: refused by name at the reduction.
"""

from __future__ import annotations

import pytest

_PRELUDE = "import warnings\n\n\n"


def _tree(source: str):
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_source_tree.tree import SourceFile

    return SourceFile(
        (source, "test_witness.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )


def _box(body: str):
    from sugar_source_tree import nodes

    tree = _tree(_PRELUDE + "class Box:\n" + body)
    (box,) = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, nodes.ClassDef) and node.name == "Box"
    )
    return box


_WITH = (
    "    a = 1\n"
    "    with warnings.catch_warnings():\n"
    '        warnings.filterwarnings("ignore")\n'
    "        c = 2\n"
    "    d = 3\n"
)


def test_a_with_in_a_class_body_constructs_with_its_rows() -> None:
    from sugar_lift_py_tests.sugar.class_definition_sugar import ClassDefinitionSugar

    sugar = _box(_WITH).sugar()

    assert isinstance(sugar, ClassDefinitionSugar)
    assert [row.name for row in sugar.fields] == ["a", "c", "d"]
    # ``c`` stands in the ``with``'s body, which runs on every face the
    # statement completes on: it is no arm's row.
    assert not sugar.branch_fields
    assert all(row.evaluation_key is not None for row in sugar.fields)
    assert len(sugar.body) == 3
    assert not sugar.unrostered_definitions


def test_a_with_under_an_if_reads_its_rows_as_the_arm_s() -> None:
    sugar = _box(
        "    if True:\n"
        "        with warnings.catch_warnings():\n"
        "            c = 2\n"
    ).sugar()

    assert [row.name for row in sugar.fields] == ["c"]
    assert sugar.branch_fields == frozenset({0})


def test_a_name_with_as_binds_in_a_class_body_refuses_by_name() -> None:
    from sugar_source_tree.panic import SugarNotWritten

    with pytest.raises(
        SugarNotWritten,
        match="class field w whose statement carries no evaluation key",
    ):
        _box("    with warnings.catch_warnings() as w:\n        c = 2\n").sugar()


def test_a_def_in_a_with_of_a_class_body_is_carried_unrostered() -> None:
    # Built where the ``with`` builds it, in no method roster: the class's
    # reduction refuses it by name (``test_class_body_conditional_def``).
    sugar = _box(
        "    with warnings.catch_warnings():\n"
        "\n"
        "        def m(self):\n"
        "            return 1\n"
    ).sugar()

    assert len(sugar.unrostered_definitions) == 1
    assert all(method.name != "m" for method in sugar.methods)


def test_a_class_in_a_with_of_a_class_body_still_refuses_at_construction() -> None:
    from sugar_source_tree.panic import SugarNotWritten

    with pytest.raises(SugarNotWritten, match="class member ClassDef"):
        _box(
            "    with warnings.catch_warnings():\n"
            "        class Inner:\n"
            "            pass\n"
        ).sugar()
