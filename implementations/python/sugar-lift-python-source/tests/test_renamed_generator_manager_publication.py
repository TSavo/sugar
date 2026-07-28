"""Renamed-manager publication suite — generalization of generator-backed refs.

Unrelated source-defined generator managers (different names, modules, resource
shapes) publish authenticated enter/exit coordinates, generator construction
testimony, and the generator-backed resource ref through the **identical**
pipeline. A renamed import alias of one manager publishes the same testimony
modulo use-site coordinates. Builtin ``open`` still enrolls nothing.

Grep-proof: no test or production dispatch branch mentions a manager by name.
Tampered source refuses publication per manager. Consumption-free: tests only
assert publication into construction context tables.
"""

from __future__ import annotations

import ast
import csv
import importlib.metadata
import inspect
import textwrap
from dataclasses import dataclass
from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_contract import ProtocolResourceSemanticsV1
from sugar_lift_py_tests.context_manager_resolution import (
    NativeDefinitionCoordinateGapV1,
    NativeProtocolSlot,
    SourceDerivedGeneratorResourceRefV1,
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.manager_protocol_construction import (
    GeneratorBackedManagerProtocolV1,
)
from sugar_lift_python_source.manager_summary_derivation import (
    populate_source_derived_resource_refs,
)
from sugar_source_tree.tree import SourceFile

# ---------------------------------------------------------------------------
# Shared decorator CM wrapper — not a manager; the factory generators differ.
# ---------------------------------------------------------------------------

def _resource_wrapper(*, seal: str) -> str:
    """Per-package CM wrapper. Distinct ``seal`` bytes ⇒ distinct source_cid."""
    return (
        f"# package seal: {seal}\n"
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


@dataclass(frozen=True)
class _ManagerShape:
    """Parametric description of one unrelated generator manager family.

    Names and package ids exist only to build authenticated source files.
    Publication assertions never branch on these strings.
    """

    package: str
    export: str
    factory_module: str
    factory_source: str
    consumer_call: str
    # Distinct resource shape label for residual reporting only.
    shape: str


# Three UNRELATED generators: different packages, exports, modules, bodies.
# Export names deliberately avoid stdlib collisions (e.g. warnings.catch_warnings)
# so seating proves source-defined managers, not ambient builtins.
_SHAPES: tuple[_ManagerShape, ...] = (
    _ManagerShape(
        package="cfg_setter_pkg",
        export="set_config",
        factory_module="config_setter.py",
        factory_source=(
            "from cfg_setter_pkg.wrapper import resource_manager\n"
            "\n"
            "@resource_manager\n"
            "def set_config(key, value):\n"
            "    # config-setter shape: bind then restore\n"
            "    prior = None\n"
            "    yield (key, value, prior)\n"
        ),
        consumer_call="set_config('display.max_rows', 10)",
        shape="config-setter",
    ),
    _ManagerShape(
        package="warn_filter_pkg",
        export="filter_warnings",
        factory_module="warnings_filter.py",
        factory_source=(
            "from warn_filter_pkg.wrapper import resource_manager\n"
            "\n"
            "@resource_manager\n"
            "def filter_warnings(action):\n"
            "    # warnings-filter shape: filter stack push/pop\n"
            "    filters = [action]\n"
            "    yield filters\n"
        ),
        consumer_call="filter_warnings('ignore')",
        shape="warnings-filter",
    ),
    _ManagerShape(
        package="temp_state_pkg",
        export="hold_state",
        factory_module="temp_state.py",
        factory_source=(
            "from temp_state_pkg.wrapper import resource_manager\n"
            "\n"
            "@resource_manager\n"
            "def hold_state(marker):\n"
            "    # temp-state shape: carry marker across the with body\n"
            "    saved = marker\n"
            "    yield saved\n"
        ),
        consumer_call="hold_state(1)",
        shape="temp-state",
    ),
)


def _write_package(root: Path, files: dict[str, str], package_name: str):
    package = root / package_name
    package.mkdir(exist_ok=True)
    for relative, text in files.items():
        target = package / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    metadata = root / f"{package_name}_dist-1.0.dist-info"
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


def _package_files(shape: _ManagerShape, *, factory_source: str | None = None) -> dict:
    return {
        "__init__.py": f"from {shape.package}.{shape.factory_module[:-3]} import {shape.export}\n",
        shape.factory_module: factory_source or shape.factory_source,
        # Seal with package id so unrelated managers do not share wrapper source_cid.
        "wrapper.py": _resource_wrapper(seal=shape.package),
    }


def _populate(root: Path, *, shape: _ManagerShape, consumer_source: str, files=None):
    dist = _write_package(root, files or _package_files(shape), shape.package)
    consumer = root / "consumer.py"
    consumer.write_text(consumer_source, encoding="utf-8")
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
        root=root,
        path=consumer,
        distribution_index={shape.package: dist},
    )
    return context, tree


def _canonical_consumer(shape: _ManagerShape) -> str:
    return (
        f"from {shape.package} import {shape.export}\n"
        f"with {shape.consumer_call}:\n"
        f"    pass\n"
    )


def _renamed_consumer(shape: _ManagerShape, alias: str) -> str:
    return (
        f"from {shape.package} import {shape.export} as {alias}\n"
        f"with {alias}{shape.consumer_call[len(shape.export):]}:\n"
        f"    pass\n"
    )


# ---------------------------------------------------------------------------
# Name-free publication pipeline (IDENTICAL for every manager seat)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Publication:
    """Testimony extracted without naming the producing manager."""

    receiver: SourceFragmentCoordinateV1
    enter: SourceFragmentCoordinateV1
    exit: SourceFragmentCoordinateV1
    ref: SourceDerivedGeneratorResourceRefV1
    frame_cid: str
    protocol_construction_cid: str
    has_generator_steps: bool
    enter_definition: SourceFragmentCoordinateV1
    exit_definition: SourceFragmentCoordinateV1


def _publications(context: TreeConstructionContextV1) -> list[_Publication]:
    """Collect every generator-backed publication seat — no name dispatch."""
    out: list[_Publication] = []
    for receiver in context.source_manager_provider_calls:
        enter = context.contract_refs.require_native_definition(
            receiver, NativeProtocolSlot.CONTEXT_ENTER
        )
        exit_ = context.contract_refs.require_native_definition(
            receiver, NativeProtocolSlot.CONTEXT_EXIT
        )
        ref = context.source_derived_contract_refs.get(receiver)
        if not isinstance(ref, SourceDerivedGeneratorResourceRefV1):
            continue
        if not isinstance(enter, SourceFragmentCoordinateV1):
            continue
        if not isinstance(exit_, SourceFragmentCoordinateV1):
            continue
        protocol = ref.protocol
        if not isinstance(protocol, GeneratorBackedManagerProtocolV1):
            continue
        frame = protocol.generator_frame
        out.append(
            _Publication(
                receiver=receiver,
                enter=enter,
                exit=exit_,
                ref=ref,
                frame_cid=frame.frame_cid,
                protocol_construction_cid=protocol.protocol_construction_cid,
                has_generator_steps=frame.generator_steps is not None,
                enter_definition=protocol.enter_definition,
                exit_definition=protocol.exit_definition,
            )
        )
    return out


def _assert_full_publication(context: TreeConstructionContextV1, *, residual: str):
    """IDENTICAL pipeline assertions for any seated generator manager.

    Failure names the residual shape, never invents a skip.
    """
    pubs = _publications(context)
    if not pubs:
        seats = list(context.source_manager_provider_calls)
        refs = {
            str(k): type(v).__name__
            for k, v in context.source_derived_contract_refs.items()
        }
        pytest.fail(
            f"NAMED RESIDUAL ({residual}): generator manager did not publish "
            f"SourceDerivedGeneratorResourceRefV1 through the pipeline.\n"
            f"  provider seats: {seats}\n"
            f"  derived refs: {refs}\n"
            f"  expected: enter+exit native defs + GeneratorBackedManagerProtocolV1 "
            f"with generator_steps on the use-site receiver"
        )
    for pub in pubs:
        assert isinstance(pub.ref.semantics, ProtocolResourceSemanticsV1)
        assert pub.has_generator_steps is True
        assert pub.enter != pub.exit
        assert pub.enter_definition == pub.enter
        assert pub.exit_definition == pub.exit
        assert pub.enter.source_cid == pub.exit.source_cid
        assert pub.enter.source_cid.startswith("blake3-512:")
        assert (pub.enter.start_line, pub.enter.start_col) < (
            pub.exit.start_line,
            pub.exit.start_col,
        )
        # Exactly one generator-backed ref per receiver.
        assert (
            sum(
                1
                for site, value in context.source_derived_contract_refs.items()
                if site == pub.receiver
                and isinstance(value, SourceDerivedGeneratorResourceRefV1)
            )
            == 1
        )
    return pubs


def _lifecycle_key(pub: _Publication) -> tuple:
    """Testimony compared across rename — excludes use-site coordinates."""
    return (
        type(pub.ref).__name__,
        type(pub.ref.semantics).__name__,
        type(pub.ref.protocol).__name__,
        pub.has_generator_steps,
        pub.enter.source_cid,
        pub.exit.source_cid,
        pub.enter.start_line,
        pub.enter.start_col,
        pub.exit.start_line,
        pub.exit.start_col,
        pub.frame_cid,
        pub.enter_definition,
        pub.exit_definition,
    )


# ---------------------------------------------------------------------------
# Core laws
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shape", _SHAPES, ids=lambda s: s.shape)
def test_unrelated_generator_manager_publishes_full_pipeline(
    tmp_path: Path, shape: _ManagerShape
):
    """Each unrelated generator publishes enter/exit + generator ref testimony."""
    root = tmp_path / shape.package
    root.mkdir()
    context, _ = _populate(
        root, shape=shape, consumer_source=_canonical_consumer(shape)
    )
    _assert_full_publication(context, residual=shape.shape)


def test_three_unrelated_managers_share_identical_pipeline_shape(tmp_path: Path):
    """All three shapes satisfy the same publication predicates (no name arms)."""
    snapshots = []
    for shape in _SHAPES:
        root = tmp_path / shape.package
        root.mkdir()
        context, _ = _populate(
            root, shape=shape, consumer_source=_canonical_consumer(shape)
        )
        pubs = _assert_full_publication(context, residual=shape.shape)
        # Structural pipeline keys only — not manager names.
        for pub in pubs:
            snapshots.append(
                (
                    type(pub.ref).__name__,
                    type(pub.ref.semantics).__name__,
                    type(pub.ref.protocol).__name__,
                    pub.has_generator_steps,
                    pub.enter != pub.exit,
                    pub.enter_definition == pub.enter,
                    pub.exit_definition == pub.exit,
                )
            )
    assert len(snapshots) >= 3
    # Every manager produced the same structural publication shape.
    assert len(set(snapshots)) == 1, snapshots


def test_renamed_alias_publishes_identical_testimony_modulo_coordinates(
    tmp_path: Path,
):
    """``import export as alias`` keeps lifecycle testimony; only use-site moves."""
    shape = _SHAPES[0]
    alias = "apply_settings"
    can_root = tmp_path / "canonical"
    ren_root = tmp_path / "renamed"
    can_root.mkdir()
    ren_root.mkdir()
    can_ctx, _ = _populate(
        can_root, shape=shape, consumer_source=_canonical_consumer(shape)
    )
    ren_ctx, _ = _populate(
        ren_root,
        shape=shape,
        consumer_source=_renamed_consumer(shape, alias),
    )
    can_pubs = _assert_full_publication(can_ctx, residual=f"{shape.shape}/canonical")
    ren_pubs = _assert_full_publication(ren_ctx, residual=f"{shape.shape}/renamed")
    assert len(can_pubs) == len(ren_pubs) == 1
    can_pub, ren_pub = can_pubs[0], ren_pubs[0]
    assert _lifecycle_key(can_pub) == _lifecycle_key(ren_pub)
    # Use-site receivers differ (alias spelling changes consumer source_cid /
    # span); lifecycle definition coordinates do not.
    assert can_pub.receiver != ren_pub.receiver or (
        can_pub.receiver.source_cid != ren_pub.receiver.source_cid
    )


def test_builtin_open_still_enrolls_nothing(tmp_path: Path):
    """Discrimination: builtin open publishes neither generator ref nor native defs."""
    path = tmp_path / "open_consumer.py"
    path.write_text(
        "def exercise(path):\n"
        "    with open(path) as handle:\n"
        "        return handle\n",
        encoding="utf-8",
    )
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (
            path.read_text(encoding="utf-8"),
            str(path),
            blake3_512_of(path.read_bytes()),
        ),
        construction_context=context,
    )
    populate_source_derived_resource_refs(tree, root=tmp_path, path=path)
    assert context.source_manager_provider_calls == {}
    assert not any(
        isinstance(value, SourceDerivedGeneratorResourceRefV1)
        for value in context.source_derived_contract_refs.values()
    )
    assert _publications(context) == []


@pytest.mark.parametrize("shape", _SHAPES, ids=lambda s: s.shape)
def test_tampered_source_refuses_publication_per_manager(
    tmp_path: Path, shape: _ManagerShape
):
    """Tamper: strip yield so the factory is not a generator — no gen ref."""
    # Honest control: still publishes.
    honest = tmp_path / f"honest_{shape.package}"
    honest.mkdir()
    honest_ctx, _ = _populate(
        honest, shape=shape, consumer_source=_canonical_consumer(shape)
    )
    _assert_full_publication(honest_ctx, residual=f"{shape.shape}/honest-control")

    # Tamper: replace yield with a plain return — no generator suspension.
    tampered_factory = shape.factory_source.replace("yield ", "return ")
    assert "yield " not in tampered_factory
    assert "return " in tampered_factory
    dirty = tmp_path / f"tampered_{shape.package}"
    dirty.mkdir()
    dirty_ctx, _ = _populate(
        dirty,
        shape=shape,
        consumer_source=_canonical_consumer(shape),
        files=_package_files(shape, factory_source=tampered_factory),
    )
    pubs = _publications(dirty_ctx)
    assert pubs == [], (
        f"tampered {shape.shape} still published generator-backed refs: {pubs}"
    )
    # No SourceDerivedGeneratorResourceRefV1 under any seat for this consumer.
    assert not any(
        isinstance(value, SourceDerivedGeneratorResourceRefV1)
        for value in dirty_ctx.source_derived_contract_refs.values()
    )


def test_enter_body_tamper_changes_published_coordinate(tmp_path: Path):
    """Acceptance: mutating enter definition body changes its coordinate."""
    shape = _SHAPES[1]
    base_wrapper = _resource_wrapper(seal=shape.package)
    tampered_wrapper = (
        f"# package seal: {shape.package}\n"
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
    first = tmp_path / "enter_a"
    second = tmp_path / "enter_b"
    first.mkdir()
    second.mkdir()
    first_files = _package_files(shape)
    second_files = dict(first_files)
    second_files["wrapper.py"] = tampered_wrapper
    first_ctx, _ = _populate(
        first, shape=shape, consumer_source=_canonical_consumer(shape)
    )
    second_ctx, _ = _populate(
        second,
        shape=shape,
        consumer_source=_canonical_consumer(shape),
        files=second_files,
    )
    first_pubs = _assert_full_publication(first_ctx, residual=f"{shape.shape}/enter-a")
    second_pubs = _assert_full_publication(
        second_ctx, residual=f"{shape.shape}/enter-b"
    )
    assert first_pubs[0].enter != second_pubs[0].enter
    assert first_pubs[0].enter.start_line != second_pubs[0].enter.start_line


# ---------------------------------------------------------------------------
# Grep-proof: no name dispatch in production publication path or this suite
# ---------------------------------------------------------------------------


def test_publication_path_has_no_manager_name_dispatch():
    """Production derivation must not hard-code any of these manager exports."""
    import sugar_lift_python_source.manager_summary_derivation as derivation
    import sugar_lift_python_source.manager_protocol_construction as protocol

    sources = (
        textwrap.dedent(inspect.getsource(derivation)),
        textwrap.dedent(inspect.getsource(protocol)),
    )
    forbidden = {
        shape.export for shape in _SHAPES
    } | {
        shape.package for shape in _SHAPES
    } | {
        "option_context",
        "pd.option_context",
        "ensure_clean",
        "set_config",
        "filter_warnings",
        "hold_state",
        "catch_warnings",
        "temporary_state",
        "apply_settings",
        "_GeneratorContextManager",
        "contextmanager",
        "contextlib.py",
    }
    for source in sources:
        module = ast.parse(source)
        literals = {
            node.value
            for node in ast.walk(module)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        assert literals.isdisjoint(forbidden), literals & forbidden
        assert "ast.parse" not in source
        assert "ast.walk" not in source


def test_this_suite_has_no_name_dispatch_in_publication_helpers():
    """The pipeline helpers branch on types/seats, never on export strings."""
    source = Path(__file__).read_text(encoding="utf-8")
    module = ast.parse(source)
    # Functions that form the name-free pipeline.
    helper_names = {
        "_publications",
        "_assert_full_publication",
        "_lifecycle_key",
    }
    for node in module.body:
        if not isinstance(node, ast.FunctionDef) or node.name not in helper_names:
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                # Helpers may mention residual format strings, not export names.
                assert child.value not in {s.export for s in _SHAPES}, (
                    f"{node.name} embeds export name {child.value!r}"
                )
                assert child.value not in {s.package for s in _SHAPES}


def test_distinct_managers_publish_distinct_definition_coordinates(tmp_path: Path):
    """Unrelated packages cannot share enter/exit definition or frame identity."""
    pubs_by_shape = []
    for shape in _SHAPES:
        root = tmp_path / shape.package
        root.mkdir()
        context, _ = _populate(
            root, shape=shape, consumer_source=_canonical_consumer(shape)
        )
        pubs = _assert_full_publication(context, residual=shape.shape)
        pubs_by_shape.append((shape.shape, pubs[0]))
    for i, (shape_a, pub_a) in enumerate(pubs_by_shape):
        for shape_b, pub_b in pubs_by_shape[i + 1 :]:
            # Distinct package wrapper seals ⇒ distinct enter/exit source_cid.
            assert pub_a.enter != pub_b.enter, (shape_a, shape_b)
            assert pub_a.exit != pub_b.exit, (shape_a, shape_b)
            assert pub_a.enter.source_cid != pub_b.enter.source_cid, (
                shape_a,
                shape_b,
            )
            # Distinct generator factories ⇒ distinct construction frames.
            assert pub_a.frame_cid != pub_b.frame_cid, (shape_a, shape_b)
