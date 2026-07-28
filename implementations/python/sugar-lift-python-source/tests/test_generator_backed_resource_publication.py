"""Closed generator-backed resource contract publication.

Authenticated generator frame + native enter/exit definitions produce ONE
typed ``SourceDerivedGeneratorResourceRefV1`` carrying generator lifecycle
testimony. Coordinates alone cannot construct the ref; a non-generator frame
cannot acquire generator semantics. No ObjectValue fabrication.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.context_manager_contract import (
    ProtocolResourceSemanticsV1,
    ReturnTruthinessDispositionV1,
)
from sugar_lift_py_tests.context_manager_resolution import (
    NativeProtocolSlot,
    SourceDerivedGeneratorResourceRefV1,
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.manager_protocol_construction import (
    GeneratorBackedManagerProtocolV1,
    ManagerProtocolConstructionGapV1,
    construct_generator_backed_protocol,
)
from sugar_lift_python_source.manager_summary_derivation import (
    populate_source_derived_resource_refs,
)
from sugar_source_tree.tree import SourceFile


def test_option_context_publishes_one_generator_backed_resource_ref():
    """Positive: option_context installs ONE generator-backed resource ref."""
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
    ref = context.source_derived_contract_refs.get(receiver)
    assert isinstance(ref, SourceDerivedGeneratorResourceRefV1), type(ref)
    assert isinstance(ref.semantics, ProtocolResourceSemanticsV1)
    assert isinstance(ref.semantics.exit.disposition, ReturnTruthinessDispositionV1)
    protocol = ref.protocol
    assert isinstance(protocol, GeneratorBackedManagerProtocolV1)
    assert protocol.generator_frame.generator_steps is not None
    assert protocol.enter_definition != protocol.exit_definition
    # Native enter/exit definitions enrolled beside the ref.
    enter = context.contract_refs.require_native_definition(
        receiver, NativeProtocolSlot.CONTEXT_ENTER
    )
    exit_ = context.contract_refs.require_native_definition(
        receiver, NativeProtocolSlot.CONTEXT_EXIT
    )
    assert enter == protocol.enter_definition
    assert exit_ == protocol.exit_definition
    # Exactly one ref per use-site receiver.
    assert (
        sum(
            1
            for site, value in context.source_derived_contract_refs.items()
            if site == receiver
            and isinstance(value, SourceDerivedGeneratorResourceRefV1)
        )
        == 1
    )


def test_removing_generator_frame_refuses_protocol_construction():
    """Discrimination: no generator_steps → refuse generator-backed protocol."""
    enter = SourceFragmentCoordinateV1("blake3-512:" + "a" * 128, 1, 0, 2, 0)
    exit_ = SourceFragmentCoordinateV1("blake3-512:" + "a" * 128, 3, 0, 4, 0)

    class _NonGeneratorFrame:
        frame_cid = "blake3-512:" + "b" * 128
        generator_steps = None

    result = construct_generator_backed_protocol(
        frame=_NonGeneratorFrame(),
        enter_definition=enter,
        exit_definition=exit_,
        exit_face_id="face",
        construction_cid="blake3-512:" + "c" * 128,
    )
    assert isinstance(result, ManagerProtocolConstructionGapV1)
    assert result.kind == "generator-missing"


def test_coordinates_alone_cannot_construct_protocol():
    """Discrimination: enter/exit coords without a generator frame refuse."""
    enter = SourceFragmentCoordinateV1("blake3-512:" + "a" * 128, 1, 0, 2, 0)
    exit_ = SourceFragmentCoordinateV1("blake3-512:" + "a" * 128, 3, 0, 4, 0)
    result = construct_generator_backed_protocol(
        frame=None,
        enter_definition=enter,
        exit_definition=exit_,
        exit_face_id="face",
        construction_cid="blake3-512:" + "c" * 128,
    )
    assert isinstance(result, ManagerProtocolConstructionGapV1)
    assert result.kind == "generator-missing"


def test_lying_non_generator_frame_cannot_acquire_generator_semantics():
    """Discrimination: empty-steps frame cannot mint generator protocol."""
    enter = SourceFragmentCoordinateV1("blake3-512:" + "a" * 128, 1, 0, 2, 0)
    exit_ = SourceFragmentCoordinateV1("blake3-512:" + "a" * 128, 3, 0, 4, 0)

    class _LyingFrame:
        frame_cid = "blake3-512:" + "d" * 128
        generator_steps = None  # claims a frame, denies suspension

    result = construct_generator_backed_protocol(
        frame=_LyingFrame(),
        enter_definition=enter,
        exit_definition=exit_,
        exit_face_id="face",
        construction_cid="blake3-512:" + "e" * 128,
    )
    assert isinstance(result, ManagerProtocolConstructionGapV1)
    assert result.kind == "generator-missing"


def test_changing_generator_frame_changes_protocol_identity():
    """Acceptance: distinct generator frames mint distinct protocol CIDs."""
    enter = SourceFragmentCoordinateV1("blake3-512:" + "a" * 128, 1, 0, 2, 0)
    exit_ = SourceFragmentCoordinateV1("blake3-512:" + "a" * 128, 3, 0, 4, 0)

    class _GenFrame:
        def __init__(self, cid: str):
            self.frame_cid = cid
            self.generator_steps = (object(),)

    first = construct_generator_backed_protocol(
        frame=_GenFrame("blake3-512:" + "1" * 128),
        enter_definition=enter,
        exit_definition=exit_,
        exit_face_id="face",
        construction_cid="blake3-512:" + "c" * 128,
    )
    second = construct_generator_backed_protocol(
        frame=_GenFrame("blake3-512:" + "2" * 128),
        enter_definition=enter,
        exit_definition=exit_,
        exit_face_id="face",
        construction_cid="blake3-512:" + "c" * 128,
    )
    assert isinstance(first, GeneratorBackedManagerProtocolV1)
    assert isinstance(second, GeneratorBackedManagerProtocolV1)
    assert first.protocol_construction_cid != second.protocol_construction_cid


def test_identical_enter_exit_coordinates_refuse():
    """Discrimination: enter and exit definitions must differ."""
    same = SourceFragmentCoordinateV1("blake3-512:" + "a" * 128, 1, 0, 2, 0)

    class _GenFrame:
        frame_cid = "blake3-512:" + "f" * 128
        generator_steps = (object(),)

    result = construct_generator_backed_protocol(
        frame=_GenFrame(),
        enter_definition=same,
        exit_definition=same,
        exit_face_id="face",
        construction_cid="blake3-512:" + "c" * 128,
    )
    assert isinstance(result, ManagerProtocolConstructionGapV1)
    assert result.kind == "generator-protocol"


def test_open_still_publishes_neither_generator_ref_nor_native_defs(tmp_path: Path):
    """Discrimination: builtin open produces no generator resource ref."""
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
    assert not any(
        isinstance(value, SourceDerivedGeneratorResourceRefV1)
        for value in context.source_derived_contract_refs.values()
    )


def test_generator_backed_ref_refuses_non_generator_protocol_in_constructor():
    """SourceDerivedGeneratorResourceRefV1 constructor is closed."""
    from sugar_lift_py_tests.context_manager_contract import (
        EnterResultContractV1,
        ExitContractV1,
        ImportSignatureV2,
    )
    from sugar_lift_py_tests.ir import PrimitiveSort

    use_site = SourceFragmentCoordinateV1("blake3-512:" + "a" * 128, 1, 0, 1, 1)
    semantics = ProtocolResourceSemanticsV1(
        EnterResultContractV1(PrimitiveSort("Value")),
        ExitContractV1(ReturnTruthinessDispositionV1()),
    )
    try:
        SourceDerivedGeneratorResourceRefV1(
            use_site,
            "blake3-512:" + "b" * 128,
            semantics,
            ImportSignatureV2(()),
            protocol=object(),
        )
        raised = False
    except ValueError:
        raised = True
    assert raised
