from __future__ import annotations

import csv
import importlib.metadata
from pathlib import Path

import pytest

from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.manager_summary_derivation import (
    _projected_manager_call_uses,
    populate_source_derived_resource_refs,
)
from sugar_source_tree.nodes import With
from sugar_source_tree.tree import SourceFile

PANDAS_SOURCE_CID = (
    "blake3-512:60e7b5ba2c971960e4d8edcaa85e916704dc8bfb977bc15dafb2f2b3e87458ff"
    "ba4b2f823e500c4c591a968b7c3e8ed436035aa171e8b3227055d9956147fae1"
)
PANDAS_MANIFEST_CID = (
    "blake3-512:6f317a5a489eb7e730064d79792f0d1656723130603309e2f2ed9cbedb604eda1"
    "c4b77a26dc90c980411292ea3994af9015da4cd850b5a307af5a4998b563530"
)


def _pandas_construction_root() -> Path:
    """Distribution seat is site-packages; corpus identity is the package root."""
    corpus = authenticated_pandas_corpus()
    assert (corpus.version, corpus.manifest_cid, corpus.file_count) == (
        "3.0.3",
        PANDAS_MANIFEST_CID,
        1421,
    )
    return corpus.root.parent


def _pandas_consumer_path() -> Path:
    corpus = authenticated_pandas_corpus()
    path = corpus.root / "tests/io/formats/test_ipython_compat.py"
    assert path.is_file()
    assert blake3_512_of(path.read_bytes()) == PANDAS_SOURCE_CID
    return path


def _real_tree():
    root = _pandas_construction_root()
    path = _pandas_consumer_path()
    return open_source_file_for_construction(
        path,
        root=root,
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
        populate_derived=False,
    )


def _line_32_with(tree):
    return next(
        node
        for node in tree.nodes()
        if node.kind == "With" and node.line_col_span().start_line == 32
    )


def _generator_distribution(root: Path, source: str, *, exported: str = "acquire"):
    package = root / "arbitrary"
    package.mkdir()
    (package / "__init__.py").write_text(
        f"from arbitrary.manager import {exported}\n", encoding="utf-8"
    )
    (package / "manager.py").write_text(source, encoding="utf-8")
    metadata = root / "arbitrary_dist-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: arbitrary-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    files = (
        "arbitrary/__init__.py",
        "arbitrary/manager.py",
        "arbitrary_dist-1.0.dist-info/METADATA",
        "arbitrary_dist-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for file in files:
            writer.writerow((file, "", ""))
    return importlib.metadata.Distribution.at(metadata)


def test_local_two_name_managers_project_both_reaching_calls(tmp_path: Path) -> None:
    source = tmp_path / "truthful.py"
    source.write_text(
        "def exercise(make_manager):\n"
        "    opt = make_manager()\n"
        "    with_latex = make_manager()\n"
        "    with opt, with_latex:\n"
        "        pass\n",
        encoding="utf-8",
    )
    tree = open_source_file_for_construction(
        source,
        root=tmp_path,
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
        populate_derived=False,
    )
    site = next(
        node
        for node in tree.nodes()
        if node.kind == "With" and node.line_col_span().start_line == 4
    )

    assert [item.context_expr.kind for item in site.items] == ["Name", "Name"]
    projected = _projected_manager_call_uses(tree)
    rows = sorted(
        (call.line_col_span().start_line, coordinate.start_line, coordinate.start_col)
        for coordinate, call, _exit_face in projected.values()
        if coordinate.start_line == 4
    )
    assert rows == [(2, 4, 9), (3, 4, 14)]


def test_pandas_303_two_name_managers_project_their_assignment_calls() -> None:
    """The verified corpus site consumes two distinct acquired managers."""
    tree = _real_tree()
    site = _line_32_with(tree)
    assert [item.context_expr.kind for item in site.items] == ["Name", "Name"]

    projected = _projected_manager_call_uses(tree)
    rows = sorted(
        (call.line_col_span().start_line, coordinate.start_line, coordinate.start_col)
        for coordinate, call, _exit_face in projected.values()
        if coordinate.start_line == 32
    )
    assert rows == [(21, 32, 13), (30, 32, 18)]


def test_projection_is_a_transaction_and_does_not_mutate_the_source_tree() -> None:
    tree = _real_tree()
    site = _line_32_with(tree)
    before = tuple(item.context_expr for item in site.items)

    _projected_manager_call_uses(tree)

    assert tuple(item.context_expr for item in site.items) == before
    assert [item.context_expr.kind for item in site.items] == ["Name", "Name"]


def test_pandas_303_both_bare_managers_construct_independent_provider_frames() -> None:
    """Pinned multi-manager With: each Name constructs through its reaching call.

    Before: populate raised SourceCallBindingGap("unconsumed call actual") while
    resolving option_context helpers that raise OptionError(msg). After: both
    manager-use coordinates seat distinct generator frames, and With sugar is
    GeneratorWithSugar without any SourceCallBindingGap.
    """
    tree = _real_tree()
    root = _pandas_construction_root()
    path = _pandas_consumer_path()
    site = _line_32_with(tree)

    populate_source_derived_resource_refs(tree, root=root, path=path)

    context = tree.root.unit.construction_context
    seats = sorted(
        (coordinate.start_col, call.line_col_span().start_line)
        for coordinate, call in context.source_manager_provider_calls.items()
        if coordinate.start_line == 32
    )
    assert seats == [(13, 21), (18, 30)]

    frames = []
    for item in site.items:
        frame = site._generator_manager_frame(item)
        assert frame is not None
        assert frame.generator_steps is not None
        assert frame.parameter_kinds == ("vararg",)
        frames.append(frame.frame_cid)
    # Independent manager coordinates: two seats, same provider identity is fine,
    # but each item must resolve its own use-site seat (cols 13 and 18).
    assert len(frames) == 2
    assert [item.context_expr.kind for item in site.items] == ["Name", "Name"]

    sugar = site.sugar()
    assert isinstance(sugar, GeneratorWithSugar)


def test_truthful_local_two_assigned_generators_construct_and_desugar(
    tmp_path: Path,
) -> None:
    """Truthful twin: two bare Names that reach generator calls both construct."""
    distribution = _generator_distribution(
        tmp_path, "def acquire():\n    yield\n", exported="acquire"
    )
    consumer = (
        "import arbitrary\n"
        "def exercise():\n"
        "    first = arbitrary.acquire()\n"
        "    second = arbitrary.acquire()\n"
        "    with first, second:\n"
        "        pass\n"
    )
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=context,
    )
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        distribution_index={"arbitrary": distribution},
    )

    site = next(node for node in tree.nodes() if isinstance(node, With))
    assert [item.context_expr.kind for item in site.items] == ["Name", "Name"]
    seats = sorted(
        (coordinate.start_col, call.line_col_span().start_line)
        for coordinate, call in context.source_manager_provider_calls.items()
        if coordinate.start_line == 5
    )
    assert seats == [(9, 3), (16, 4)]
    assert all(site._generator_manager_frame(item) is not None for item in site.items)

    sugar = site.sugar()
    assert isinstance(sugar, GeneratorWithSugar)
    outcome = sugar.desugar()
    assert isinstance(outcome, Complete)


def test_lying_same_spelling_without_reaching_call_does_not_construct(
    tmp_path: Path,
) -> None:
    """Lying twin: bare Names with no reaching Call never mint provider seats."""
    source = tmp_path / "lying.py"
    source.write_text(
        "def exercise(opt_value, latex_value):\n"
        "    opt = opt_value\n"
        "    with_latex = latex_value\n"
        "    with opt, with_latex:\n"
        "        pass\n",
        encoding="utf-8",
    )
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = open_source_file_for_construction(
        source,
        root=tmp_path,
        construction_context=context,
        populate_derived=False,
    )
    populate_source_derived_resource_refs(tree, root=tmp_path, path=source)

    site = next(
        node
        for node in tree.nodes()
        if isinstance(node, With) and node.line_col_span().start_line == 4
    )
    assert context.source_manager_provider_calls == {}
    assert all(site._generator_manager_frame(item) is None for item in site.items)
    assert _projected_manager_call_uses(tree) == {}


def test_undecided_rebinding_does_not_invent_a_second_manager_call(
    tmp_path: Path,
) -> None:
    """Lying twin: the second Name no longer reaches acquired call state."""
    source = tmp_path / "twin.py"
    source.write_text(
        "def exercise(make_manager, undecided):\n"
        "    first = make_manager()\n"
        "    second = make_manager()\n"
        "    second = undecided\n"
        "    with first, second:\n"
        "        pass\n",
        encoding="utf-8",
    )
    tree = open_source_file_for_construction(
        source,
        root=tmp_path,
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
        populate_derived=False,
    )

    projected = _projected_manager_call_uses(tree)
    rows = [
        (coordinate.start_line, coordinate.start_col, call.line_col_span().start_line)
        for coordinate, call, _exit_face in projected.values()
        if coordinate.start_line == 5
    ]
    assert rows == [(5, 9, 2)]


def test_independent_manager_coordinates_survive_shared_provider_spelling(
    tmp_path: Path,
) -> None:
    """Two uses of the same provider function keep independent use coordinates."""
    distribution = _generator_distribution(
        tmp_path, "def acquire():\n    yield\n", exported="acquire"
    )
    consumer = (
        "import arbitrary\n"
        "def exercise():\n"
        "    left = arbitrary.acquire()\n"
        "    right = arbitrary.acquire()\n"
        "    with left, right:\n"
        "        pass\n"
    )
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=context,
    )
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        distribution_index={"arbitrary": distribution},
    )
    site = next(node for node in tree.nodes() if isinstance(node, With))
    use_coords = [
        item._manager_use_site_span()
        for item in site.items
    ]
    assert use_coords[0] != use_coords[1]
    provider_calls = [
        site._provider_manager_call(item) for item in site.items
    ]
    assert all(call is not None for call in provider_calls)
    assert provider_calls[0].line_col_span() != provider_calls[1].line_col_span()


def test_mechanism_modules_contain_no_vendor_name_literals() -> None:
    """Provider construction cannot admit this site by manager spelling."""
    import ast
    import inspect
    import textwrap

    import sugar_lift_python_source.manager_summary_derivation as derivation
    import sugar_source_tree.nodes as nodes

    for module in (derivation, nodes):
        tree = ast.parse(textwrap.dedent(inspect.getsource(module)))
        literals = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        assert literals.isdisjoint(
            {
                "opt",
                "with_latex",
                "option_context",
                "pytest.raises",
                "external_error_raised",
            }
        )
