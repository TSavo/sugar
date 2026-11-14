from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.outcome.exit_set import Halted
from sugar_lift_python_source.manager_summary_derivation import (
    populate_source_derived_resource_refs,
)
from sugar_lift_python_source.dependency_artifact import (
    authenticate_dependency_top_level,
)
from sugar_lift_python_source.resolution_session import SourceResolutionSession
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.nodes import Attribute, With
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _identity(name: str):
    from sugar_lift_py_tests.floor.ground_exit import (
        _builtin_exception_identity,
    )

    identity, _mro = _builtin_exception_identity(name)
    assert identity is not None, f"{name!r} is not a builtin exception identity"
    return identity


def _import_identity(qualified: str):
    from sugar_lift_py_tests.ir import ctor, str_const

    return ctor(
        "python:exception_type_identity",
        [str_const("import"), str_const(qualified)],
    )


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
    pytest_graph = authenticate_dependency_top_level("pytest")
    if pytest_graph.artifact_kind != "distribution":
        raise AssertionError("installed pytest slice requires a distribution graph")
    session = SourceResolutionSession(
        enrolled_distributions=frozenset({pytest_graph.distribution_name})
    )
    session.dependency_graphs["pytest"] = pytest_graph
    populate_source_derived_resource_refs(
        tree, root=tmp_path, path=path, session=session
    )
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
    assert effect.exception_type_coordinate == _identity("ValueError")
    assert isinstance(effect.occurrence_id, str) and ":" in effect.occurrence_id, (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {effect.occurrence_id!r}"
    )
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
    assert halted.effect.exception_type_coordinate == _import_identity(
        "provider.errors.CustomError"
    )
    assert (
        isinstance(halted.effect.occurrence_id, str)
        and ":" in halted.effect.occurrence_id
    ), (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {halted.effect.occurrence_id!r}"
    )


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

    assert outcome.completed_value() is not None


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
    assert effect.exception_type_coordinate == _import_identity(
        "pandas.errors.AbstractMethodError"
    )
    assert isinstance(effect.occurrence_id, str) and ":" in effect.occurrence_id, (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {effect.occurrence_id!r}"
    )
    assert effect.producer_node_owner == "Attribute"


@pytest.mark.parametrize("name", ["ValueError", "KeyError", "RuntimeError"])
@pytest.mark.parametrize("style", ["module_alias", "from_alias"])
def test_imported_builtin_property_raise_keeps_language_identity_and_ancestry(
    tmp_path, name, style
):
    declaration, operand = (
        ("import builtins as errors\n", f"errors.{name}")
        if style == "module_alias"
        else (f"from builtins import {name} as ImportedError\n", "ImportedError")
    )
    tree = _tree(
        tmp_path,
        "import pytest\n" + declaration + "class Receiver:\n"
        "    @property\n"
        "    def value(self):\n"
        f"        raise {operand}('source getter')\n"
        "def use():\n"
        f"    with pytest.raises({name}):\n"
        "        Receiver().value\n",
    )
    outcome = _body_attribute(tree).sugar().desugar(None)
    assert isinstance(outcome, ExitSet)
    halted = tuple(face for face in outcome.exits if isinstance(face, Halted))
    assert len(halted) == 1
    effect = halted[0].effect
    assert isinstance(effect, RaiseEffect)
    assert effect.exception_type_coordinate == _identity(name)
    assert effect.exception_type_coordinate != _import_identity(f"builtins.{name}")
    assert effect.exception_type_coordinate != _identity("TypeError")
    assert effect.exception_type_mro is not None
    assert _identity(name) in effect.exception_type_mro
    assert _identity("Exception") in effect.exception_type_mro
    assert effect.producer_node_owner == "Attribute"


def test_nonbuiltin_provider_with_builtin_suffix_keeps_its_own_identity(tmp_path):
    tree = _tree(
        tmp_path,
        "import pytest\n"
        "import foreign.builtins as errors\n"
        "class Receiver:\n"
        "    @property\n"
        "    def value(self):\n"
        "        raise errors.ValueError('source getter')\n"
        "def use():\n"
        "    with pytest.raises(ValueError):\n"
        "        Receiver().value\n",
    )
    outcome = _body_attribute(tree).sugar().desugar(None)
    assert isinstance(outcome, ExitSet)
    effect = next(face.effect for face in outcome.exits if isinstance(face, Halted))
    assert isinstance(effect, RaiseEffect)
    assert effect.exception_type_coordinate == _import_identity(
        "foreign.builtins.ValueError"
    )
    assert effect.exception_type_coordinate != _identity("ValueError")
    assert effect.exception_type_mro is None


def test_unknown_builtin_member_cannot_authenticate_a_property_raise(tmp_path):
    from sugar_lift_py_tests.effect import UndeterminedRaiseEffect

    tree = _tree(
        tmp_path,
        "import pytest\n"
        "import builtins as errors\n"
        "class Receiver:\n"
        "    @property\n"
        "    def value(self):\n"
        "        raise errors.UnwrittenError('source getter')\n"
        "def use():\n"
        "    with pytest.raises(ValueError):\n"
        "        Receiver().value\n",
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
        "import pytest\n"
        "import builtins as errors\n"
        "errors = replacement\n"
        "class Receiver:\n"
        "    @property\n"
        "    def value(self):\n"
        "        raise errors.ValueError('source getter')\n"
        "def use():\n"
        "    with pytest.raises(ValueError):\n"
        "        Receiver().value\n",
    )
    outcome = _body_attribute(tree).sugar().desugar(None)
    assert isinstance(outcome, ExitSet)
    effect = next(face.effect for face in outcome.exits if isinstance(face, Halted))
    assert isinstance(effect, UndeterminedRaiseEffect)
    assert not isinstance(effect, RaiseEffect)
