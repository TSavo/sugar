"""Publication of source-defined context protocol coordinates.

A class resource publishes CONTEXT_ENTER / CONTEXT_EXIT from its own class
source.  Builtin open publishes neither slot.

A decorated generator function is never a manager by its decorator's body:
its name is bound to the decorators' result, and what a call of it returns is
the one decorator application's (``DecoratorApplicationSugar``, #7757).  No
decorator body is read to name a returned manager class or its enter/exit
definitions.

No source scanning or first-candidate selection.
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


def _populate_local(tmp_path: Path, source: str):
    path = tmp_path / "local_consumer.py"
    path.write_text(source, encoding="utf-8")
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
    return context


def _published_protocol_slots(context) -> list:
    return [
        (receiver, slot)
        for (receiver, slot), value in context.contract_refs.native_definitions.items()
        if slot in (NativeProtocolSlot.CONTEXT_ENTER, NativeProtocolSlot.CONTEXT_EXIT)
        and not isinstance(value, NativeDefinitionCoordinateGapV1)
    ]


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


def test_a_source_decorated_generator_is_never_a_manager_by_its_decorator_body(
    tmp_path: Path,
):
    """``@resource_manager def make_resource(): yield 1`` binds
    ``make_resource`` to ``resource_manager(make_resource)``.  The decorator's
    body returns a helper constructing ``ResourceCM``, but nothing here reads
    it: no frame is seated for the call and no enter/exit definition is
    published.  What the call returns is the one decorator application's."""
    context = _populate_local(
        tmp_path,
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
        "\n"
        "@resource_manager\n"
        "def make_resource():\n"
        "    yield 1\n"
        "\n"
        "def exercise():\n"
        "    with make_resource():\n"
        "        pass\n",
    )
    assert context.source_manager_provider_calls == {}
    assert _published_protocol_slots(context) == []


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
    assert _published_protocol_slots(context) == []


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
    # No decorator-body reader: a decorator's result is the one application's.
    for deleted in (
        "_protocol_coords_from_generator_decorators",
        "_construct_decorator_function",
        "_sole_returned_manager_class",
        "_publish_decorated_non_manager_head",
    ):
        assert not hasattr(derivation, deleted), deleted
    # No ast.parse of dependency source in the publication path.
    assert "ast.parse" not in source
    assert "ast.walk" not in source
