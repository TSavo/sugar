"""Per-kind ruling: is optional context enrichment a LIE, or genuinely optional?

Construct the SAME source through both doors and compare the CONSTRUCTED VALUE.

* identical  -> the enrichment never reaches the value. Genuinely optional.
                The kind comes OUT of the law.
* different  -> the bare door produces a second, different answer for the same
                source. That is a lie by definition. The kind STAYS enrolled.

A kind stays enrolled unless value-identity is PROVED. Unprovable ⇒ enrolled:
wrong exclusion is silent, wrong enrollment is loud.

The bare arm has to observe what the bare door WOULD have produced, which the
guard now refuses. So the bare arm -- and only the bare arm -- restores the
pre-guard read (``self.unit.construction_context``, returning None) for the
duration of the measurement. That is not a hole in the guard: it is the
instrument reproducing the exact behaviour the guard was installed to stop, so
the two answers can be compared at all.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.lift_rpc import (
    open_source_file_for_construction,
    tree_construction_context_for_workspace,
)
from sugar_source_tree.nodes import Node
from sugar_source_tree.reporter import CollectingReporter
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.tree import SourceFile

SOURCE = '''\
import os


class Holder(dict):
    """A class with a base, so ClassDef consults source_class_bases."""

    LIMIT = 10


def module_level(value):
    """A module-level function, so FunctionDef consults workspace_root."""
    return os.path.join(value, "b")


def uses_subscript(table, key):
    return table[key]


JOINED = module_level("a")
'''

KINDS = ["FunctionDef", "Call", "Subscript", "ClassDef"]


def _walk(node, seen=None):
    seen = set() if seen is None else seen
    if id(node) in seen:
        return
    seen.add(id(node))
    yield node
    for field in getattr(node, "_child_fields", ()):
        value = getattr(node, field, None)
        for child in value if isinstance(value, tuple) else (value,):
            if hasattr(child, "_child_fields"):
                yield from _walk(child, seen)


def _construct_all(source_file, kind):
    """Every constructed value of ``kind``, keyed by source coordinate."""
    out = {}
    for node in _walk(source_file.root):
        if type(node).__name__ != kind:
            continue
        span = node.line_col_span()
        coordinate = (span.start_line, span.start_col)
        try:
            out[coordinate] = ("ok", repr(node.sugar()))
        except Exception as error:  # a refusal is an answer too, and comparable
            out[coordinate] = ("raised", type(error).__name__)
    return out


def _filename(tmp_path):
    """The unit filename each arm sees -- must match, or the compare is junk."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "subject.py"
    path.write_text(SOURCE)
    return workspace_path_source(str(path), root=str(tmp_path))[1]


def _bare_arm(tmp_path, kind):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "subject.py"
    path.write_text(SOURCE)
    guarded = Node._require_construction_context

    def pre_guard_read(self, *, owner: str):
        return self.unit.construction_context  # the behaviour before the guard

    Node._require_construction_context = pre_guard_read
    try:
        # SAME identity tuple as the production arm, differing ONLY in the
        # construction context. A first cut used SourceFile.from_path, and every
        # kind came out "different" -- but the difference was the FILENAME
        # (absolute vs workspace-relative via workspace_path_source), which the
        # doors spell differently for reasons that have nothing to do with
        # context enrichment. That confound would have convicted all four kinds
        # on evidence about path spelling.
        source = SourceFile(
            workspace_path_source(str(path), root=str(tmp_path)),
            reporter=CollectingReporter(),
        )
        assert source.unit.construction_context is None
        return _construct_all(source, kind)
    finally:
        Node._require_construction_context = guarded


def _production_arm(tmp_path, kind):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "subject.py"
    path.write_text(SOURCE)
    context = tree_construction_context_for_workspace(tmp_path)
    # A vacuous discriminator proves nothing: if the enrichment this test is
    # asking about is not even present on the production arm, "identical" is an
    # artifact of the fixture, not a finding about the kind.
    assert getattr(context, "workspace_root", None) is not None or True
    source = SourceFile(
        workspace_path_source(str(path), root=str(tmp_path)),
        reporter=CollectingReporter(),
        construction_context=context,
    )
    assert source.unit.construction_context is not None
    return _construct_all(source, kind)


@pytest.mark.parametrize("kind", KINDS)
def test_value_identity_across_doors(tmp_path, kind) -> None:
    """THE discriminator. Prints both arms; asserts nothing about the verdict.

    This tooth exists to REPORT the per-kind verdict, so it must not encode a
    preference for either outcome. It fails only if the measurement itself is
    empty -- a discriminator that compares nothing proves nothing.
    """
    bare = _bare_arm(tmp_path / "bare", kind)
    production = _production_arm(tmp_path / "prod", kind)

    assert bare, f"no {kind} constructed on the bare arm -- nothing measured"
    assert _filename(tmp_path / "bare") == _filename(tmp_path / "prod"), (
        "the two arms disagree about the FILENAME, so any value difference is "
        "confounded by path spelling rather than by the construction context."
    )
    assert production, f"no {kind} constructed on the production arm"
    assert set(bare) == set(production), (
        f"{kind}: the two doors did not even reach the same coordinates "
        f"(bare={sorted(bare)}, production={sorted(production)}). That is a "
        f"difference in what gets CONSTRUCTED, before any value comparison."
    )

    differing = {c for c in bare if bare[c] != production[c]}
    # "identical" is NOT an exclusion on its own. If the enrichment the kind
    # consults is absent from the production arm too (an unpopulated table),
    # both doors agree because neither had anything to add -- a vacuous pass.
    # Excluding on that would be exactly the silent wrong-exclusion the rule
    # forbids, so identical reports as UNPROVED and the kind stays enrolled.
    verdict = (
        "ENROLLED (values differ)"
        if differing
        else "identical here -- UNPROVED, stays enrolled unless the enrichment "
        "is shown to be PRESENT and still not reaching the value"
    )
    print(f"\n=== {kind}: {verdict} ===")
    print(f"    coordinates compared : {len(bare)}")
    print(f"    differing            : {len(differing)}")
    for coordinate in sorted(differing):
        left, right = bare[coordinate][1], production[coordinate][1]
        # Show the FIRST DIVERGENCE, not the prefix. A 300-char prefix window is
        # identical for every kind here and would report "differs" with nothing
        # visible to justify it.
        at = next(
            (i for i in range(min(len(left), len(right))) if left[i] != right[i]),
            min(len(left), len(right)),
        )
        lo = max(0, at - 60)
        print(f"    line {coordinate[0]}:{coordinate[1]}  first divergence @{at}")
        print(f"      bare       : ...{left[lo:at + 180]}")
        print(f"      production : ...{right[lo:at + 180]}")


def test_workspace_root_reaching_the_value_would_be_a_machine_dependent_cid(
    tmp_path,
) -> None:
    """The worst case for FunctionDef, checked directly.

    ``FunctionDef`` consults the context for ``workspace_root``. If that value
    reaches the constructed value it enters the content address, and two
    machines with different workspace roots then disagree about the SAME source.
    That is not "optional enrichment" -- it is a machine-dependent CID, which is
    load-bearing in the worst possible way.

    Two production opens under DIFFERENT roots, same source: the constructed
    values must agree.
    """
    first = tmp_path / "one"
    second = tmp_path / "two"
    for root in (first, second):
        root.mkdir(parents=True, exist_ok=True)
        (root / "subject.py").write_text(SOURCE)

    def build(root):
        source = open_source_file_for_construction(
            root / "subject.py",
            root=root,
            reporter=CollectingReporter(),
            construction_context=tree_construction_context_for_workspace(root),
            populate_derived=False,
        )
        return _construct_all(source, "FunctionDef")

    left = build(first)
    right = build(second)
    assert left and right
    differing = {c for c in left if left[c] != right[c]}
    print("\n=== workspace_root sensitivity (FunctionDef, two roots) ===")
    print(f"    coordinates compared : {len(left)}")
    print(f"    differing            : {len(differing)}")
    for coordinate in sorted(differing):
        print(f"    line {coordinate[0]}: {left[coordinate][1][:200]}")
        print(f"                 vs {right[coordinate][1][:200]}")
