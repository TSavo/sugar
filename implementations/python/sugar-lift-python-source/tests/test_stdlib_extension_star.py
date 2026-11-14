"""A manager from a module no imported proof answers is cited by its import target."""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.context_manager_resolution import (
    OpaqueCitedContextManagerRefV1,
)

from test_contextlib_suppress_source_exit_faces import _corpus, _open


def test_decimal_localcontext_is_cited_by_its_import_target(tmp_path: Path) -> None:
    # No dependency source is read to decide what ``decimal.localcontext`` is
    # (step 3): the manager is not bridged and is cited naming its import
    # target.
    source = (
        "import decimal\n"
        "def f():\n"
        "    with decimal.localcontext() as ctx:\n"
        "        pass\n"
    )
    source_file = _open(_corpus(tmp_path, source))
    refs = source_file.root.unit.construction_context.source_derived_contract_refs
    (reference,) = refs.values()
    assert isinstance(reference, OpaqueCitedContextManagerRefV1)
    assert reference.roster.resolution_kind == "call-target-off-population"
    assert reference.roster.target_name == "python:decimal.localcontext"
