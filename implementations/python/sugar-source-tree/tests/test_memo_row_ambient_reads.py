"""A memo row is served only where every ambient value it read still holds.

#7838, inventory item 44, point 7.  One ``SourceFile``, as one process holds
a resident module.  Class ``C`` is built while ``PROJECTED_CLASS_METHODS``
names only its manager methods (what a narrowed manager projection sets), and
then built plainly, as an ordinary caller builds it.  The projected row read
the projection; the plain build reads none, so the row is not served to it
and ``extra`` is constructed, exactly as a plain build alone constructs it.
"""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree import nodes
from sugar_source_tree.tree import SourceFile

SOURCE = (
    "class C:\n"
    "    def __enter__(self):\n"
    "        return self\n"
    "\n"
    "    def __exit__(self, *exc):\n"
    "        return False\n"
    "\n"
    "    def extra(self):\n"
    "        return 1\n"
)

PLAIN = {
    "__enter__": "ConstructedClassMethodV1",
    "__exit__": "ConstructedClassMethodV1",
    "extra": "ConstructedClassMethodV1",
}


def _class_node():
    tree = SourceFile(
        (SOURCE, "memo_row_ambient_reads.py", blake3_512_of(SOURCE.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    (cls,) = [n for n in tree.nodes() if isinstance(n, nodes.ClassDef)]
    return cls


def _kinds(sugar) -> dict[str, str]:
    return {method.name: type(method).__name__ for method in sugar.methods}


def test_a_projected_row_is_not_served_to_a_plain_build() -> None:
    cls = _class_node()
    token = nodes.PROJECTED_CLASS_METHODS.set(
        {"C": frozenset({"__enter__", "__exit__"})}
    )
    try:
        projected = cls.sugar()
    finally:
        nodes.PROJECTED_CLASS_METHODS.reset(token)
    assert _kinds(projected)["extra"] == "DeferredClassMethodV1"

    assert _kinds(cls.sugar()) == PLAIN


def test_a_plain_build_alone_constructs_every_method() -> None:
    assert _kinds(_class_node().sugar()) == PLAIN


def test_the_projected_row_still_answers_its_own_projection() -> None:
    cls = _class_node()
    projection = {"C": frozenset({"__enter__", "__exit__"})}
    token = nodes.PROJECTED_CLASS_METHODS.set(projection)
    try:
        first = cls.sugar()
        again = cls.sugar()
    finally:
        nodes.PROJECTED_CLASS_METHODS.reset(token)
    assert again is first
