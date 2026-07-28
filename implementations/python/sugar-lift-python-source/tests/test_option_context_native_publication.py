"""Publication of source-defined context protocol coordinates.

A source-defined context manager publishes authenticated definition
coordinates for both ``CONTEXT_ENTER`` and ``CONTEXT_EXIT`` into
``ResolvedContractRefsV1.native_definitions``, keyed by the manager use-site
receiver. Consumption reads them via ``require_native_definition``; this arm
never resolves at desugar time.

For ``@contextmanager`` generators (pandas ``option_context``), enter/exit
are the language generator-CM class methods from authenticated contextlib
source — the real method bodies that drive the generator's nested
try/yield/finally. Builtin ``open`` has no source definition and therefore
publishes neither slot.

No edits to ``nodes.py`` / ``with_resource_sugar.py`` (consumption is owned
elsewhere).
"""

from __future__ import annotations

import csv
import importlib.metadata
from pathlib import Path

from sugar_lift_py_tests.context_manager_resolution import (
    NativeDefinitionCoordinateGapV1,
    NativeProtocolSlot,
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.manager_summary_derivation import (
    _generator_context_manager_protocol_coordinates,
    populate_source_derived_resource_refs,
)
from sugar_source_tree.tree import SourceFile


def _write_class_resource_package(
    tmp_path: Path, source_text: str, package_name: str = "arbitrary"
):
    package = tmp_path / package_name
    package.mkdir(exist_ok=True)
    (package / "__init__.py").write_text(
        f"from {package_name}.manager import make_guard\n", encoding="utf-8"
    )
    (package / "manager.py").write_text(source_text, encoding="utf-8")
    metadata = tmp_path / f"{package_name}_dist-1.0.dist-info"
    metadata.mkdir(exist_ok=True)
    (metadata / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {package_name}-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    files = (
        f"{package_name}/__init__.py",
        f"{package_name}/manager.py",
        f"{package_name}_dist-1.0.dist-info/METADATA",
        f"{package_name}_dist-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for file in files:
            writer.writerow((file, "", ""))
    return importlib.metadata.Distribution.at(metadata)


def _populate_consumer(tmp_path: Path, dist, package: str = "arbitrary"):
    consumer = tmp_path / "consumer.py"
    consumer.write_text(
        f"from {package} import make_guard\n" "with make_guard():\n" "    pass\n",
        encoding="utf-8",
    )
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (
            consumer.read_text(encoding="utf-8"),
            str(consumer),
            blake3_512_of(consumer.read_bytes()),
        ),
        construction_context=context,
    )
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=consumer,
        distribution_index={package: dist},
    )
    return context


def test_generator_cm_protocol_coordinates_are_distinct_authenticated_methods():
    """GCM enter and exit are real, distinct source spans."""
    coords = _generator_context_manager_protocol_coordinates()
    assert coords is not None
    enter, exit_ = coords
    assert isinstance(enter, SourceFragmentCoordinateV1)
    assert isinstance(exit_, SourceFragmentCoordinateV1)
    assert enter != exit_
    assert enter.source_cid == exit_.source_cid
    assert enter.source_cid.startswith("blake3-512:")
    assert (enter.start_line, enter.start_col) < (exit_.start_line, exit_.start_col)


def test_option_context_publishes_both_context_enter_and_exit_coordinates():
    """Positive arm: seated generator manager publishes both protocol slots."""
    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction

    corpus = authenticated_pandas_corpus()
    root = corpus.root.parent
    path = root / "pandas/tests/io/formats/test_ipython_compat.py"
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = open_source_file_for_construction(
        path, root=root, construction_context=context, populate_derived=False
    )
    populate_source_derived_resource_refs(tree, root=root, path=path)

    receivers = [
        coordinate
        for coordinate in context.source_manager_provider_calls
        if coordinate.start_line == 25
    ]
    assert receivers, "expected seated option_context use at line 25"
    receiver = receivers[0]
    expected = _generator_context_manager_protocol_coordinates()
    assert expected is not None
    enter_expected, exit_expected = expected

    enter = context.contract_refs.require_native_definition(
        receiver, NativeProtocolSlot.CONTEXT_ENTER
    )
    exit_ = context.contract_refs.require_native_definition(
        receiver, NativeProtocolSlot.CONTEXT_EXIT
    )
    assert enter == enter_expected
    assert exit_ == exit_expected
    assert enter != exit_
    assert enter != exit_expected
    assert exit_ != enter_expected


def test_option_context_publishes_at_every_seated_generator_use_site():
    """Publication is keyed by use-site receiver, not a single global row."""
    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction

    corpus = authenticated_pandas_corpus()
    root = corpus.root.parent
    path = root / "pandas/tests/io/formats/test_ipython_compat.py"
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = open_source_file_for_construction(
        path, root=root, construction_context=context, populate_derived=False
    )
    populate_source_derived_resource_refs(tree, root=root, path=path)

    expected = _generator_context_manager_protocol_coordinates()
    assert expected is not None
    published = 0
    for receiver in context.source_manager_provider_calls:
        enter = context.contract_refs.require_native_definition(
            receiver, NativeProtocolSlot.CONTEXT_ENTER
        )
        exit_ = context.contract_refs.require_native_definition(
            receiver, NativeProtocolSlot.CONTEXT_EXIT
        )
        if isinstance(enter, NativeDefinitionCoordinateGapV1):
            continue
        assert enter == expected[0]
        assert exit_ == expected[1]
        published += 1
    assert published >= 1


def test_open_produces_no_source_definition(tmp_path: Path):
    """Discrimination arm: builtin open publishes neither protocol slot."""
    path = tmp_path / "open_consumer.py"
    path.write_text(
        "def exercise(path):\n"
        "    with open(path) as handle:\n"
        "        return handle\n",
        encoding="utf-8",
    )
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (path.read_text(encoding="utf-8"), str(path), blake3_512_of(path.read_bytes())),
        construction_context=context,
    )
    populate_source_derived_resource_refs(tree, root=tmp_path, path=path)

    assert context.source_manager_provider_calls == {}
    for (receiver, slot), value in context.contract_refs.native_definitions.items():
        del receiver
        if slot in (
            NativeProtocolSlot.CONTEXT_ENTER,
            NativeProtocolSlot.CONTEXT_EXIT,
        ):
            assert isinstance(value, NativeDefinitionCoordinateGapV1)
    from sugar_source_tree.nodes import With

    for node in tree.nodes():
        if not isinstance(node, With):
            continue
        for item in node.items:
            start_line, start_col, end_line, end_col = item._manager_use_site_span()
            receiver = SourceFragmentCoordinateV1(
                node.unit.source_cid,
                start_line,
                start_col,
                end_line,
                end_col,
            )
            enter = context.contract_refs.require_native_definition(
                receiver, NativeProtocolSlot.CONTEXT_ENTER
            )
            exit_ = context.contract_refs.require_native_definition(
                receiver, NativeProtocolSlot.CONTEXT_EXIT
            )
            assert isinstance(enter, NativeDefinitionCoordinateGapV1)
            assert isinstance(exit_, NativeDefinitionCoordinateGapV1)
            assert enter.reason.startswith("authenticated source definition")
            assert exit_.reason.startswith("authenticated source definition")


def test_changing_enter_source_definition_changes_its_coordinate(tmp_path: Path):
    """Acceptance: mutating enter source changes the enter coordinate."""
    base = (
        "class Guard:\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return False\n"
        "\n"
        "def make_guard():\n"
        "    return Guard()\n"
    )
    shifted = (
        "class Guard:\n"
        "    def helper(self):\n"
        "        return self\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return False\n"
        "\n"
        "def make_guard():\n"
        "    return Guard()\n"
    )
    first_root = tmp_path / "first"
    first_root.mkdir()
    first = _populate_consumer(
        first_root,
        _write_class_resource_package(first_root, base, "guardpkg"),
        "guardpkg",
    )
    first_refs = list(first.source_derived_contract_refs)
    assert first_refs, "expected class resource publication"
    first_receiver = first_refs[0]
    first_enter = first.contract_refs.require_native_definition(
        first_receiver, NativeProtocolSlot.CONTEXT_ENTER
    )
    first_exit = first.contract_refs.require_native_definition(
        first_receiver, NativeProtocolSlot.CONTEXT_EXIT
    )
    assert isinstance(first_enter, SourceFragmentCoordinateV1)
    assert isinstance(first_exit, SourceFragmentCoordinateV1)

    second_root = tmp_path / "second"
    second_root.mkdir()
    second = _populate_consumer(
        second_root,
        _write_class_resource_package(second_root, shifted, "guardpkg"),
        "guardpkg",
    )
    second_refs = list(second.source_derived_contract_refs)
    assert second_refs
    second_receiver = second_refs[0]
    second_enter = second.contract_refs.require_native_definition(
        second_receiver, NativeProtocolSlot.CONTEXT_ENTER
    )
    second_exit = second.contract_refs.require_native_definition(
        second_receiver, NativeProtocolSlot.CONTEXT_EXIT
    )
    assert isinstance(second_enter, SourceFragmentCoordinateV1)
    assert isinstance(second_exit, SourceFragmentCoordinateV1)

    assert first_enter != second_enter
    assert first_enter.start_line != second_enter.start_line
    assert second_enter.start_line > first_enter.start_line
    assert second_exit != second_enter
    assert second_exit != first_enter
    assert first_exit != first_enter


def test_changing_exit_source_definition_changes_its_coordinate(tmp_path: Path):
    """Acceptance: mutating exit body changes the exit coordinate."""
    base = (
        "class Guard:\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return False\n"
        "\n"
        "def make_guard():\n"
        "    return Guard()\n"
    )
    longer_exit = (
        "class Guard:\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        # restore then release\n"
        "        return False\n"
        "\n"
        "def make_guard():\n"
        "    return Guard()\n"
    )
    first_root = tmp_path / "exit_first"
    first_root.mkdir()
    first = _populate_consumer(
        first_root,
        _write_class_resource_package(first_root, base, "exitpkg"),
        "exitpkg",
    )
    first_receiver = list(first.source_derived_contract_refs)[0]
    first_enter = first.contract_refs.require_native_definition(
        first_receiver, NativeProtocolSlot.CONTEXT_ENTER
    )
    first_exit = first.contract_refs.require_native_definition(
        first_receiver, NativeProtocolSlot.CONTEXT_EXIT
    )

    second_root = tmp_path / "exit_second"
    second_root.mkdir()
    second = _populate_consumer(
        second_root,
        _write_class_resource_package(second_root, longer_exit, "exitpkg"),
        "exitpkg",
    )
    second_receiver = list(second.source_derived_contract_refs)[0]
    second_enter = second.contract_refs.require_native_definition(
        second_receiver, NativeProtocolSlot.CONTEXT_ENTER
    )
    second_exit = second.contract_refs.require_native_definition(
        second_receiver, NativeProtocolSlot.CONTEXT_EXIT
    )

    assert isinstance(first_exit, SourceFragmentCoordinateV1)
    assert isinstance(second_exit, SourceFragmentCoordinateV1)
    assert first_exit != second_exit
    assert (
        first_exit.end_line != second_exit.end_line
        or first_exit.source_cid != second_exit.source_cid
    )
    assert isinstance(first_enter, SourceFragmentCoordinateV1)
    assert isinstance(second_enter, SourceFragmentCoordinateV1)
    assert first_enter.start_line == second_enter.start_line
    assert first_enter.start_col == second_enter.start_col


def test_class_resource_publishes_enter_exit_from_class_source(tmp_path: Path):
    """Positive arm: class-source enter/exit definition sites publish."""
    dist = _write_class_resource_package(
        tmp_path,
        (
            "class Guard:\n"
            "    def __enter__(self):\n"
            "        return self\n"
            "    def __exit__(self, effect_type, effect, traceback):\n"
            "        return False\n"
            "\n"
            "def make_guard():\n"
            "    return Guard()\n"
        ),
    )
    context = _populate_consumer(tmp_path, dist)
    refs = list(context.source_derived_contract_refs)
    assert refs, "expected source-derived class resource ref"
    receiver = refs[0]
    enter = context.contract_refs.require_native_definition(
        receiver, NativeProtocolSlot.CONTEXT_ENTER
    )
    exit_ = context.contract_refs.require_native_definition(
        receiver, NativeProtocolSlot.CONTEXT_EXIT
    )
    assert isinstance(enter, SourceFragmentCoordinateV1)
    assert isinstance(exit_, SourceFragmentCoordinateV1)
    assert enter != exit_
    assert enter.start_line < exit_.start_line


def test_lying_twin_spelling_without_binding_publishes_nothing(tmp_path: Path):
    """Discrimination arm: spelling the name grants no native definitions."""
    path = tmp_path / "lying.py"
    path.write_text(
        "def exercise(option_context):\n"
        '    with option_context("display.max_rows", 10):\n'
        "        pass\n",
        encoding="utf-8",
    )
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (path.read_text(encoding="utf-8"), str(path), blake3_512_of(path.read_bytes())),
        construction_context=context,
    )
    populate_source_derived_resource_refs(tree, root=tmp_path, path=path)

    assert context.source_manager_provider_calls == {}
    assert not any(
        slot in (NativeProtocolSlot.CONTEXT_ENTER, NativeProtocolSlot.CONTEXT_EXIT)
        and not isinstance(value, NativeDefinitionCoordinateGapV1)
        for (receiver, slot), value in context.contract_refs.native_definitions.items()
    )


def test_enter_and_exit_coordinates_are_not_interchangeable():
    """Discrimination arm: enter coord must not satisfy the exit slot."""
    coords = _generator_context_manager_protocol_coordinates()
    assert coords is not None
    enter, exit_ = coords
    assert enter != exit_
    assert enter.start_line != exit_.start_line


def test_publication_path_has_no_option_context_vendor_literal():
    """No spelling admission rule for the manager name."""
    import ast
    import inspect
    import textwrap

    import sugar_lift_python_source.manager_summary_derivation as derivation

    module = ast.parse(textwrap.dedent(inspect.getsource(derivation)))
    literals = {
        node.value
        for node in ast.walk(module)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert literals.isdisjoint(
        {
            "option_context",
            "pd.option_context",
            "ensure_clean",
            "display.max_rows",
            "_GeneratorContextManager",
        }
    )
