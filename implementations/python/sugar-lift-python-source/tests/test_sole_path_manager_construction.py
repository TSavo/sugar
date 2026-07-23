from __future__ import annotations

import csv
import importlib.metadata
from pathlib import Path

from sugar_lift_py_tests.floor import BlockValue, ReturnValue, TermValue
from sugar_lift_py_tests.import_binding import authenticated_import_use_receipts
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.dependency_artifact import (
    DependencyArtifactGraph,
    ResolvedPythonObjectV1,
    resolve_import_binding,
)
from sugar_lift_python_source.manager_construction import (
    ConstructedCallActualV1,
    ConstructedManagerBehaviorV1,
    ManagerConstructionGapV1,
    construct_manager_behavior,
)
from sugar_lift_python_source.manager_protocol_construction import (
    ConstructedManagerProtocolV1,
    ManagerProtocolConstructionGapV1,
    construct_manager_protocol,
)
from sugar_source_tree.binding_provenance import ConstructedValueTestimonyV1
from sugar_source_tree.binding_state import BindingEntryV1
from sugar_source_tree.nodes import Call, Constant
from sugar_source_tree.tree import SourceFile


def _distribution(root: Path, source: str) -> importlib.metadata.Distribution:
    package = root / "arbitrary"
    package.mkdir()
    (package / "__init__.py").write_text(
        "from arbitrary.manager import make_guard\n", encoding="utf-8"
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


def _resolved(root: Path, source: str):
    graph = DependencyArtifactGraph.authenticate(_distribution(root, source))
    consumer = "import arbitrary\narbitrary.make_guard(23)\n"
    path = root / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    source_cid = blake3_512_of(consumer.encode())
    receipts, _ = authenticated_import_use_receipts(root, path, consumer, source_cid)
    resolved = resolve_import_binding(receipts[0], graph=graph)
    assert isinstance(resolved, ResolvedPythonObjectV1)
    source_file = SourceFile((consumer, str(path), source_cid))
    call = next(item for item in source_file.nodes() if isinstance(item, Call))
    literal = next(item for item in call.args if isinstance(item, Constant))
    actual = TermValue(23)
    # Testimony uses the canonical term address, never repr spelling.
    from sugar_lift_py_tests.ir import _term_content_cid

    testimony = ConstructedValueTestimonyV1.mint(
        literal.fragment, _term_content_cid(actual.to_term(owner="test"))
    )
    return (
        graph,
        resolved,
        ConstructedCallActualV1(literal, actual, testimony),
        call.fragment,
    )


def test_renamed_factory_constructs_returned_receiver_state_through_one_door(tmp_path):
    graph, resolved, actual, call_site = _resolved(
        tmp_path,
        "class UnprivilegedGuard:\n"
        "    def __init__(self, expected):\n"
        "        self.expected = expected\n\n"
        "def make_guard(expected):\n"
        "    return UnprivilegedGuard(expected)\n",
    )

    result = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )

    assert isinstance(result, ConstructedManagerBehaviorV1)
    fields = {field.name: field.value for field in result.receiver_state.fields}
    assert fields == {"expected": actual.value}
    entry = result.formal_actual_bindings[0]
    assert isinstance(entry, BindingEntryV1)
    assert entry.state is actual.node
    assert entry.coordinate.projection_path == ("formal", 0)
    assert "node" not in repr(entry.wire()).lower()
    assert result.manager_construction_cid.startswith("blake3-512:")


def test_opaque_source_call_stays_typed_loud(tmp_path):
    graph, resolved, actual, call_site = _resolved(
        tmp_path, "def make_guard(expected):\n    return len(expected)\n"
    )

    result = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )

    assert isinstance(result, ManagerConstructionGapV1)
    assert result.kind == "opaque-call-target"


def test_renamed_manager_protocol_retains_ordinary_method_call_frames(tmp_path):
    graph, resolved, actual, call_site = _resolved(
        tmp_path,
        "class ArbitraryGuard:\n"
        "    def __init__(self, marker):\n"
        "        self.marker = marker\n\n"
        "    def __enter__(self):\n"
        "        return self.marker\n\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return self.marker\n\n"
        "def make_guard(marker):\n"
        "    return ArbitraryGuard(marker)\n",
    )
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )
    assert isinstance(behavior, ConstructedManagerBehaviorV1)

    protocol = construct_manager_protocol(behavior, exit_face_id="fixture-face")

    assert isinstance(protocol, ConstructedManagerProtocolV1)
    assert protocol.enter_call.body is not None
    assert protocol.exit_call.body is not None
    assert protocol.enter_frame_cid.startswith("blake3-512:")
    assert protocol.exit_frame_cid.startswith("blake3-512:")
    assert protocol.protocol_construction_cid.startswith("blake3-512:")
    assert protocol.enter_call.formal_coordinate_cids
    enter_block = protocol.enter_call.force_floor(
        None, owner="renamed enter", project_callsite=False
    )
    exit_block = protocol.exit_call.force_floor(
        None, owner="renamed exit", project_callsite=False
    )
    assert isinstance(enter_block, BlockValue)
    assert isinstance(exit_block, BlockValue)
    assert enter_block.statements == (ReturnValue(actual.value),)
    assert exit_block.statements == (ReturnValue(actual.value),)


def test_manager_missing_source_protocol_method_stays_typed_loud(tmp_path):
    graph, resolved, actual, call_site = _resolved(
        tmp_path,
        "class ArbitraryObject:\n"
        "    def __init__(self, marker):\n"
        "        self.marker = marker\n\n"
        "def make_guard(marker):\n"
        "    return ArbitraryObject(marker)\n",
    )
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )
    assert isinstance(behavior, ConstructedManagerBehaviorV1)

    protocol = construct_manager_protocol(behavior, exit_face_id="fixture-face")

    assert isinstance(protocol, ManagerProtocolConstructionGapV1)
    assert protocol.kind == "enter-missing"


def test_renamed_enter_and_exit_halts_remain_method_exitsets(tmp_path):
    graph, resolved, actual, call_site = _resolved(
        tmp_path,
        "class ArbitraryFailingGuard:\n"
        "    def __init__(self, marker):\n"
        "        self.marker = marker\n\n"
        "    def __enter__(self):\n"
        "        raise ValueError('enter')\n\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        raise TypeError('exit')\n\n"
        "def make_guard(marker):\n"
        "    return ArbitraryFailingGuard(marker)\n",
    )
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )
    assert isinstance(behavior, ConstructedManagerBehaviorV1)
    protocol = construct_manager_protocol(behavior, exit_face_id="fixture-face")
    assert isinstance(protocol, ConstructedManagerProtocolV1)

    from sugar_lift_py_tests.outcome import ExitSet, Halted, outcome_to_exitset

    enter = outcome_to_exitset(protocol.enter_outcome())
    exit_ = outcome_to_exitset(protocol.exit_outcome())
    assert isinstance(enter, ExitSet)
    assert isinstance(exit_, ExitSet)
    assert all(isinstance(face, Halted) for face in enter.exits)
    assert all(isinstance(face, Halted) for face in exit_.exits)
