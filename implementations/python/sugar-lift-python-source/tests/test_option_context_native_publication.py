"""Publication of source-defined context protocol coordinates.

Producer path: authenticated construction of the generator function's
decorator/helper yields the exact returned generator-CM class; that class's
constructed method frames publish CONTEXT_ENTER / CONTEXT_EXIT into
ResolvedContractRefsV1.native_definitions. Builtin open publishes neither slot.

No nodes.py / WithResourceSugar edits. No source scanning or first-candidate
selection.
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
from sugar_lift_python_source.manager_summary_derivation import (
    _classes_constructed_by_returns,
    _enter_exit_sites_from_class_def,
    _protocol_coords_from_generator_decorators,
    _sole_returned_manager_class,
    populate_source_derived_resource_refs,
)
from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_python_source.resolution_session import SourceResolutionSession
from sugar_source_tree.tree import SourceFile


def _write_package(tmp_path: Path, files: dict[str, str], package_name: str):
    package = tmp_path / package_name
    package.mkdir(exist_ok=True)
    for relative, text in files.items():
        target = (
            package / relative if relative != "__init__.py" else package / "__init__.py"
        )
        if "/" in relative:
            target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    # Also allow top-level seats under package root via files keys
    metadata = tmp_path / f"{package_name}_dist-1.0.dist-info"
    metadata.mkdir(exist_ok=True)
    (metadata / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {package_name}-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    seats = [f"{package_name}/{rel}" for rel in files]
    seats.extend(
        [
            f"{package_name}_dist-1.0.dist-info/METADATA",
            f"{package_name}_dist-1.0.dist-info/RECORD",
        ]
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for seat in seats:
            writer.writerow((seat, "", ""))
    return importlib.metadata.Distribution.at(metadata)


def _populate(tmp_path: Path, dist, package: str, consumer_source: str):
    consumer = tmp_path / "consumer.py"
    consumer.write_text(consumer_source, encoding="utf-8")
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        path_source(str(consumer)),
        construction_context=context,
    )
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=consumer,
        distribution_index={package: dist},
        session=SourceResolutionSession(
            enrolled_distributions=frozenset({dist.metadata["Name"]})
        ),
    )
    return context


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
    populate_source_derived_resource_refs(
        tree,
        root=root,
        path=path,
        session=SourceResolutionSession(
            enrolled_distributions=frozenset({corpus.distribution})
        ),
    )

    receivers = [
        coordinate
        for coordinate in context.source_manager_provider_calls
        if coordinate.start_line == 25
    ]
    assert receivers, "expected seated option_context use at line 25"
    receiver = receivers[0]
    enter = context.contract_refs.require_native_definition(
        receiver, NativeProtocolSlot.CONTEXT_ENTER
    )
    exit_ = context.contract_refs.require_native_definition(
        receiver, NativeProtocolSlot.CONTEXT_EXIT
    )
    assert isinstance(enter, SourceFragmentCoordinateV1)
    assert isinstance(exit_, SourceFragmentCoordinateV1)
    assert enter != exit_
    assert enter.source_cid == exit_.source_cid
    assert enter.source_cid.startswith("blake3-512:")
    assert (enter.start_line, enter.start_col) < (exit_.start_line, exit_.start_col)


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
    populate_source_derived_resource_refs(
        tree,
        root=root,
        path=path,
        session=SourceResolutionSession(
            enrolled_distributions=frozenset({corpus.distribution})
        ),
    )

    published = 0
    sample = None
    for receiver in context.source_manager_provider_calls:
        enter = context.contract_refs.require_native_definition(
            receiver, NativeProtocolSlot.CONTEXT_ENTER
        )
        exit_ = context.contract_refs.require_native_definition(
            receiver, NativeProtocolSlot.CONTEXT_EXIT
        )
        if isinstance(enter, NativeDefinitionCoordinateGapV1):
            continue
        assert isinstance(exit_, SourceFragmentCoordinateV1)
        if sample is None:
            sample = (enter, exit_)
        else:
            assert enter == sample[0]
            assert exit_ == sample[1]
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
        path_source(str(path)),
        construction_context=context,
    )
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        session=SourceResolutionSession(enrolled_distributions=frozenset()),
    )

    assert context.source_manager_provider_calls == {}
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


def test_decorator_construction_yields_returned_class_method_coordinates(
    tmp_path: Path,
):
    """Authenticated decorator/helper construction owns enter/exit sites."""
    dist = _write_package(
        tmp_path,
        {
            "__init__.py": "from deco_pkg.factory import make_resource\n",
            "factory.py": (
                "from deco_pkg.wrapper import resource_manager\n"
                "\n"
                "@resource_manager\n"
                "def make_resource():\n"
                "    yield 1\n"
            ),
            "wrapper.py": (
                "class ResourceCM:\n"
                "    def __init__(self, gen):\n"
                "        self.gen = gen\n"
                "    def __enter__(self):\n"
                "        return next(self.gen)\n"
                "    def __exit__(self, effect_type, effect, traceback):\n"
                "        return False\n"
                "\n"
                "def resource_manager(func):\n"
                "    def helper(*args, **kwargs):\n"
                "        return ResourceCM(func(*args, **kwargs))\n"
                "    return helper\n"
            ),
        },
        "deco_pkg",
    )
    context = _populate(
        tmp_path,
        dist,
        "deco_pkg",
        "from deco_pkg import make_resource\n" "with make_resource():\n" "    pass\n",
    )
    receivers = list(context.source_manager_provider_calls)
    assert receivers, "expected generator provider seat"
    receiver = receivers[0]
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


def test_content_tampered_enter_source_changes_coordinate(tmp_path: Path):
    """Acceptance: mutating enter definition changes its published coordinate."""
    base_wrapper = (
        "class ResourceCM:\n"
        "    def __init__(self, gen):\n"
        "        self.gen = gen\n"
        "    def __enter__(self):\n"
        "        return next(self.gen)\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return False\n"
        "\n"
        "def resource_manager(func):\n"
        "    def helper(*args, **kwargs):\n"
        "        return ResourceCM(func(*args, **kwargs))\n"
        "    return helper\n"
    )
    tampered_wrapper = (
        "class ResourceCM:\n"
        "    def __init__(self, gen):\n"
        "        self.gen = gen\n"
        "    def helper(self):\n"
        "        return self\n"
        "    def __enter__(self):\n"
        "        return next(self.gen)\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return False\n"
        "\n"
        "def resource_manager(func):\n"
        "    def helper(*args, **kwargs):\n"
        "        return ResourceCM(func(*args, **kwargs))\n"
        "    return helper\n"
    )
    factory = (
        "from tamper_pkg.wrapper import resource_manager\n"
        "\n"
        "@resource_manager\n"
        "def make_resource():\n"
        "    yield 1\n"
    )
    first_root = tmp_path / "first"
    first_root.mkdir()
    first = _populate(
        first_root,
        _write_package(
            first_root,
            {
                "__init__.py": "from tamper_pkg.factory import make_resource\n",
                "factory.py": factory,
                "wrapper.py": base_wrapper,
            },
            "tamper_pkg",
        ),
        "tamper_pkg",
        "from tamper_pkg import make_resource\nwith make_resource():\n    pass\n",
    )
    second_root = tmp_path / "second"
    second_root.mkdir()
    second = _populate(
        second_root,
        _write_package(
            second_root,
            {
                "__init__.py": "from tamper_pkg.factory import make_resource\n",
                "factory.py": factory,
                "wrapper.py": tampered_wrapper,
            },
            "tamper_pkg",
        ),
        "tamper_pkg",
        "from tamper_pkg import make_resource\nwith make_resource():\n    pass\n",
    )
    first_receiver = next(iter(first.source_manager_provider_calls))
    second_receiver = next(iter(second.source_manager_provider_calls))
    first_enter = first.contract_refs.require_native_definition(
        first_receiver, NativeProtocolSlot.CONTEXT_ENTER
    )
    second_enter = second.contract_refs.require_native_definition(
        second_receiver, NativeProtocolSlot.CONTEXT_ENTER
    )
    assert isinstance(first_enter, SourceFragmentCoordinateV1)
    assert isinstance(second_enter, SourceFragmentCoordinateV1)
    assert first_enter != second_enter
    assert first_enter.start_line != second_enter.start_line


def test_two_plausible_returned_classes_refuse_first_candidate(tmp_path: Path):
    """Discrimination: two return classes cannot select the first."""
    from sugar_source_tree.nodes import FunctionDef

    path = tmp_path / "ambiguous.py"
    path.write_text(
        "class AlphaCM:\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return False\n"
        "\n"
        "class BetaCM:\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return False\n"
        "\n"
        "def resource_manager(func):\n"
        "    def helper(*args, **kwargs):\n"
        "        if args:\n"
        "            return AlphaCM()\n"
        "        return BetaCM()\n"
        "    return helper\n",
        encoding="utf-8",
    )
    tree = SourceFile(path_source(str(path)))
    decorator_fn = next(
        node
        for node in tree.root.body
        if isinstance(node, FunctionDef) and node.name == "resource_manager"
    )
    assert _sole_returned_manager_class(decorator_fn) is None
    classes = _classes_constructed_by_returns(
        next(
            node
            for node in decorator_fn.body
            if isinstance(node, FunctionDef) and node.name == "helper"
        ).body
    )
    assert len(classes) == 2


def test_separate_source_cids_do_not_share_coordinates(tmp_path: Path):
    """Separate authenticated decorator modules cannot share coordinates."""
    wrapper_a = (
        "class ResourceCM:\n"
        "    def __init__(self, gen):\n"
        "        self.gen = gen\n"
        "    def __enter__(self):\n"
        "        return next(self.gen)\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return False\n"
        "\n"
        "def resource_manager(func):\n"
        "    def helper(*args, **kwargs):\n"
        "        return ResourceCM(func(*args, **kwargs))\n"
        "    return helper\n"
    )
    # Different content → different source_cid even if spans align numerically.
    wrapper_b = (
        "class ResourceCM:\n"
        "    def __init__(self, gen):\n"
        "        self.gen = gen\n"
        "    def __enter__(self):\n"
        "        return next(self.gen)  # distinct body bytes\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return False\n"
        "\n"
        "def resource_manager(func):\n"
        "    def helper(*args, **kwargs):\n"
        "        return ResourceCM(func(*args, **kwargs))\n"
        "    return helper\n"
    )
    factory = (
        "from cid_pkg.wrapper import resource_manager\n"
        "\n"
        "@resource_manager\n"
        "def make_resource():\n"
        "    yield 1\n"
    )
    first_root = tmp_path / "cid_a"
    first_root.mkdir()
    first = _populate(
        first_root,
        _write_package(
            first_root,
            {
                "__init__.py": "from cid_pkg.factory import make_resource\n",
                "factory.py": factory,
                "wrapper.py": wrapper_a,
            },
            "cid_pkg",
        ),
        "cid_pkg",
        "from cid_pkg import make_resource\nwith make_resource():\n    pass\n",
    )
    second_root = tmp_path / "cid_b"
    second_root.mkdir()
    second = _populate(
        second_root,
        _write_package(
            second_root,
            {
                "__init__.py": "from cid_pkg.factory import make_resource\n",
                "factory.py": factory,
                "wrapper.py": wrapper_b,
            },
            "cid_pkg",
        ),
        "cid_pkg",
        "from cid_pkg import make_resource\nwith make_resource():\n    pass\n",
    )
    first_receiver = next(iter(first.source_manager_provider_calls))
    second_receiver = next(iter(second.source_manager_provider_calls))
    first_enter = first.contract_refs.require_native_definition(
        first_receiver, NativeProtocolSlot.CONTEXT_ENTER
    )
    second_enter = second.contract_refs.require_native_definition(
        second_receiver, NativeProtocolSlot.CONTEXT_ENTER
    )
    assert isinstance(first_enter, SourceFragmentCoordinateV1)
    assert isinstance(second_enter, SourceFragmentCoordinateV1)
    assert first_enter.source_cid != second_enter.source_cid
    assert first_enter != second_enter


def test_class_resource_publishes_enter_exit_from_class_source(tmp_path: Path):
    """Positive arm: class-source enter/exit definition sites publish."""
    dist = _write_package(
        tmp_path,
        {
            "__init__.py": "from class_pkg.manager import make_guard\n",
            "manager.py": (
                "class Guard:\n"
                "    def __enter__(self):\n"
                "        return self\n"
                "    def __exit__(self, effect_type, effect, traceback):\n"
                "        return False\n"
                "\n"
                "def make_guard():\n"
                "    return Guard()\n"
            ),
        },
        "class_pkg",
    )
    context = _populate(
        tmp_path,
        dist,
        "class_pkg",
        "from class_pkg import make_guard\nwith make_guard():\n    pass\n",
    )
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
        path_source(str(path)),
        construction_context=context,
    )
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        session=SourceResolutionSession(enrolled_distributions=frozenset()),
    )
    assert context.source_manager_provider_calls == {}
    assert not any(
        slot in (NativeProtocolSlot.CONTEXT_ENTER, NativeProtocolSlot.CONTEXT_EXIT)
        and not isinstance(value, NativeDefinitionCoordinateGapV1)
        for (receiver, slot), value in context.contract_refs.native_definitions.items()
    )


def test_publication_path_has_no_scan_or_vendor_literals():
    """No ast scan, no first-candidate cache, no manager spelling arms."""
    import ast
    import inspect
    import textwrap

    import sugar_lift_python_source.manager_summary_derivation as derivation

    source = textwrap.dedent(inspect.getsource(derivation))
    module = ast.parse(source)
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
            "contextmanager",
            "contextlib.py",
        }
    )
    # No process-global unkeyed cache residual.
    assert not hasattr(derivation, "_GENERATOR_CM_PROTOCOL_COORDS")
    # No ast.parse of dependency source in the publication path.
    assert "ast.parse" not in source
    assert "ast.walk" not in source
