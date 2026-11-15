"""Every face of a slice bound's evaluation reaches the subscript it bounds.

The pandas corpus line ``tests/indexes/datetimes/test_partial_slicing.py:451``,
``df[start : end[:-4] + "1:00"]``, completed with no halt in the no-context
subscript census (``test_authenticated_subscript_family_owns_no_construction_
panics``): a body that left by no arm, so a halt was dropped.  With ``df``,
``start`` and ``end`` undecided, three operations may raise and each keeps its
own raise face:

* ``end[:-4]``: a subscript of an undecided receiver (``SymbolicValue.subscript``);
* ``... + "1:00"``: a binary operation over an undecided operand
  (``UndecidedBinary:+``);
* ``df[...]``: a subscript of an undecided receiver (``SymbolicValue.subscript``).

Building the slice adds no face of its own: Python's ``slice()`` accepts any
objects as bounds and never raises; it carries its bounds' faces.

The probe shape is the census's: the expression's own sugar reduced with no
context, so every name is an undecided free value (no caller, no formal).  The
variants localize which piece dropped the halts: a plain slice, a slice whose
bound is a subscript, and a slice whose bound is ``undecided + str``.  The
cause was the last: ``SymbolicValue + StringValue`` minted a deferred
native-operation carrier with no formal coordinate (#7060), which no caller
answers, so the whole expression became that carrier instead of the undecided
binary law's two faces, and every face composed beside it waited on it.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.outcome import Completed, ExitSet
from sugar_source_tree.nodes import Return

SUBSCRIPT = "SymbolicValue.subscript"
BINARY_ADD = "UndecidedBinary:+"


def _returned_expression_outcome(tmp_path: Path, source: str):
    """The returned expression of ``f``, reduced with no context."""
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction

    path = tmp_path / "slice_bound.py"
    path.write_text(source, encoding="utf-8")
    tree = open_source_file_for_construction(
        path,
        root=tmp_path,
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    (returned,) = [node for node in tree.nodes() if isinstance(node, Return)]
    return returned.value.sugar().desugar(None)


def _halt_owners(outcome) -> Counter:
    assert isinstance(outcome, ExitSet), (
        "the expression must reduce to its faces, not wait on a carrier no "
        f"caller answers: {type(outcome).__name__}"
    )
    effects = [face.effect for face in outcome.halts()]
    assert all(isinstance(effect, UndeterminedRaiseEffect) for effect in effects), [
        type(effect).__name__ for effect in effects
    ]
    return Counter(effect.producer_node_owner for effect in effects)


def test_the_corpus_line_keeps_every_halt_face(tmp_path: Path) -> None:
    outcome = _returned_expression_outcome(
        tmp_path,
        'def f(df, start, end):\n    return df[start : end[:-4] + "1:00"]\n',
    )
    owners = _halt_owners(outcome)
    assert owners == Counter({SUBSCRIPT: 2, BINARY_ADD: 1}), owners
    assert any(isinstance(face, Completed) for face in outcome.exits), (
        "the read may also complete"
    )


def test_a_plain_slice_keeps_the_subscript_face(tmp_path: Path) -> None:
    owners = _halt_owners(
        _returned_expression_outcome(
            tmp_path, "def f(x, a, b):\n    return x[a:b]\n"
        )
    )
    assert owners == Counter({SUBSCRIPT: 1}), owners


def test_a_bound_that_adds_a_string_keeps_its_face(tmp_path: Path) -> None:
    owners = _halt_owners(
        _returned_expression_outcome(
            tmp_path, 'def f(x, a, b):\n    return x[a : b + "s"]\n'
        )
    )
    assert owners == Counter({SUBSCRIPT: 1, BINARY_ADD: 1}), owners


def test_a_bound_that_subscripts_keeps_its_face(tmp_path: Path) -> None:
    owners = _halt_owners(
        _returned_expression_outcome(
            tmp_path, "def f(x, a, b):\n    return x[a : b[:-1]]\n"
        )
    )
    assert owners == Counter({SUBSCRIPT: 2}), owners
