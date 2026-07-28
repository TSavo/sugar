from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.outcome import Complete, ExitSet
from sugar_lift_py_tests.outcome.exit_set import Halted
from sugar_lift_python_source.manager_summary_derivation import (
    populate_source_derived_resource_refs,
)
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.nodes import Attribute, With
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile

PANDAS_MANIFEST_CID = (
    "blake3-512:6f317a5a489eb7e730064d79792f0d1656723130603309e2f2ed9cbedb604eda"
    "1c4b77a26dc90c980411292ea3994af9015da4cd850b5a307af5a4998b563530"
)


def _tree(tmp_path: Path, source: str) -> SourceFile:
    path = tmp_path / "property_attribute.py"
    path.write_text(source, encoding="utf-8")
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        workspace_path_source(str(path), root=str(tmp_path)),
        construction_context=context,
    )
    populate_source_derived_resource_refs(tree, root=tmp_path, path=path)
    return tree


def _body_attribute(tree: SourceFile) -> Attribute:
    with_node = next(node for node in tree.nodes() if isinstance(node, With))
    expression = with_node.body[0].value
    assert isinstance(expression, Attribute)
    return expression


def test_source_property_getter_publishes_authenticated_exceptional_exit(
    tmp_path: Path,
) -> None:
    tree = _tree(
        tmp_path,
        "import pytest\n"
        "class Receiver:\n"
        "    @property\n"
        "    def value(self):\n"
        "        raise ValueError('source getter')\n"
        "def use():\n"
        "    with pytest.raises(ValueError):\n"
        "        Receiver().value\n",
    )

    outcome = _body_attribute(tree).sugar().desugar(None)

    assert isinstance(outcome, ExitSet)
    halted = tuple(face for face in outcome.exits if isinstance(face, Halted))
    assert len(halted) == 1
    effect = halted[0].effect
    assert isinstance(effect, RaiseEffect)
    assert effect.exception_name == "ValueError"
    assert effect.exception_type_coordinate is not None
    assert effect.occurrence_id is not None
    assert effect.producer_node_owner == "Attribute"


def test_property_getter_raise_keeps_imported_bare_exception_coordinate(
    tmp_path: Path,
) -> None:
    tree = _tree(
        tmp_path,
        "import pytest\n"
        "from provider.errors import CustomError\n"
        "class Receiver:\n"
        "    @property\n"
        "    def value(self):\n"
        "        raise CustomError('source getter')\n"
        "def use():\n"
        "    with pytest.raises(CustomError):\n"
        "        Receiver().value\n",
    )

    outcome = _body_attribute(tree).sugar().desugar(None)

    assert isinstance(outcome, ExitSet)
    halted = next(face for face in outcome.exits if isinstance(face, Halted))
    assert isinstance(halted.effect, RaiseEffect)
    assert halted.effect.exception_name == "CustomError"
    assert halted.effect.exception_type_coordinate is not None
    assert halted.effect.occurrence_id is not None


def test_source_property_getter_that_returns_completes_without_a_raise(
    tmp_path: Path,
) -> None:
    tree = _tree(
        tmp_path,
        "import pytest\n"
        "class Receiver:\n"
        "    @property\n"
        "    def value(self):\n"
        "        return 7\n"
        "def use():\n"
        "    with pytest.raises(ValueError):\n"
        "        Receiver().value\n",
    )

    outcome = _body_attribute(tree).sugar().desugar(None)

    assert isinstance(outcome, Complete)


def test_shadowed_property_spelling_does_not_authorize_descriptor_dispatch(
    tmp_path: Path,
) -> None:
    tree = _tree(
        tmp_path,
        "import pytest\n"
        "def property(fn):\n"
        "    return fn\n"
        "class Receiver:\n"
        "    @property\n"
        "    def value(self):\n"
        "        raise ValueError('not a descriptor')\n"
        "def use():\n"
        "    with pytest.raises(ValueError):\n"
        "        Receiver().value\n",
    )

    with pytest.raises(SugarNotWritten):
        _body_attribute(tree).sugar().desugar(None)


def test_pandas_303_abstract_method_property_is_the_concrete_reproducer() -> None:
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
    halted = next(face for face in outcome.exits if isinstance(face, Halted))
    effect = halted.effect
    assert isinstance(effect, RaiseEffect)
    assert effect.exception_name == "AbstractMethodError"
    assert effect.exception_type_coordinate is not None
    assert effect.occurrence_id is not None
    assert effect.producer_node_owner == "Attribute"
