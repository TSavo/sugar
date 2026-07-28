"""The ground-exit locus law: a citation must be re-readable, or it is refused.

`ground_raise_effect` is the ONE door that mints a ground exceptional exit --
IndexError from a proved out-of-bounds constant subscript, AssertionError from
a proved-false assert, TypeError from `1 in "abc"`, ZeroDivisionError from a
proved-zero divisor. Every one cites two things: a source locus, and the text
that locus indexes into.

That imposes two requirements on the locus, and this module pins both as
REFUSALS rather than crashes:

1. It must be a fragment stating `filename` and `unit`. Prose addresses
   nothing, so no citation can be built from it. This arm previously read
   `site.filename` and died with `AttributeError: 'str' object has no
   attribute 'filename'` -- a crash wearing a law's clothes, which named
   neither the problem nor the fix.

2. Its filename must be workspace-relative. A `SourceMemento` addresses
   `{file, span}` relative to the workspace and `resolve_span_memento` re-reads
   it as `project_root / file`, so an absolute locus is not a longer spelling
   of the same address -- it is an address no other checkout can resolve.

Both stay LOUD. `panic = gap`. The alternative to refusing is a citation that
silently cannot be checked, which is worse than no citation.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.gap.panic import ConstructionPanic


def _fragment(tmp_path, *, root):
    """A real fragment whose locus is stated relative to ``root``."""
    from sugar_lift_python_source.source_oracle import workspace_path_source
    from sugar_source_tree.tree import SourceFile

    source = tmp_path / "ground.py"
    source.write_text("def witness():\n    return [1][3]\n", encoding="utf-8")
    identity = workspace_path_source(str(source), root=str(root))
    return next(SourceFile(identity).functions()).fragment


def _absolute_fragment(tmp_path):
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_source_tree.tree import SourceFile

    source = tmp_path / "ground.py"
    source.write_text("def witness():\n    return [1][3]\n", encoding="utf-8")
    return next(SourceFile(path_source(str(source))).functions()).fragment


def _exit(site):
    from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

    return ground_exceptional_exit(
        exception_name="IndexError", site=site, owner="test.ground_exit"
    )


# -- requirement 1: the locus must be a fragment ------------------------------


@pytest.mark.parametrize(
    "prose",
    ("site", "", "pandas/core/frame.py:12:4", "<SourceFragment ...>"),
)
def test_a_prose_locus_is_refused_and_says_what_to_thread(prose) -> None:
    """Every spelling of prose, including one that LOOKS like a locus."""
    with pytest.raises(ConstructionPanic) as raised:
        _exit(prose)

    info = raised.value.info
    assert info.owner == "test.ground_exit"
    assert "str locus stating no source fragment" == info.observed
    assert "fragment stating filename and unit" in info.requested
    assert "thread the fragment" in info.fix


def test_a_locus_with_a_filename_but_no_unit_is_refused() -> None:
    """Half a fragment cannot cite either: the text is what gets hashed."""

    class HalfFragment:
        filename = "pkg/mod.py"
        unit = None

    with pytest.raises(ConstructionPanic) as raised:
        _exit(HalfFragment())

    assert "HalfFragment locus stating no source fragment" == raised.value.info.observed


def test_the_refusal_is_a_named_gap_not_an_attribute_error() -> None:
    """The discrimination that names this whole change.

    A crash and a refusal are both loud, but only one of them says what is
    wrong. `ConstructionPanic` is a BaseException and `AttributeError` is not,
    so this also pins that the audit membrane sees a gap here, not a defect.
    """
    with pytest.raises(ConstructionPanic):
        _exit("site")

    with pytest.raises(BaseException) as raised:
        _exit("site")
    assert not isinstance(raised.value, AttributeError)


# -- requirement 2: the locus must be workspace-relative ----------------------


def test_an_absolute_locus_is_refused(tmp_path) -> None:
    with pytest.raises(ConstructionPanic) as raised:
        _exit(_absolute_fragment(tmp_path))

    info = raised.value.info
    assert info.observed == "absolute source locus"
    assert "workspace-relative" in info.requested


# -- the positive arm: a real fragment mints a real citation ------------------


def test_a_workspace_relative_fragment_mints_the_cited_exit(tmp_path) -> None:
    """Both requirements met: the door constructs, and cites re-readable source."""
    import hashlib

    from sugar_lift_py_tests.floor import RaiseValue
    from sugar_lift_py_tests.outcome import Complete

    site = _fragment(tmp_path, root=tmp_path)

    outcome = _exit(site)

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, RaiseValue)
    assert outcome.value.effect.exception_name == "IndexError"
    # The citation is the hash of the text the locus indexes into -- not a
    # placeholder, and not the absolute path's text.
    expected = hashlib.sha256(site.unit.source.encode()).hexdigest()
    assert outcome.value.effect.source_sha256 == expected


def test_the_cited_locus_is_relative_so_another_checkout_can_resolve_it(
    tmp_path,
) -> None:
    """The whole point of requirement 2, asserted on the minted locus."""
    from pathlib import Path

    site = _fragment(tmp_path, root=tmp_path)

    assert not Path(site.filename).is_absolute()
    assert site.filename == "ground.py"
