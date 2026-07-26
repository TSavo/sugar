"""Ground exceptional exits carry a workspace-relative, source-cited locus.

Three faces of one law.

TRUTHFUL: a corpus opened by absolute path through the construction door
mints a workspace-relative locus, and every ground exit (IndexError from a
proved out-of-bounds constant subscript, TypeError from ``None[...]``,
AssertionError from a proved-false assert, ZeroDivisionError from a
proved-zero divisor) CONSTRUCTS -- it does not panic.

CITED: the constructed exit pins the text its locus indexes into. The five
ground-exit copies each read ``site.source``, which a ``SourceFragment`` does
not have; the read was dead because the locus law below fired first, so a
green board never exercised it. A citation that is silently absent is the
elision this face forbids.

LYING: the locus law is SATISFIED, not deleted. A ``SourceFile`` built from
the bare ``path_source`` door still carries an absolute locus, and a ground
exit over it must still panic with the workspace-relative demand. A
``SourceMemento`` addresses ``{file, span}`` relative to a workspace and
``resolve_span_memento`` re-reads it as ``project_root / file``; an absolute
locus is an address no other checkout can resolve.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor import RaiseValue
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.outcome import Complete

CORPUS = """\
def ground_index():
    xs = [1, 2, 3]
    return xs[5]


def ground_type():
    n = None
    return n[0]


def ground_assert():
    assert False
    return 1


def ground_zero_div():
    return 1 / 0


def ground_str_index():
    s = "ab"
    return s[9]


def ground_tuple_index():
    t = (1, 2)
    return t[7]
"""

EXPECTED_EXCEPTIONS = {
    "ground_index": "IndexError",
    "ground_type": "TypeError",
    "ground_assert": "AssertionError",
    "ground_zero_div": "ZeroDivisionError",
    "ground_str_index": "IndexError",
    "ground_tuple_index": "IndexError",
}


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "ground_exits.py").write_text(CORPUS, encoding="utf-8")
    return root


def _raise_effects(root: Path) -> dict[str, RaiseEffect]:
    """Desugar every function through the production construction door.

    The path handed in is ABSOLUTE -- that is the corpus shape the census
    lifts, and the shape that used to panic.
    """
    path = root / "ground_exits.py"
    assert path.is_absolute()
    source_file = open_source_file_for_construction(
        path, root=root, populate_derived=True
    )
    effects: dict[str, RaiseEffect] = {}
    for function in source_file.functions():
        outcome = function.sugar().desugar(None)
        assert isinstance(outcome, Complete), (
            f"{function.name} did not construct: {outcome!r}"
        )
        raises = [
            statement
            for statement in outcome.value.record.statements
            if isinstance(statement, RaiseValue)
        ]
        assert len(raises) == 1, (
            f"{function.name} constructed {len(raises)} raise exits, not the "
            f"one ground exit its body proves"
        )
        effects[function.name] = raises[0].effect
    return effects


def test_ground_exits_construct_under_an_absolute_corpus_path(corpus: Path) -> None:
    """TRUTHFUL: every ground exit constructs; none panics on its own locus."""
    effects = _raise_effects(corpus)
    assert {
        name: effect.exception_name for name, effect in effects.items()
    } == EXPECTED_EXCEPTIONS


def test_ground_exit_blame_is_workspace_relative(corpus: Path) -> None:
    """TRUTHFUL: the blame names the file by its workspace-relative locus."""
    effects = _raise_effects(corpus)
    assert effects, "no ground exit was constructed -- nothing was measured"
    for name, effect in effects.items():
        blame = effect.blame
        assert blame is not None, f"{name} exit carries no blame locus"
        # The blame renders the fragment, which names the file it cites. That
        # name must be the workspace-relative one -- an absolute spelling is
        # the address no other checkout can resolve.
        assert "'ground_exits.py'" in blame, (
            f"{name} blame `{blame}` does not name the workspace-relative locus"
        )
        assert str(corpus) not in blame, (
            f"{name} blame `{blame}` leaks the absolute workspace path"
        )


def test_ground_exit_cites_the_source_it_locates(corpus: Path) -> None:
    """CITED: the exit pins the exact text of the file its locus indexes."""
    expected = hashlib.sha256(CORPUS.encode()).hexdigest()
    effects = _raise_effects(corpus)
    for name, effect in effects.items():
        assert effect.source_sha256 == expected, (
            f"{name} exit cites {effect.source_sha256!r}, not the source text "
            f"its locus indexes into"
        )


def test_absolute_locus_still_refuses_to_construct_a_ground_exit(
    corpus: Path,
) -> None:
    """LYING: the law is satisfied, not deleted.

    Built through the bare ``path_source`` door the locus is absolute again,
    and the ground exit must stay LOUD rather than mint an unresolvable
    citation. Deleting the locus check makes this test pass a construction it
    must refuse.
    """
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_lift_py_tests.gap.panic import ConstructionPanic
    from sugar_source_tree.tree import SourceFile

    path = corpus / "ground_exits.py"
    source_file = SourceFile(path_source(str(path)))
    function = next(
        fn for fn in source_file.functions() if fn.name == "ground_index"
    )
    with pytest.raises(ConstructionPanic) as raised:
        function.sugar().desugar(None)
    message = str(raised.value)
    assert "absolute source locus" in message
    assert "workspace-relative source locus" in message
