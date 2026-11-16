"""A property read on an instance is the dispatched member read (#7757, #9043).

``Receiver().value`` where ``value`` is a ``@property`` reads the member the
instance's class row holds and calls it as the dispatched member, joined at
prove.  The lift never runs the getter's body: it does not read a ``raise``
or a ``return`` off it, so no halt of the read names an exception type taken
from the getter, and the read's own halt is kept beside its completion (a
halt is never dropped).  The tests that pinned the getter run at lift (its
raise's type identity, an alias of a builtin raised there, a refusal of a
shadowed ``property`` spelling that authorised the run) pinned that deleted
second way.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.outcome import Completed, ExitSet
from sugar_lift_py_tests.outcome.exit_set import Halted
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.nodes import Attribute, With
from sugar_source_tree.tree import SourceFile


PANDAS_MANIFEST_CID = (
    "blake3-512:6f317a5a489eb7e730064d79792f0d1656723130603309e2f2ed9cbedb604eda"
    "1c4b77a26dc90c980411292ea3994af9015da4cd850b5a307af5a4998b563530"
)


def _tree(tmp_path: Path, source: str) -> SourceFile:
    path = tmp_path / "property_attribute.py"
    path.write_text(source, encoding="utf-8")
    context = TreeConstructionContextV1.for_source_call_construction()
    return SourceFile(
        workspace_path_source(str(path), root=str(tmp_path)),
        construction_context=context,
    )


def _body_attribute(tree: SourceFile) -> Attribute:
    with_node = next(node for node in tree.nodes() if isinstance(node, With))
    expression = with_node.body[0].value
    assert isinstance(expression, Attribute)
    return expression


def _getter_raises_read_off_its_body(outcome: ExitSet, name: str) -> tuple:
    """Every halt of ``outcome`` naming ``name`` as an authenticated raise:
    the type a getter body's ``raise`` would state if it were run here."""
    return tuple(
        face
        for face in outcome.exits
        if isinstance(face, Halted)
        and isinstance(face.effect, RaiseEffect)
        and face.effect.exception_name == name
    )


def _getter(statement: str, *, prefix: str = "") -> str:
    return (
        "import pytest\n" + prefix + "class Receiver:\n"
        "    @property\n"
        "    def value(self):\n"
        f"        {statement}\n"
        "def use():\n"
        "    with pytest.raises(ValueError):\n"
        "        Receiver().value\n"
    )


def test_source_property_getter_body_is_never_run_at_lift(tmp_path: Path) -> None:
    """The getter raises ``ValueError``; the read is the dispatched member
    read, so its halt is kept and no halt states the getter's raise."""
    tree = _tree(tmp_path, _getter("raise ValueError('source getter')"))

    outcome = _body_attribute(tree).sugar().desugar(None)

    assert isinstance(outcome, ExitSet)
    assert any(isinstance(face, Halted) for face in outcome.exits), outcome.exits
    assert _getter_raises_read_off_its_body(outcome, "ValueError") == ()


def test_source_property_getter_that_returns_is_still_the_undecided_read(
    tmp_path: Path,
) -> None:
    """The getter returns ``7``; the read does not complete with ``7``
    unconditionally: it completes on its own face, its halt kept."""
    tree = _tree(tmp_path, "return 7")

    outcome = _body_attribute(tree).sugar().desugar(None)

    assert isinstance(outcome, ExitSet)
    assert any(isinstance(face, Completed) for face in outcome.exits), outcome.exits
    assert any(isinstance(face, Halted) for face in outcome.exits), outcome.exits
    assert outcome.completed_value() is None


def test_shadowed_property_spelling_reads_the_same_dispatched_member(
    tmp_path: Path,
) -> None:
    """``property`` rebound to a plain function: the read is the same
    dispatched member read, by binding and never by spelling, so it neither
    runs the body nor states its raise."""
    tree = _tree(
        tmp_path,
        _getter(
            "raise ValueError('not a descriptor')",
            prefix="def property(fn):\n    return fn\n",
        ),
    )

    outcome = _body_attribute(tree).sugar().desugar(None)

    assert isinstance(outcome, ExitSet)
    assert any(isinstance(face, Halted) for face in outcome.exits), outcome.exits
    assert _getter_raises_read_off_its_body(outcome, "ValueError") == ()


def test_pandas_303_abstract_method_property_is_the_concrete_reproducer() -> None:
    """pandas ``tests/test_errors.py`` line 108: the abstract-method property
    raises ``AbstractMethodError`` in its getter; its read keeps a halt and
    states no raise read off the getter's body."""
    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus

    corpus = authenticated_pandas_corpus()
    assert (corpus.version, corpus.manifest_cid, corpus.file_count) == (
        "3.0.3",
        PANDAS_MANIFEST_CID,
        1421,
    )
    path = corpus.root / "tests/test_errors.py"
    tree = SourceFile(
        workspace_path_source(str(path), root=str(corpus.root.parent)),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    matches = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, Attribute)
        and node.attr == "property"
        and node.line_col_span().start_line == 108
    )
    assert len(matches) == 1

    outcome = matches[0].sugar().desugar(None)

    assert isinstance(outcome, ExitSet)
    assert any(isinstance(face, Halted) for face in outcome.exits), outcome.exits
    assert _getter_raises_read_off_its_body(outcome, "AbstractMethodError") == ()


def test_unknown_builtin_member_cannot_authenticate_a_property_raise(tmp_path):
    from sugar_lift_py_tests.effect import UndeterminedRaiseEffect

    tree = _tree(
        tmp_path,
        _getter(
            "raise errors.UnwrittenError('source getter')",
            prefix="import builtins as errors\n",
        ),
    )
    outcome = _body_attribute(tree).sugar().desugar(None)
    assert isinstance(outcome, ExitSet)
    effect = next(face.effect for face in outcome.exits if isinstance(face, Halted))
    assert isinstance(effect, UndeterminedRaiseEffect)
    assert not isinstance(effect, RaiseEffect)


def test_shadowed_builtin_alias_cannot_authenticate_a_property_raise(tmp_path):
    from sugar_lift_py_tests.effect import UndeterminedRaiseEffect

    tree = _tree(
        tmp_path,
        _getter(
            "raise errors.ValueError('source getter')",
            prefix="import builtins as errors\nerrors = replacement\n",
        ),
    )
    outcome = _body_attribute(tree).sugar().desugar(None)
    assert isinstance(outcome, ExitSet)
    effect = next(face.effect for face in outcome.exits if isinstance(face, Halted))
    assert isinstance(effect, UndeterminedRaiseEffect)
    assert not isinstance(effect, RaiseEffect)
