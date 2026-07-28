"""A span belongs to the source it was MEASURED IN — never to its parent's.

`Child.resolve` materializes a child handle under the unit it is given, which
for a child slot is the PARENT's unit. Within one file that is free and right:
parent and child were parsed from the same text, so the same line table reads
both. Across files it is not. The moment a caller's actual argument node is
bound into a callee body parsed from another file, the child was re-homed onto
a source its span was never measured in, and asking it to project read:

    BACKEND DEFECT [spans.LineTable.line_col]
      observed:  offset 55069 outside 0..27637

Three of the pandas board's five backend-defect rows were that one bug. 27637
is exactly `contextlib.py` on Python 3.12 — the interpreter the census ran —
so every one of those rows was a pandas use site being read against contextlib's
line table. The span was never wrong. The source it was read against was.

`BackendNode.minting_unit` is the fix and the law: a handle that was PARSED
out of a source says so and keeps it; a handle whose span is BORROWED from an
origin (every shadow rewrite, every synthetic constituent) answers `None` and
correctly takes the unit it is materialized under, because a borrowed span is
already in that source's coordinates.

Both faces are here. The truthful face is that a cross-unit child keeps its own
source and projects to the SAME coordinates it projects to at home. The lying
face is the discriminator: it fails if `minting_unit` is honored for shadow
handles too, which would strand every rewrite on a unit it does not belong to.
"""

from pathlib import Path

import pytest

from sugar_source_tree import SourceFile
from sugar_source_tree.backend import Child, materialize
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.shadow import ShadowNode, _handle_of


def _two_files(tmp_path: Path):
    """A SHORT definer and a LONG caller, so the caller's late spans run past
    the end of the definer's source — the `55069 > 27637` relationship."""
    definer = tmp_path / "definer.py"
    definer.write_text("def m(a):\n    return a\n", encoding="utf-8")
    caller = tmp_path / "caller.py"
    caller.write_text("# " + "pad " * 400 + "\nx = 1\ny = 2\n", encoding="utf-8")
    return (
        SourceFile.from_path(definer, reporter=CollectingReporter()),
        SourceFile.from_path(caller, reporter=CollectingReporter()),
    )


def test_a_cross_unit_child_keeps_the_source_its_span_was_minted_from(
    tmp_path: Path,
) -> None:
    definer, caller = _two_files(tmp_path)
    # The precondition the defect needs: the caller's node lies past the end of
    # the definer's text. Asserted, not assumed — if the fixture ever stops
    # satisfying it this test would pass for the wrong reason.
    late = caller.root.body[-1]
    assert late.span.start > len(definer.unit.source)

    at_home = late.line_col_span()
    rehomed = Child(_handle_of(late)).resolve(definer.unit, definer.reporter)

    assert rehomed.unit is caller.unit
    assert rehomed.unit is not definer.unit
    # The observable, not the number: it projects to the SAME place it does at
    # home, because it is the same span in the same source.
    assert rehomed.line_col_span() == at_home
    # The fragment door reads the same table, so it must agree.
    assert rehomed.fragment.line_col_span == at_home


def test_lying_a_borrowed_span_must_NOT_carry_a_minting_unit(tmp_path: Path) -> None:
    """The discriminator for the other direction.

    A shadow rewrite borrows its origin's span and is materialized under that
    origin's unit. If shadow handles also claimed a minting unit, every rewrite
    would be pinned to whatever unit happened to mint it and substitution could
    strand a rewritten node on a foreign source — the same defect, mirrored.
    A handle that did not parse anything must answer `None`.
    """
    _definer, caller = _two_files(tmp_path)
    late = caller.root.body[-1]
    shadow = ShadowNode("Pass", late.span, ())
    assert shadow.minting_unit is None

    # ...and it therefore takes the unit it is materialized under, which is how
    # a rewrite stays in its origin's source.
    node = materialize(caller.unit, shadow, caller.reporter)
    assert node.unit is caller.unit


def test_a_parsed_handle_names_the_unit_it_parsed(tmp_path: Path) -> None:
    """The source-backed side of the same law, stated directly."""
    _definer, caller = _two_files(tmp_path)
    late = caller.root.body[-1]
    assert late.ref.minting_unit is caller.unit


def test_same_file_children_are_unchanged(tmp_path: Path) -> None:
    """The overwhelmingly common case must be byte-identical.

    Parent and child from one file already agree on their unit, so honoring the
    child's own is a no-op. This twin is what fails if the fix ever starts
    resolving a same-file child against something other than its own source.
    """
    _definer, caller = _two_files(tmp_path)
    for node in caller.root.body:
        child = Child(_handle_of(node)).resolve(caller.unit, caller.reporter)
        assert child.unit is caller.unit
        assert child.line_col_span() == node.line_col_span()
