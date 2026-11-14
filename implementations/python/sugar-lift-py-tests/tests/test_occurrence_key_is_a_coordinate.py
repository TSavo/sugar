"""Every occurrence key names its site by coordinate, never by a repr (#7808).

``occurrence_key`` used to spell a site as ``str(site)``: a source fragment's
``__repr__``, ``<SourceFragment 'file' [start, end) node=Call>``, which embeds
the unit's filename and a class's print format into proof identity. The key
is now the site's ``SourceFragmentCoordinateV1`` CID (content: source CID plus
line/col span), qualified by the occurrence path as before.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.occurrence import (
    entered,
    occurrence_key,
    site_coordinate_cid,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.tree import SourceFile


def _call_fragment(source: str, filename: str):
    tree = SourceFile((source, filename, blake3_512_of(source.encode("utf-8"))))
    return next(node for node in tree.nodes() if type(node).__name__ == "Call").fragment


SOURCE = "def f(x):\n    return g(x)\n"


def test_a_key_is_the_site_coordinate_not_its_repr() -> None:
    fragment = _call_fragment(SOURCE, "m.py")
    key = occurrence_key(fragment, ())
    assert key == site_coordinate_cid(fragment)
    assert key.startswith("blake3-512:")
    assert "SourceFragment" not in key and "m.py" not in key


def test_the_key_does_not_depend_on_the_file_name() -> None:
    here = occurrence_key(_call_fragment(SOURCE, "m.py"), ())
    there = occurrence_key(_call_fragment(SOURCE, "/elsewhere/deeper/n.py"), ())
    assert here == there


def test_the_occurrence_path_still_qualifies_the_key() -> None:
    fragment = _call_fragment(SOURCE, "m.py")
    with entered("loop:abc#1"):
        key = occurrence_key(fragment)
    assert key == f"{site_coordinate_cid(fragment)}@loop:abc#1"


def test_a_synthetic_slot_id_stays_itself() -> None:
    assert occurrence_key("with-item#exit_face", ()) == "with-item#exit_face"


def test_a_repr_spelling_is_refused() -> None:
    fragment = _call_fragment(SOURCE, "m.py")
    with pytest.raises(ConstructionPanic):
        occurrence_key(repr(fragment), ())
