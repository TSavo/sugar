"""Installed source-defined contextlib managers publish through the class door."""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.canonicalizer import blake3_512_of
from sugar_lift_py_tests.context_manager_resolution import (
    NativeProtocolSlot,
    SourceDerivedContextManagerRefV1,
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_python_source.manager_summary_derivation import (
    populate_source_derived_resource_refs,
)
from sugar_source_tree.tree import SourceFile


@pytest.mark.parametrize("call", ("renamed_suppress(ValueError)", "RenamedStack()"))
def test_installed_renamed_contextlib_class_manager_publishes_native_definitions(
    tmp_path: Path, call: str
):
    source = (
        "from contextlib import suppress as renamed_suppress\n"
        "from contextlib import ExitStack as RenamedStack\n"
        "def consume():\n"
        f"    with {call}:\n"
        "        pass\n"
    )
    path = tmp_path / "consumer.py"
    path.write_text(source, encoding="utf-8")
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (source, str(path), blake3_512_of(source.encode("utf-8"))),
        construction_context=context,
    )

    populate_source_derived_resource_refs(tree, root=tmp_path, path=path)

    assert len(context.source_derived_contract_refs) == 1
    receiver, ref = next(iter(context.source_derived_contract_refs.items()))
    assert isinstance(ref, SourceDerivedContextManagerRefV1), type(ref)
    enter = context.contract_refs.require_native_definition(
        receiver, NativeProtocolSlot.CONTEXT_ENTER
    )
    exit_ = context.contract_refs.require_native_definition(
        receiver, NativeProtocolSlot.CONTEXT_EXIT
    )
    assert isinstance(enter, SourceFragmentCoordinateV1)
    assert isinstance(exit_, SourceFragmentCoordinateV1)
    assert enter != exit_
