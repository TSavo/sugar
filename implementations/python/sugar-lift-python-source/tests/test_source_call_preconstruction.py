from __future__ import annotations

import csv
import importlib.metadata
from pathlib import Path

from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.floor import BlockValue, CallSiteValue, ReturnValue, TermValue
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.source_call_preconstruction import (
    SourceCallPreconstructionGapV1,
    SourceCallPreconstructionRefV1,
    populate_source_visible_call_frames,
)
from sugar_source_tree.nodes import Call
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
        "from unprivileged import arbitrary_helper as renamed\n"
        "renamed()\n",
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
    assert constructed.statements == (ReturnValue(TermValue(17)),)


def test_source_visible_function_with_opaque_child_stays_typed_loud(
    tmp_path: Path,
) -> None:
    distribution = _distribution(
        tmp_path,
        "def arbitrary_helper(value):\n"
        "    return len(value)\n",
    )
    path, source_file, context = _consumer(
        tmp_path,
        "from unprivileged import arbitrary_helper as renamed\n"
        "renamed(17)\n",
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
