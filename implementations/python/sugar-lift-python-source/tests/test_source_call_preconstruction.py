from __future__ import annotations

import csv
from dataclasses import replace
import importlib.metadata
from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.floor import BlockValue, CallSiteValue, ReturnValue, TermValue
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.source_call_resolution import (
    SourceCallPreconstructionGapV1,
    SourceCallPreconstructionRefV1,
)
from sugar_lift_python_source.source_call_preconstruction import (
    populate_source_visible_call_frames,
)
from sugar_source_tree.nodes import Call
from sugar_source_tree.panic import BackendDefect, SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _distribution(root: Path, implementation: str) -> importlib.metadata.Distribution:
    package = root / "unprivileged"
    package.mkdir()
    (package / "__init__.py").write_text(
        "from unprivileged.helpers import arbitrary_helper\n", encoding="utf-8"
    )
    (package / "helpers.py").write_text(implementation, encoding="utf-8")
    metadata = root / "unprivileged_dist-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: unprivileged-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    files = (
        "unprivileged/__init__.py",
        "unprivileged/helpers.py",
        "unprivileged_dist-1.0.dist-info/METADATA",
        "unprivileged_dist-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for file in files:
            writer.writerow((file, "", ""))
    return importlib.metadata.Distribution.at(metadata)


def _coordinate(call: Call) -> SourceFragmentCoordinateV1:
    span = call.line_col_span()
    return SourceFragmentCoordinateV1(
        call.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )


def _consumer(root: Path, source: str):
    path = root / "consumer.py"
    path.write_text(source, encoding="utf-8")
    context = TreeConstructionContextV1.for_source_call_construction(
        workspace_root=str(root)
    )
    source_file = SourceFile(
        (source, str(path), blake3_512_of(source.encode("utf-8"))),
        construction_context=context,
    )
    return path, source_file, context


def test_renamed_cross_file_call_installs_source_frame_and_constructs_return(
    tmp_path: Path,
) -> None:
    distribution = _distribution(
        tmp_path,
        "def inner(value):\n"
        "    return value\n\n"
        "def arbitrary_helper(value=17):\n"
        "    return inner(value)\n",
    )
    path, source_file, context = _consumer(
        tmp_path,
        "from unprivileged import arbitrary_helper as renamed\n" "renamed()\n",
    )
    call = next(node for node in source_file.nodes() if isinstance(node, Call))

    populate_source_visible_call_frames(
        source_file,
        root=tmp_path,
        path=path,
        distribution_index={"unprivileged": distribution},
    )

    coordinate = _coordinate(call)
    row = context.source_call_resolutions[coordinate]
    assert isinstance(row, SourceCallPreconstructionRefV1)
    assert row.resolved_object_cid.startswith("blake3-512:")
    assert row.source_call_frame_cid == context.source_call_frames[coordinate].frame_cid
    outcome = call.sugar().desugar()
    assert isinstance(outcome.value, CallSiteValue)
    assert outcome.value.body is not None
    constructed = outcome.value.force_floor(
        None, owner="renamed cross-file call", project_callsite=False
    )
    assert isinstance(constructed, BlockValue)
    assert len(constructed.statements) == 1
    nested = constructed.statements[0]
    assert isinstance(nested, ReturnValue)
    assert isinstance(nested.value, CallSiteValue)
    nested_result = nested.value.force_floor(
        None, owner="renamed recursive source call", project_callsite=False
    )
    assert isinstance(nested_result, BlockValue)
    assert nested_result.statements == (ReturnValue(TermValue(17)),)


def test_repeated_calls_reuse_one_authenticated_distribution_lookup(
    tmp_path: Path, monkeypatch
) -> None:
    distribution = _distribution(
        tmp_path,
        "def arbitrary_helper(value=17):\n    return value\n",
    )
    path, source_file, _context = _consumer(
        tmp_path,
        "from unprivileged import arbitrary_helper\n"
        "arbitrary_helper()\n"
        "arbitrary_helper()\n",
    )
    lookups = 0
    import sugar_lift_py_tests.import_binding as import_binding

    lexical_passes = 0
    original_import_uses = import_binding.authenticated_import_uses

    def counted_import_uses(*args, **kwargs):
        nonlocal lexical_passes
        lexical_passes += 1
        return original_import_uses(*args, **kwargs)

    monkeypatch.setattr(
        import_binding, "authenticated_import_uses", counted_import_uses
    )

    monkeypatch.setattr(
        importlib.metadata,
        "packages_distributions",
        lambda: {"unprivileged": ("unprivileged-dist",)},
    )

    def selected_distribution(name: str):
        nonlocal lookups
        lookups += 1
        assert name == "unprivileged-dist"
        return distribution

    monkeypatch.setattr(importlib.metadata, "distribution", selected_distribution)

    populate_source_visible_call_frames(source_file, root=tmp_path, path=path)

    assert lookups == 1
    # One mint pass plus one independent final-check pass for the whole batch.
    assert lexical_passes == 2


def test_distinct_callees_in_one_module_share_one_constructed_frame_graph(
    tmp_path: Path, monkeypatch
) -> None:
    import sugar_lift_python_source.manager_construction as manager_construction

    distribution = _distribution(
        tmp_path,
        "def first(value=1):\n    return value\n\n"
        "def second(value=2):\n    return value\n",
    )
    path, source_file, _context = _consumer(
        tmp_path,
        "from unprivileged.helpers import first, second\nfirst()\nsecond()\n",
    )
    original = manager_construction.SourceFile
    constructions = 0

    def counted_source_file(*args, **kwargs):
        nonlocal constructions
        constructions += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(manager_construction, "SourceFile", counted_source_file)

    populate_source_visible_call_frames(
        source_file,
        root=tmp_path,
        path=path,
        distribution_index={"unprivileged": distribution},
        artifact_graph_cache={},
        source_frame_cache={},
    )

    assert constructions == 1


def test_unselected_definition_gap_does_not_expand_into_selected_callee(
    tmp_path: Path,
) -> None:
    distribution = _distribution(
        tmp_path,
        "def first(value=1):\n    return value\n\n"
        "class Unselected:\n"
        "    def noisy(self):\n"
        "        try:\n"
        "            return 1\n"
        "        except Exception:\n"
        "            return 2\n",
    )
    path, source_file, context = _consumer(
        tmp_path,
        "from unprivileged.helpers import first\nfirst()\n",
    )

    populate_source_visible_call_frames(
        source_file,
        root=tmp_path,
        path=path,
        distribution_index={"unprivileged": distribution},
        artifact_graph_cache={},
        source_frame_cache={},
    )

    assert len(context.source_call_resolutions) == 1
    assert isinstance(
        next(iter(context.source_call_resolutions.values())),
        SourceCallPreconstructionRefV1,
    )


def test_selected_definition_expansion_bound_stays_typed_loud(
    tmp_path: Path, monkeypatch
) -> None:
    import sugar_lift_python_source.manager_construction as manager_construction

    distribution = _distribution(
        tmp_path,
        "class ArbitraryLarge:\n"
        "    def first(self):\n        return 1\n"
        "    def second(self):\n        return 2\n",
    )
    path, source_file, context = _consumer(
        tmp_path,
        "from unprivileged.helpers import ArbitraryLarge\nArbitraryLarge()\n",
    )
    monkeypatch.setattr(manager_construction, "_SOURCE_DEFINITION_NODE_LIMIT", 4)

    populate_source_visible_call_frames(
        source_file,
        root=tmp_path,
        path=path,
        distribution_index={"unprivileged": distribution},
        artifact_graph_cache={},
        source_frame_cache={},
    )

    row = next(iter(context.source_call_resolutions.values()))
    assert isinstance(row, SourceCallPreconstructionGapV1)
    assert row.kind == "expansion-bound"


def test_source_callee_with_unresolved_manager_stays_typed_loud(
    tmp_path: Path,
) -> None:
    distribution = _distribution(
        tmp_path,
        "def arbitrary_helper(manager):\n"
        "    with manager:\n"
        "        return 1\n",
    )
    path, source_file, context = _consumer(
        tmp_path,
        "from unprivileged import arbitrary_helper\n"
        "arbitrary_helper(object())\n",
    )

    populate_source_visible_call_frames(
        source_file,
        root=tmp_path,
        path=path,
        distribution_index={"unprivileged": distribution},
        artifact_graph_cache={},
        source_frame_cache={},
    )

    row = next(iter(context.source_call_resolutions.values()))
    assert isinstance(row, SourceCallPreconstructionGapV1)
    assert row.kind == "source-body-gap"


def test_source_visible_function_with_opaque_child_stays_typed_loud(
    tmp_path: Path,
) -> None:
    distribution = _distribution(
        tmp_path,
        "def arbitrary_helper(value):\n" "    return len(value)\n",
    )
    path, source_file, context = _consumer(
        tmp_path,
        "from unprivileged import arbitrary_helper as renamed\n" "renamed(17)\n",
    )
    call = next(node for node in source_file.nodes() if isinstance(node, Call))

    populate_source_visible_call_frames(
        source_file,
        root=tmp_path,
        path=path,
        distribution_index={"unprivileged": distribution},
    )

    coordinate = _coordinate(call)
    row = context.source_call_resolutions[coordinate]
    assert isinstance(row, SourceCallPreconstructionGapV1)
    assert row.kind == "opaque-call-target"
    assert coordinate not in context.source_call_frames
    with pytest.raises(SugarNotWritten, match="opaque-call-target"):
        call.sugar().desugar()


def test_stale_source_frame_cid_is_a_backend_defect(tmp_path: Path) -> None:
    distribution = _distribution(
        tmp_path, "def arbitrary_helper(value):\n    return value\n"
    )
    path, source_file, context = _consumer(
        tmp_path,
        "from unprivileged import arbitrary_helper as renamed\nrenamed(17)\n",
    )
    call = next(node for node in source_file.nodes() if isinstance(node, Call))
    populate_source_visible_call_frames(
        source_file,
        root=tmp_path,
        path=path,
        distribution_index={"unprivileged": distribution},
    )
    coordinate = _coordinate(call)
    context.source_call_resolutions[coordinate] = replace(
        context.source_call_resolutions[coordinate],
        source_call_frame_cid="blake3-512:" + ("00" * 64),
        resolution_cid="",
    )

    with pytest.raises(BackendDefect, match="ref/frame mismatch"):
        call.sugar()


def test_invalid_source_call_signature_is_typed_loud(tmp_path: Path) -> None:
    distribution = _distribution(
        tmp_path, "def arbitrary_helper(required):\n    return required\n"
    )
    path, source_file, context = _consumer(
        tmp_path,
        "from unprivileged import arbitrary_helper as renamed\nrenamed()\n",
    )
    call = next(node for node in source_file.nodes() if isinstance(node, Call))
    populate_source_visible_call_frames(
        source_file,
        root=tmp_path,
        path=path,
        distribution_index={"unprivileged": distribution},
    )
    coordinate = _coordinate(call)

    row = context.source_call_resolutions[coordinate]
    assert isinstance(row, SourceCallPreconstructionGapV1)
    assert row.kind == "call-binding"
    assert coordinate not in context.source_call_frames
    with pytest.raises(SugarNotWritten, match="call-binding"):
        call.sugar().desugar()


def test_unwritten_source_body_is_a_typed_call_gap(tmp_path: Path) -> None:
    distribution = _distribution(
        tmp_path,
        "def arbitrary_helper(value):\n" "    yield value\n",
    )
    path, source_file, context = _consumer(
        tmp_path,
        "from unprivileged import arbitrary_helper as renamed\nrenamed(17)\n",
    )
    call = next(node for node in source_file.nodes() if isinstance(node, Call))
    populate_source_visible_call_frames(
        source_file,
        root=tmp_path,
        path=path,
        distribution_index={"unprivileged": distribution},
    )
    coordinate = _coordinate(call)

    row = context.source_call_resolutions[coordinate]
    assert isinstance(row, SourceCallPreconstructionGapV1)
    assert row.kind == "source-body-gap"
    assert coordinate not in context.source_call_frames
    with pytest.raises(SugarNotWritten, match="source-body-gap"):
        call.sugar().desugar()


def test_distribution_without_authenticated_manifest_stays_typed_loud(
    tmp_path: Path,
) -> None:
    distribution = _distribution(
        tmp_path, "def arbitrary_helper(value):\n    return value\n"
    )
    (tmp_path / "unprivileged_dist-1.0.dist-info" / "RECORD").unlink()
    path, source_file, context = _consumer(
        tmp_path,
        "from unprivileged import arbitrary_helper as renamed\nrenamed(17)\n",
    )
    call = next(node for node in source_file.nodes() if isinstance(node, Call))
    populate_source_visible_call_frames(
        source_file,
        root=tmp_path,
        path=path,
        distribution_index={"unprivileged": distribution},
    )
    coordinate = _coordinate(call)

    row = context.source_call_resolutions[coordinate]
    assert isinstance(row, SourceCallPreconstructionGapV1)
    assert row.kind == "artifact-resolution"
    assert coordinate not in context.source_call_frames
    with pytest.raises(SugarNotWritten, match="artifact-resolution"):
        call.sugar().desugar()


def test_cross_file_frame_preserves_real_variadic_actuals(tmp_path: Path) -> None:
    from sugar_lift_py_tests.floor import DictValue, StringValue, TupleValue

    distribution = _distribution(
        tmp_path,
        "def arbitrary_helper(first, *rest, **options):\n" "    return rest\n",
    )
    path, source_file, context = _consumer(
        tmp_path,
        "import unprivileged\n" "unprivileged.arbitrary_helper(1, 2, 3, label=4)\n",
    )
    call = next(node for node in source_file.nodes() if isinstance(node, Call))

    populate_source_visible_call_frames(
        source_file,
        root=tmp_path,
        path=path,
        distribution_index={"unprivileged": distribution},
    )

    value = call.sugar().desugar().value
    assert isinstance(value, CallSiteValue)
    assert value.arg_values[0] == TermValue(1)
    assert isinstance(value.arg_values[1], TupleValue)
    assert value.arg_values[1].elements == (TermValue(2), TermValue(3))
    assert isinstance(value.arg_values[2], DictValue)
    assert value.arg_values[2].entries == ((StringValue("label"), TermValue(4)),)


def test_renamed_source_class_constructor_and_method_use_authenticated_frames(
    tmp_path: Path,
) -> None:
    distribution = _distribution(
        tmp_path,
        "class arbitrary_helper:\n"
        "    def __init__(self, seed=11):\n"
        "        self.seed = seed\n\n"
        "    def project(self, value=17, *rest, **options):\n"
        "        return value\n",
    )
    path, source_file, context = _consumer(
        tmp_path,
        "from unprivileged import arbitrary_helper as Renamed\n"
        "Renamed(13).project(value=23, label=29)\n",
    )
    calls = tuple(node for node in source_file.nodes() if isinstance(node, Call))
    constructor = next(call for call in calls if not hasattr(call.func, "attr"))
    method = next(
        call for call in calls if getattr(call.func, "attr", None) == "project"
    )

    populate_source_visible_call_frames(
        source_file,
        root=tmp_path,
        path=path,
        distribution_index={"unprivileged": distribution},
    )

    constructor_row = context.source_call_resolutions[_coordinate(constructor)]
    method_row = context.source_call_resolutions[_coordinate(method)]
    assert isinstance(constructor_row, SourceCallPreconstructionRefV1)
    assert isinstance(method_row, SourceCallPreconstructionRefV1)
    assert method_row.resolved_object_cid == constructor_row.resolved_object_cid
    method_value = method.sugar().desugar().value
    assert isinstance(method_value, CallSiteValue)
    method_result = method_value.force_floor(
        None, owner="renamed authenticated method", project_callsite=False
    )
    assert method_result.statements == (ReturnValue(TermValue(23)),)


def test_authenticated_class_missing_method_stays_typed_loud(tmp_path: Path) -> None:
    distribution = _distribution(
        tmp_path,
        "class arbitrary_helper:\n" "    def __init__(self):\n" "        pass\n",
    )
    path, source_file, context = _consumer(
        tmp_path,
        "from unprivileged import arbitrary_helper as Renamed\n"
        "Renamed().missing(23)\n",
    )
    method = next(
        node
        for node in source_file.nodes()
        if isinstance(node, Call) and getattr(node.func, "attr", None) == "missing"
    )

    populate_source_visible_call_frames(
        source_file,
        root=tmp_path,
        path=path,
        distribution_index={"unprivileged": distribution},
    )

    row = context.source_call_resolutions[_coordinate(method)]
    assert isinstance(row, SourceCallPreconstructionGapV1)
    assert row.kind == "dynamic-call-target"
    assert _coordinate(method) not in context.source_call_frames
    with pytest.raises(SugarNotWritten, match="dynamic-call-target"):
        method.sugar().desugar()


def test_assigned_constructed_receiver_uses_its_authenticated_method_frame(
    tmp_path: Path,
) -> None:
    distribution = _distribution(
        tmp_path,
        "class arbitrary_helper:\n"
        "    def __init__(self, seed):\n"
        "        self.seed = seed\n\n"
        "    def project(self, value=17, **options):\n"
        "        return value\n",
    )
    path, source_file, _context = _consumer(
        tmp_path,
        "from unprivileged import arbitrary_helper as Renamed\n"
        "def consume():\n"
        "    receiver = Renamed(13)\n"
        "    return receiver.project(label=29)\n",
    )
    populate_source_visible_call_frames(
        source_file,
        root=tmp_path,
        path=path,
        distribution_index={"unprivileged": distribution},
    )
    function = next(source_file.functions()).substitute({})
    method = next(
        node
        for node in function.walk()
        if isinstance(node, Call) and getattr(node.func, "attr", None) == "project"
    )

    method_value = method.sugar().desugar().value
    assert isinstance(method_value, CallSiteValue)
    result = method_value.force_floor(
        None, owner="assigned authenticated receiver", project_callsite=False
    )
    assert result.statements == (ReturnValue(TermValue(17)),)


def test_authenticated_constructor_method_follows_local_mro(tmp_path: Path) -> None:
    distribution = _distribution(
        tmp_path,
        "class Ancestor:\n"
        "    def project(self, value=31):\n"
        "        return value\n\n"
        "class arbitrary_helper(Ancestor):\n"
        "    def __init__(self):\n"
        "        pass\n",
    )
    path, source_file, context = _consumer(
        tmp_path,
        "from unprivileged import arbitrary_helper as Renamed\n"
        "Renamed().project()\n",
    )
    method = next(
        node
        for node in source_file.nodes()
        if isinstance(node, Call) and getattr(node.func, "attr", None) == "project"
    )

    populate_source_visible_call_frames(
        source_file,
        root=tmp_path,
        path=path,
        distribution_index={"unprivileged": distribution},
    )

    row = context.source_call_resolutions[_coordinate(method)]
    assert isinstance(row, SourceCallPreconstructionRefV1)
    result = (
        method.sugar()
        .desugar()
        .value.force_floor(
            None, owner="authenticated inherited method", project_callsite=False
        )
    )
    assert result.statements == (ReturnValue(TermValue(31)),)
