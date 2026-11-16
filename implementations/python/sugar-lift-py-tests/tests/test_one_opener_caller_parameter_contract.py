"""One way to open a file (#7757 inventory item 5).

The caller-parameter contract used to open its files with a bare
``SourceFile.from_path``: an absolute seat, no construction context -- a
different unit from the one the board reads. Its one file reader (the scan
for native-operation carrier operators) is deleted with the carrier; the
bare doors stay gone.
"""

from __future__ import annotations

from sugar_lift_py_tests import caller_parameter_contract, lift_rpc


def test_the_bare_doors_are_gone() -> None:
    """The extra entry points are deleted, not left beside the opener."""
    from sugar_source_tree.tree import SourceFile, SourceTree

    assert not hasattr(SourceFile, "from_module")
    assert not hasattr(SourceFile, "from_path")
    assert not hasattr(SourceTree, "files")
    assert not hasattr(lift_rpc, "_open_enumerated_file")
    assert not hasattr(lift_rpc, "_source_file_at_seat")
    assert not hasattr(lift_rpc, "_source_file_at_own_seat")
    assert not hasattr(
        caller_parameter_contract, "_typed_minted_native_operator_constants"
    )
