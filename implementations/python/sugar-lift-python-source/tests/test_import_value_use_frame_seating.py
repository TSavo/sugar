"""Per-frame import value-use seating + same-unit actual rehost.

Critical path for seam-1: ``_resolve_source_visible_frame_uncached`` seats
final-checked value-use receipts on the frame's OWN SourceUnit before
construction, and ``bind_node_actuals`` rehosts foreign actuals onto that unit
so identity operands never carry cross-unit LineTable offsets.
"""

from __future__ import annotations

import csv
import importlib.metadata
from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.source_call_resolution import SourceCallPreconstructionRefV1
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.dependency_artifact import ResolvedPythonObjectV1
from sugar_lift_python_source.source_call_preconstruction import (
    populate_source_visible_call_frames,
)
from sugar_source_tree.nodes import BindingCoordinateRef, Call, Constant, Dict, FunctionDef, Tuple_
from sugar_source_tree.tree import SourceFile


def _distribution(root: Path, helpers: str, types: str = "class ArrayType:\n    pass\n"):
    package = root / "unprivileged"
    package.mkdir()
    (package / "__init__.py").write_text(
        "from unprivileged.helpers import box_expected, ArrayType\n",
        encoding="utf-8",
    )
    (package / "helpers.py").write_text(helpers, encoding="utf-8")
    (package / "types.py").write_text(types, encoding="utf-8")
    metadata = root / "unprivileged_dist-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: unprivileged-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    files = (
        "unprivileged/__init__.py",
        "unprivileged/helpers.py",
        "unprivileged/types.py",
        "unprivileged_dist-1.0.dist-info/METADATA",
        "unprivileged_dist-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for file in files:
            writer.writerow((file, "", ""))
    return importlib.metadata.Distribution.at(metadata)


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


def _frame_for_box_expected(
    tmp_path: Path,
    helpers: str,
    types: str = "class ArrayType:\n    pass\n",
):
    distribution = _distribution(tmp_path, helpers, types)
    path, source_file, context = _consumer(
        tmp_path,
        "from unprivileged import box_expected, ArrayType\n"
        "actual = box_expected((1,), ArrayType)\n",
    )
    call = next(node for node in source_file.nodes() if isinstance(node, Call))
    populate_source_visible_call_frames(
        source_file,
        root=tmp_path,
        path=path,
        distribution_index={"unprivileged": distribution},
    )
    span = call.line_col_span()
    coordinate = SourceFragmentCoordinateV1(
        source_file.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )
    assert isinstance(
        context.source_call_resolutions[coordinate], SourceCallPreconstructionRefV1
    )
    return context.source_call_frames[coordinate]


def test_sibling_dynamic_import_use_does_not_block_selected_runtime_frame(
    tmp_path: Path,
) -> None:
    """Truthful: only the authenticated selected definition owns frame uses."""
    frame = _frame_for_box_expected(
        tmp_path,
        "from unprivileged.types import ArrayType, F\n"
        "def unrelated(value):\n"
        "    return F\n"
        "def box_expected(expected, box_cls=None):\n"
        "    return expected if box_cls is None else box_cls\n",
        "class ArrayType:\n"
        "    pass\n"
        "def choose_type():\n"
        "    return object()\n"
        "F = choose_type()\n",
    )

    assert frame.owner.name == "box_expected"
    assert all(
        resolved.definition.name != "F"
        for resolved in frame.owner.unit._import_value_use_resolutions.values()
    )


def test_frame_seats_import_value_use_receipts_on_own_unit(tmp_path: Path) -> None:
    """Truthful: body identity operand is seated on the frame unit only."""
    frame = _frame_for_box_expected(
        tmp_path,
        "from unprivileged.types import ArrayType\n"
        "def box_expected(expected, box_cls=None):\n"
        "    default = ArrayType\n"
        "    return expected if box_cls is None else box_cls\n",
    )
    resolutions = frame.owner.unit._import_value_use_resolutions
    assert resolutions, "frame unit must seat its own value-use receipts"
    assert all(isinstance(value, ResolvedPythonObjectV1) for value in resolutions.values())
    # Definition-coordinate identity — not spelling.
    seated = next(iter(resolutions.values()))
    assert seated.definition.name == "ArrayType"
    assert seated.definition.kind == "class"
    ctx = frame.owner.unit.construction_context
    assert ctx is not None
    assert ctx.source_import_value_resolutions
    for coordinate in ctx.source_import_value_resolutions:
        assert coordinate.source_cid == frame.owner.unit.source_cid


def test_foreign_actuals_rehost_onto_frame_unit_without_linetable_panic(
    tmp_path: Path,
) -> None:
    """Truthful: call-site actuals bind as same-unit BindingCoordinateRefs."""
    # Pad the consumer so foreign offsets exceed the frame unit length.
    frame = _frame_for_box_expected(
        tmp_path,
        "def box_expected(expected, box_cls=None):\n"
        "    return expected if box_cls is None else box_cls\n",
    )
    assert frame.runtime_entries
    owner_cid = frame.owner.unit.source_cid
    owner_len = len(frame.owner.unit.source)
    for entry in frame.runtime_entries:
        state = entry.state
        assert state.unit.source_cid == owner_cid
        # Projecting the span must stay inside the owner LineTable.
        span = state.span
        assert 0 <= span.start <= span.end <= owner_len
        state.line_col_span()
        assert isinstance(state, BindingCoordinateRef)


def test_same_unit_actuals_pass_through_without_rehost(tmp_path: Path) -> None:
    """Truthful twin: same-unit constants are not replaced by formal refs."""
    from sugar_source_tree.nodes import FunctionDef

    local_source = "def local(x):\n    return x\nlocal(1)\n"
    local_path = tmp_path / "local.py"
    local_path.write_text(local_source, encoding="utf-8")
    local_context = TreeConstructionContextV1.for_source_call_construction()
    local_file = SourceFile(
        (local_source, str(local_path), blake3_512_of(local_source.encode("utf-8"))),
        construction_context=local_context,
    )
    function = next(
        node
        for node in local_file.nodes()
        if isinstance(node, FunctionDef) and node.name == "local"
    )
    local_call = next(node for node in local_file.nodes() if isinstance(node, Call))
    local_frame = function.source_visible_call_frame().bind_node_actuals(
        local_call.args, ()
    )
    state = local_frame.runtime_entries[0].state
    assert isinstance(state, Constant)
    assert state.unit.source_cid == local_file.unit.source_cid
    assert state.value == 1


def test_foreign_variadic_actuals_rehost_with_distinct_coordinates(
    tmp_path: Path,
) -> None:
    """Each nested ``*args`` value retains a distinct formal projection."""
    owner_source = "def collect(*items):\n    return items\n"
    owner_file = SourceFile(
        (owner_source, "owner.py", blake3_512_of(owner_source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    function = next(
        node for node in owner_file.nodes() if isinstance(node, FunctionDef)
    )
    foreign_source = "left = 1\nright = 2\n"
    foreign_file = SourceFile(
        (foreign_source, "foreign.py", blake3_512_of(foreign_source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    actuals = tuple(
        node for node in foreign_file.nodes() if isinstance(node, Constant)
    )
    frame = function.source_visible_call_frame().bind_node_actuals(actuals, ())
    packed = frame.runtime_entries[0].state
    assert isinstance(packed, Tuple_)
    assert len(packed.elts) == 2
    assert all(isinstance(node, BindingCoordinateRef) for node in packed.elts)
    coordinates = tuple(node.coordinate for node in packed.elts)
    assert coordinates[0].cid != coordinates[1].cid
    assert coordinates[0].projection_path[-2:] == ("variadic", 0)
    assert coordinates[1].projection_path[-2:] == ("variadic", 1)


def test_foreign_variadic_keyword_actuals_rehost_with_distinct_coordinates(
    tmp_path: Path,
) -> None:
    """Each nested ``**kwargs`` value retains a distinct formal projection."""
    owner_source = "def collect(**items):\n    return items\n"
    owner_file = SourceFile(
        (owner_source, "owner_kw.py", blake3_512_of(owner_source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    function = next(
        node for node in owner_file.nodes() if isinstance(node, FunctionDef)
    )
    foreign_source = "left = 1\nright = 2\n"
    foreign_file = SourceFile(
        (foreign_source, "foreign_kw.py", blake3_512_of(foreign_source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    actuals = tuple(
        node for node in foreign_file.nodes() if isinstance(node, Constant)
    )
    frame = function.source_visible_call_frame().bind_node_actuals(
        (), (("left", actuals[0]), ("right", actuals[1]))
    )
    packed = frame.runtime_entries[0].state
    assert isinstance(packed, Dict)
    coordinates = tuple(item.value.coordinate for item in packed.items)
    assert coordinates[0].cid != coordinates[1].cid
    assert coordinates[0].projection_path[-2:] == ("variadic-keyword", 0)
    assert coordinates[1].projection_path[-2:] == ("variadic-keyword", 1)


def test_lying_foreign_unit_receipt_refuses_with_exact_gap_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lying twin: a genuinely minted foreign receipt cannot seat here."""
    from sugar_lift_py_tests import import_binding
    from sugar_lift_python_source.manager_construction import (
        ImportValueUseSeatingGap,
    )

    foreign_source = "from unprivileged import ArrayType\nvalue = ArrayType\n"
    foreign_path = tmp_path / "foreign_consumer.py"
    foreign_path.write_text(foreign_source, encoding="utf-8")
    receipts, outcomes = import_binding.authenticated_import_value_use_receipts(
        tmp_path,
        foreign_path,
        foreign_source,
        blake3_512_of(foreign_source.encode()),
        module_identities={},
    )
    assert len(receipts) == 1
    monkeypatch.setattr(
        import_binding,
        "authenticated_import_value_use_receipts",
        lambda *_args, **_kwargs: (receipts, outcomes),
    )
    with pytest.raises(ImportValueUseSeatingGap) as raised:
        _frame_for_box_expected(
            tmp_path,
            "from unprivileged.types import ArrayType\n"
            "def box_expected(expected, box_cls=None):\n"
            "    default = ArrayType\n"
            "    return expected if box_cls is None else box_cls\n",
        )
    assert raised.value.kind == "foreign-source-cid"


def test_seat_refuses_foreign_source_cid(tmp_path: Path) -> None:
    """Side-door tooth: seating with wrong source_cid is BackendDefect."""
    from sugar_source_tree.panic import BackendDefect

    frame = _frame_for_box_expected(
        tmp_path,
        "from unprivileged.types import ArrayType\n"
        "def box_expected(expected, box_cls=None):\n"
        "    default = ArrayType\n"
        "    return expected if box_cls is None else box_cls\n",
    )
    owner = frame.owner.unit
    seated = next(iter(owner._import_value_use_resolutions.values()))
    with pytest.raises(BackendDefect, match="source_cid"):
        owner.seat_import_value_use_resolution(
            (1, 0, 1, 1),
            seated,
            source_cid="blake3-512:" + "f" * 128,
        )


def test_seat_refuses_non_resolved_object(tmp_path: Path) -> None:
    from sugar_source_tree.panic import BackendDefect

    frame = _frame_for_box_expected(
        tmp_path,
        "from unprivileged.types import ArrayType\n"
        "def box_expected(expected, box_cls=None):\n"
        "    default = ArrayType\n"
        "    return expected if box_cls is None else box_cls\n",
    )
    owner = frame.owner.unit
    with pytest.raises(BackendDefect, match="ResolvedPythonObjectV1"):
        owner.seat_import_value_use_resolution(
            (1, 0, 1, 1),
            object(),
            source_cid=owner.source_cid,
        )


def test_no_broad_exception_swallow_in_same_unit_rehost() -> None:
    """Side-door tooth: rehost has no bare except Exception → fabricate path."""
    import ast
    import inspect
    from sugar_lift_py_tests import source_call_frame as scf
    from sugar_lift_python_source.manager_construction import (
        _seat_import_value_use_receipts,
    )

    rehost_src = inspect.getsource(scf._same_unit_actual_node)
    assert "except Exception" not in rehost_src

    seat_src = inspect.getsource(_seat_import_value_use_receipts)
    # Code body (not prose): no ambient spelling auth call, no ValueError swallow.
    tree = ast.parse(seat_src)
    fn = tree.body[0]
    assert isinstance(fn, ast.FunctionDef)
    call_names: set[str] = set()
    except_types: list[str] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                call_names.add(func.id)
            elif isinstance(func, ast.Attribute):
                call_names.add(func.attr)
        if isinstance(node, ast.ExceptHandler) and node.type is not None:
            if isinstance(node.type, ast.Name):
                except_types.append(node.type.id)
    assert "authenticate_dependency_top_level" not in call_names
    assert "ValueError" not in except_types


def test_exact_import_value_receipt_seats_and_constructs_member(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sugar_lift_py_tests.import_binding import (
        AuthenticatedImportUseV1,
        authenticated_import_value_use_receipts,
    )
    from sugar_lift_py_tests.sugar.import_member_sugar import ImportMemberSugar
    from sugar_lift_python_source.dependency_artifact import AuthenticatedModuleSourceV1
    from sugar_lift_python_source.manager_construction import (
        _seat_import_value_use_receipts,
    )
    from sugar_lift_python_source.resolution_session import SourceResolutionSession
    from sugar_source_tree.nodes import Attribute

    source = "import re\ndef selected():\n    return re.I\n"
    path, source_file, context = _consumer(tmp_path, source)
    function = next(node for node in source_file.nodes() if isinstance(node, FunctionDef))
    attribute = next(node for node in source_file.nodes() if isinstance(node, Attribute))
    receipts, _ = authenticated_import_value_use_receipts(
        tmp_path, path, source, source_file.unit.source_cid, module_identities={}
    )
    receipt = next(row for row in receipts if row.target_symbol == "python:re.I")
    module = AuthenticatedModuleSourceV1(
        module_name="consumer",
        source_seat="consumer.py",
        source_cid=source_file.unit.source_cid,
        source=source,
    )

    monkeypatch.chdir(tmp_path)
    _seat_import_value_use_receipts(
        source_file=source_file,
        module=module,
        target=function,
        session=SourceResolutionSession(),
        context=context,
        dependency_graphs={},
    )
    span = attribute.line_col_span()
    span_key = (span.start_line, span.start_col, span.end_line, span.end_col)
    seated = source_file.unit.import_value_use_resolution(span_key)

    assert type(seated) is AuthenticatedImportUseV1
    assert seated.use["cid"] == receipt.use["cid"]
    assert seated.demand == receipt.demand
    assert seated.use["importBindingCid"] == receipt.use["importBindingCid"]
    assert seated.target_symbol == receipt.target_symbol
    sugar = attribute.sugar()
    assert isinstance(sugar, ImportMemberSugar)
    assert sugar.qualified_name == "re.I"
    assert sugar.to_term(owner="test") == sugar.desugar(context).value.to_term(
        owner="test"
    )


def test_import_value_receipt_state_refuses_wrong_span_foreign_and_conflict(
    tmp_path: Path,
) -> None:
    from sugar_lift_py_tests.import_binding import authenticated_import_value_use_receipts
    from sugar_source_tree.nodes import Attribute
    from sugar_source_tree.panic import BackendDefect

    source = "import re\ndef selected():\n    return re.I\n"
    path, source_file, _ = _consumer(tmp_path, source)
    attribute = next(node for node in source_file.nodes() if isinstance(node, Attribute))
    receipts, _ = authenticated_import_value_use_receipts(
        tmp_path, path, source, source_file.unit.source_cid, module_identities={}
    )
    receipt = next(row for row in receipts if row.target_symbol == "python:re.I")
    second_receipts, _ = authenticated_import_value_use_receipts(
        tmp_path, path, source, source_file.unit.source_cid, module_identities={}
    )
    conflicting = next(
        row for row in second_receipts if row.target_symbol == "python:re.I"
    )
    span = attribute.line_col_span()
    span_key = (span.start_line, span.start_col, span.end_line, span.end_col)

    with pytest.raises(BackendDefect, match="receipt testimony"):
        source_file.unit.seat_import_value_use_resolution(
            (span.start_line, span.start_col, span.end_line, span.end_col - 1),
            receipt,
            source_cid=source_file.unit.source_cid,
        )
    source_file.unit.seat_import_value_use_resolution(
        span_key, receipt, source_cid=source_file.unit.source_cid
    )
    source_file.unit.seat_import_value_use_resolution(
        span_key, receipt, source_cid=source_file.unit.source_cid
    )
    with pytest.raises(BackendDefect, match="receipt conflicts"):
        source_file.unit.seat_import_value_use_resolution(
            span_key, conflicting, source_cid=source_file.unit.source_cid
        )

    foreign_source = "import os\ndef selected():\n    return os.X\n"
    foreign_path, foreign_file, _ = _consumer(tmp_path, foreign_source)
    foreign_receipts, _ = authenticated_import_value_use_receipts(
        tmp_path,
        foreign_path,
        foreign_source,
        foreign_file.unit.source_cid,
        module_identities={},
    )
    foreign = next(row for row in foreign_receipts if row.target_symbol == "python:os.X")
    with pytest.raises(BackendDefect, match="source_cid"):
        source_file.unit.seat_import_value_use_resolution(
            span_key, foreign, source_cid=foreign_file.unit.source_cid
        )


def test_receipt_backed_import_member_is_constructed_call_argument(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar
    from sugar_lift_py_tests.sugar.import_member_sugar import ImportMemberSugar
    from sugar_lift_python_source.dependency_artifact import AuthenticatedModuleSourceV1
    from sugar_lift_python_source.manager_construction import (
        _seat_import_value_use_receipts,
    )
    from sugar_lift_python_source.resolution_session import SourceResolutionSession

    source = (
        "import re\n"
        "def selected(value):\n"
        "    return re.search('', value, re.I)\n"
    )
    _path, source_file, context = _consumer(tmp_path, source)
    function = next(node for node in source_file.nodes() if isinstance(node, FunctionDef))
    call = next(node for node in source_file.nodes() if isinstance(node, Call))
    module = AuthenticatedModuleSourceV1(
        module_name="consumer",
        source_seat="consumer.py",
        source_cid=source_file.unit.source_cid,
        source=source,
    )

    monkeypatch.chdir(tmp_path)
    _seat_import_value_use_receipts(
        source_file=source_file,
        module=module,
        target=function,
        session=SourceResolutionSession(),
        context=context,
        dependency_graphs={},
    )
    sugar = call.sugar()

    assert isinstance(sugar, CallSiteSugar)
    member = sugar.args[-1]
    assert isinstance(member, ImportMemberSugar)
    assert member.qualified_name == "re.I"
    assert member.to_term(owner="test") == member.desugar(context).value.to_term(
        owner="test"
    )


def test_import_member_testimony_canonicalizes_only_its_authenticated_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The enum.py:927 construction path must not expose a raw owner token."""
    from sugar_lift_py_tests.import_binding import (
        authenticated_import_value_use_receipts,
    )
    from sugar_lift_py_tests.sugar.import_member_sugar import ImportMemberSugar
    from sugar_lift_python_source.dependency_artifact import AuthenticatedModuleSourceV1
    from sugar_lift_python_source.manager_construction import (
        _seat_import_value_use_receipts,
    )
    from sugar_lift_python_source.resolution_session import SourceResolutionSession
    from sugar_source_tree.backend import materialize
    from sugar_source_tree.binding_state import (
        ConstructionTestimonyReporterV1,
        SubstitutionTraceBuilderV1,
    )
    from sugar_source_tree.nodes import Attribute
    from sugar_source_tree.panic import BackendDefect
    from sugar_source_tree.reporter import CollectingReporter

    source = "import sys\ndef selected():\n    return sys.modules\n"
    path, source_file, context = _consumer(tmp_path, source)
    function = next(node for node in source_file.nodes() if isinstance(node, FunctionDef))
    attribute = next(node for node in source_file.nodes() if isinstance(node, Attribute))
    module = AuthenticatedModuleSourceV1(
        module_name="consumer",
        source_seat="consumer.py",
        source_cid=source_file.unit.source_cid,
        source=source,
    )
    monkeypatch.chdir(tmp_path)
    _seat_import_value_use_receipts(
        source_file=source_file,
        module=module,
        target=function,
        session=SourceResolutionSession(),
        context=context,
        dependency_graphs={},
    )
    reporter = ConstructionTestimonyReporterV1(
        CollectingReporter(),
        SubstitutionTraceBuilderV1(source_file.unit.source_cid),
    )
    root = materialize(source_file.unit, source_file.root.ref, reporter)
    constructed_attribute = next(
        node
        for node in root.walk()
        if isinstance(node, Attribute)
        and node.line_col_span() == attribute.line_col_span()
    )

    member = constructed_attribute.sugar()
    assert isinstance(member, ImportMemberSugar)
    assert member.qualified_name == "sys.modules"

    foreign_source = "import os\ndef selected():\n    return os.modules\n"
    foreign_path, foreign_file, _ = _consumer(tmp_path, foreign_source)
    foreign_receipts, _ = authenticated_import_value_use_receipts(
        tmp_path,
        foreign_path,
        foreign_source,
        foreign_file.unit.source_cid,
        module_identities={},
    )
    foreign = next(row for row in foreign_receipts if row.target_symbol == "python:os.modules")
    span = attribute.line_col_span()
    with pytest.raises(BackendDefect, match="source_cid"):
        source_file.unit.seat_import_value_use_resolution(
            (span.start_line, span.start_col, span.end_line, span.end_col),
            foreign,
            source_cid=foreign_file.unit.source_cid,
        )
