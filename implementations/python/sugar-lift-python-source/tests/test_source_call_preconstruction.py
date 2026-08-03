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
from sugar_lift_py_tests.gap import ConstructionPanic
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.source_call_resolution import (
    SourceCallPreconstructionGapV1,
    SourceCallPreconstructionRefV1,
)
from sugar_lift_python_source.source_call_preconstruction import (
    populate_source_visible_call_frames as _populate_source_visible_call_frames,
)
from sugar_lift_python_source.resolution_session import SourceResolutionSession
from sugar_source_tree.nodes import Call
from sugar_source_tree.panic import BackendDefect, SugarNotWritten
from sugar_source_tree.tree import SourceFile


def populate_source_visible_call_frames(
    *args, distribution_index, session=None, **kwargs
):
    """The fixture distribution index is the population under test."""
    if session is None:
        roster = frozenset(
            distribution.metadata["Name"]
            for distribution in distribution_index.values()
        )
        session = SourceResolutionSession(enrolled_distributions=roster)
    return _populate_source_visible_call_frames(
        *args,
        distribution_index=distribution_index,
        session=session,
        **kwargs,
    )


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


def _distribution_with_nested_module(
    root: Path, implementation: str, nested: str
) -> importlib.metadata.Distribution:
    distribution = _distribution(root, implementation)
    package = root / "unprivileged"
    (package / "nested.py").write_text(nested, encoding="utf-8")
    record = root / "unprivileged_dist-1.0.dist-info" / "RECORD"
    with record.open("a", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerow(("unprivileged/nested.py", "", ""))
    return distribution


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


def test_authenticated_nested_attribute_call_installs_recursive_source_frame(
    tmp_path: Path,
) -> None:
    """An attributed callee with authenticated defining bytes is not dynamic."""
    distribution = _distribution_with_nested_module(
        tmp_path,
        "import unprivileged.nested as nested\n\n"
        "def arbitrary_helper(value=17):\n"
        "    return nested.project(value)\n",
        "def project(value):\n" "    return value\n",
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
    assert isinstance(
        context.source_call_resolutions[coordinate], SourceCallPreconstructionRefV1
    )
    value = call.sugar().desugar().value
    assert isinstance(value, CallSiteValue)
    result = value.force_floor(
        None, owner="authenticated nested attribute call", project_callsite=False
    )
    returned = result.statements[0]
    assert isinstance(returned, ReturnValue)
    assert isinstance(returned.value, CallSiteValue)
    nested_result = returned.value.force_floor(
        None, owner="authenticated attributed callee", project_callsite=False
    )
    assert nested_result.statements == (ReturnValue(TermValue(17)),)


def test_decorator_wrapped_source_call_does_not_borrow_undecorated_body(
    tmp_path: Path,
) -> None:
    distribution = _distribution(
        tmp_path,
        "from functools import wraps as preserve_metadata\n\n"
        "def decorate(original):\n"
        "    @preserve_metadata(original)\n"
        "    def wrapper(value):\n"
        "        return original(value)\n"
        "    return wrapper\n\n"
        "@decorate\n"
        "def arbitrary_helper(value):\n"
        "    return value + 1\n",
    )
    path, source_file, context = _consumer(
        tmp_path,
        "from unprivileged import arbitrary_helper as renamed\n" "renamed(2) + 3\n",
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
    assert row.kind == "decorator-application"
    assert coordinate not in context.source_call_frames


def test_undecorated_twin_still_installs_its_authenticated_return_frame(
    tmp_path: Path,
) -> None:
    distribution = _distribution(
        tmp_path,
        "def arbitrary_helper(value):\n" "    return value + 1\n",
    )
    path, source_file, context = _consumer(
        tmp_path,
        "from unprivileged import arbitrary_helper as renamed\n" "renamed(2) + 3\n",
    )
    call = next(node for node in source_file.nodes() if isinstance(node, Call))

    populate_source_visible_call_frames(
        source_file,
        root=tmp_path,
        path=path,
        distribution_index={"unprivileged": distribution},
    )

    coordinate = _coordinate(call)
    assert isinstance(
        context.source_call_resolutions[coordinate], SourceCallPreconstructionRefV1
    )
    assert coordinate in context.source_call_frames


def test_runtime_receiver_attribute_call_remains_dynamic_and_loud(
    tmp_path: Path,
) -> None:
    """A formal receiver supplies no authenticated identity for its method."""
    distribution = _distribution(
        tmp_path,
        "def arbitrary_helper(receiver, value):\n"
        "    return receiver.project(value)\n",
    )
    path, source_file, context = _consumer(
        tmp_path,
        "from unprivileged import arbitrary_helper as renamed\n"
        "renamed(subject, 17)\n",
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
    assert coordinate in context.source_call_frames
    value = call.sugar().desugar().value
    assert isinstance(value, CallSiteValue)
    outer = value.force_floor(
        None, owner="runtime receiver attribute call", project_callsite=False
    )
    returned = outer.statements[0]
    assert isinstance(returned, ReturnValue)
    assert isinstance(returned.value, CallSiteValue)
    with pytest.raises(ConstructionPanic) as raised:
        returned.value.force_floor(
            None, owner="runtime receiver attribute call", project_callsite=False
        )
    assert "blame=project observed=missing callsite body" in str(raised.value)


def test_frame_exists_does_not_imply_body_semantically_completed(
    tmp_path: Path,
) -> None:
    """Frame installation and body completion are distinct laws.

    Truthful twin (complete return body): authenticated outer installs a ref
    AND force_floor completes the body to a BlockValue return.

    Lying twin (incomplete child floor): the same outer still installs a ref
    and frame — ``len`` is a real builtin call, not an opaque fabricated child
    — but reducing the body stays typed-loud via ConstructionPanic. A frame
    must never be read as evidence the body completed.
    """
    # --- Truthful: frame exists AND body completes ---
    complete_root = tmp_path / "complete"
    complete_root.mkdir()
    complete_dist = _distribution(
        complete_root,
        "def arbitrary_helper(value):\n" "    return value\n",
    )
    complete_path, complete_file, complete_ctx = _consumer(
        complete_root,
        "from unprivileged import arbitrary_helper as renamed\nrenamed(17)\n",
    )
    complete_call = next(
        node for node in complete_file.nodes() if isinstance(node, Call)
    )
    populate_source_visible_call_frames(
        complete_file,
        root=complete_root,
        path=complete_path,
        distribution_index={"unprivileged": complete_dist},
    )
    complete_coord = _coordinate(complete_call)
    complete_row = complete_ctx.source_call_resolutions[complete_coord]
    assert isinstance(complete_row, SourceCallPreconstructionRefV1)
    assert complete_coord in complete_ctx.source_call_frames
    complete_value = complete_call.sugar().desugar().value
    assert isinstance(complete_value, CallSiteValue)
    completed = complete_value.force_floor(
        None, owner="truthful complete body", project_callsite=False
    )
    assert isinstance(completed, BlockValue)
    assert completed.statements == (ReturnValue(TermValue(17)),)

    # --- Lying: frame exists, body does NOT complete ---
    incomplete_root = tmp_path / "incomplete"
    incomplete_root.mkdir()
    incomplete_dist = _distribution(
        incomplete_root,
        "def arbitrary_helper(value):\n" "    return len(value)\n",
    )
    incomplete_path, incomplete_file, incomplete_ctx = _consumer(
        incomplete_root,
        "from unprivileged import arbitrary_helper as renamed\nrenamed(17)\n",
    )
    incomplete_call = next(
        node for node in incomplete_file.nodes() if isinstance(node, Call)
    )
    populate_source_visible_call_frames(
        incomplete_file,
        root=incomplete_root,
        path=incomplete_path,
        distribution_index={"unprivileged": incomplete_dist},
    )
    incomplete_coord = _coordinate(incomplete_call)
    incomplete_row = incomplete_ctx.source_call_resolutions[incomplete_coord]
    # Outer function is source-visible: preconstruction installs a frame.
    assert isinstance(incomplete_row, SourceCallPreconstructionRefV1)
    assert incomplete_coord in incomplete_ctx.source_call_frames
    # Body reduction is incomplete (TermValue has no length floor). Typed-loud
    # ConstructionPanic — never a fabricated opaque-child completion.
    with pytest.raises(ConstructionPanic, match="length|Floor"):
        incomplete_call.sugar().desugar()


def test_absent_child_export_is_loud_without_fabricated_child_result(
    tmp_path: Path,
) -> None:
    """Truly absent child export: outer frame may exist; child stays typed-loud.

    Distinguishes preconstruction frame presence from fabricating a green
    opaque child result for a name with no defining source.
    """
    distribution = _distribution(
        tmp_path,
        "def arbitrary_helper(value):\n" "    return not_a_real_export(value)\n",
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
    assert isinstance(row, SourceCallPreconstructionRefV1)
    assert coordinate in context.source_call_frames
    with pytest.raises(SugarNotWritten, match="call-target-source-absent"):
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


def test_generator_frame_exists_is_not_ordinary_body_completion(
    tmp_path: Path,
) -> None:
    """Generator source is written: frame exists; completion is not BlockValue.

    Truthful twin: a yield body installs a source frame with generator_steps
    and desugars to GeneratorConstructionV1 (allocated suspended machine).

    Lying twin: the same site must not be classified as source-body-gap (the
    body is written) and must not project as an ordinary completed BlockValue
    return — frame existence is not ordinary body semantic completion.
    """
    from sugar_lift_py_tests.generator_construction import GeneratorConstructionV1

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
    # Truthful: frame exists; generator_steps authenticate suspension.
    assert isinstance(row, SourceCallPreconstructionRefV1)
    assert coordinate in context.source_call_frames
    frame = context.source_call_frames[coordinate]
    assert frame.generator_steps is not None
    assert len(frame.generator_steps) >= 1

    outcome = call.sugar().desugar()
    assert isinstance(outcome.value, GeneratorConstructionV1)
    machine = outcome.value
    assert machine.steps  # suspended machine, not ordinary BlockValue return

    # Lying: not source-body-gap (body is written as a generator).
    assert not isinstance(row, SourceCallPreconstructionGapV1)
    # Lying: not ordinary body semantic completion.
    assert not isinstance(outcome.value, BlockValue)
    assert not isinstance(outcome.value, CallSiteValue)


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
