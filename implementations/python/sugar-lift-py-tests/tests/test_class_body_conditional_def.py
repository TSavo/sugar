"""A ``def`` under an ``if`` of a class body is built, and refused at reduction.

pandas ``tests/dtypes/test_inference.py`` builds its duck type in a test
body::

    class DictLike:
        def __init__(self, d) -> None:
            self.d = d

        if has_keys:

            def keys(self):
                return self.d.keys()

The class statement stopped at construction (step 5) with "unsupported
conditional class member FunctionDef": the tree was never built.  An arm's
``def`` is the one ``def`` statement (``_def_statement_sugar``), built where
``IfSugar`` builds its arm, so the class statement now constructs.  The method
it binds is in no roster (the class's methods are the ``def`` statements of
the body itself), so the class statement's reduction (step 6) refuses by name
(``ClassDefinitionSugar._namespace``): the method is never dropped.

Twins:
  truthful -- the class statement constructs, its arm's ``def`` carried as
              one unrostered definition;
  lying    -- reducing it never builds a class without the method: it is
              refused by name.
"""

from __future__ import annotations

import pytest

_PRELUDE = "import os\n\nFLAG = os.environ.get('F')\n\n\n"


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


_ARM_DEF = (
    "    def __init__(self, d):\n"
    "        self.d = d\n"
    "\n"
    "    if True:\n"
    "\n"
    "        def keys(self):\n"
    "            return self.d\n"
)


@pytest.mark.parametrize(
    "body",
    [
        _ARM_DEF,
        _ARM_DEF.replace("if True:", "if FLAG:"),
        (
            "    if True:\n        x = 1\n"
            "    else:\n        def m(self):\n            return 1\n"
        ),
    ],
    ids=["ground-guard", "module-global-guard", "else-arm"],
)
def test_a_def_under_an_if_constructs(body: str) -> None:
    from sugar_lift_py_tests.sugar.class_definition_sugar import ClassDefinitionSugar

    sugar = _box(body).sugar()

    assert isinstance(sugar, ClassDefinitionSugar)
    assert len(sugar.unrostered_definitions) == 1
    # The roster is the body's own ``def`` statements, never an arm's.
    assert all(method.name != "keys" for method in sugar.methods)


def test_reducing_a_class_with_a_def_under_an_if_refuses_by_name() -> None:
    from sugar_lift_py_tests.context import ReduceContext
    from sugar_source_tree.panic import SugarNotWritten

    sugar = _box(_ARM_DEF).sugar()

    with pytest.raises(SugarNotWritten, match="which no method roster carries"):
        sugar.desugar(ReduceContext.root(owner="test_class_body_conditional_def"))


def test_a_class_under_an_if_still_refuses_at_construction() -> None:
    from sugar_source_tree.panic import SugarNotWritten

    with pytest.raises(
        SugarNotWritten, match="unsupported conditional class member ClassDef"
    ):
        _box("    if True:\n        class Inner:\n            pass\n").sugar()
