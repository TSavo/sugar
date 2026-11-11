"""The import value-use door answers the same cold and warm (#7678).

The door used to read only the dependency tops seated so far.  A cold open
of pandas ``tests/scalar/timestamp/methods/test_replace.py`` had no ``os``
seat, so ``os.environ.get`` inside ``pandas._testing.set_timezone`` stayed a
bare receipt and the ``with`` constructed; the same file lifted after
``tests/io/json/test_compression.py`` in one walk found ``os`` seated and was
refused.  The door now authenticates the top the receipt names, so what ran
before is not an input.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Attribute, FunctionDef
from sugar_source_tree.tree import SourceFile


def _seat(root: Path, source: str, *, warm_tops: tuple[str, ...]):
    """Seat ``selected``'s value-use receipts under a session with ``warm_tops``
    already seated (the state an earlier file of the same walk leaves)."""
    from sugar_lift_py_tests.import_binding import (
        authenticated_import_value_use_receipts,
    )
    from sugar_lift_python_source.dependency_artifact import (
        AuthenticatedModuleSourceV1,
        authenticate_dependency_top_level,
    )
    from sugar_lift_python_source.manager_construction import (
        _seat_import_value_use_receipts,
    )
    from sugar_lift_python_source.resolution_session import SourceResolutionSession

    path = root / "consumer.py"
    path.write_text(source, encoding="utf-8")
    context = TreeConstructionContextV1.for_source_call_construction(
        workspace_root=str(root)
    )
    source_file = SourceFile(
        (source, str(path), blake3_512_of(source.encode("utf-8"))),
        construction_context=context,
    )
    authenticated_import_value_use_receipts(
        root, path, source, source_file.unit.source_cid, module_identities={}
    )
    session = SourceResolutionSession(enrolled_distributions=frozenset())
    for top in warm_tops:
        session.dependency_graphs[top] = authenticate_dependency_top_level(top)
    function = next(
        node for node in source_file.nodes() if isinstance(node, FunctionDef)
    )
    _seat_import_value_use_receipts(
        source_file=source_file,
        module=AuthenticatedModuleSourceV1(
            module_name="consumer",
            source_seat="consumer.py",
            source_cid=source_file.unit.source_cid,
            source=source,
        ),
        target=function,
        session=session,
        context=context,
        # What the frame carried in: the session's seats at its entry.
        dependency_graphs=dict(session.dependency_graphs),
    )
    return source_file, session


def test_unresolvable_stdlib_value_use_refuses_cold_as_it_does_warm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Truthful: ``os.environ.get`` is the same named gap with or without a
    prior ``os`` seat.  Before #7678 the cold seating seated the bare receipt
    and raised nothing."""
    from sugar_source_tree.panic import ImportValueUseResolutionGap

    monkeypatch.chdir(tmp_path)
    source = 'import os\ndef selected():\n    return os.environ.get("TZ")\n'
    observed = []
    for warm_tops in ((), ("os",)):
        with pytest.raises(ImportValueUseResolutionGap) as raised:
            _seat(tmp_path, source, warm_tops=warm_tops)
        observed.append(raised.value.observed)
    assert observed[0] == observed[1]
    assert "target-outside-binding" in observed[0]
    assert "'python:os.environ.get'" in observed[0]


def test_top_no_artifact_authenticates_stays_a_bare_receipt_cold_and_warm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lying: authenticating on ask must not mint authority for a top that
    has no artifact.  The use stays the bare receipt (its consumer stays
    typed-loud), no seat is invented, and nothing is raised at seating."""
    from sugar_lift_py_tests.import_binding import AuthenticatedImportUseV1

    monkeypatch.chdir(tmp_path)
    top = "sugar_no_artifact_top_7678"
    source = f"import {top}\ndef selected():\n    return {top}.value\n"
    source_file, session = _seat(tmp_path, source, warm_tops=())
    attribute = next(
        node for node in source_file.nodes() if isinstance(node, Attribute)
    )
    span = attribute.line_col_span()
    seated = source_file.unit.import_value_use_resolution(
        (span.start_line, span.start_col, span.end_line, span.end_col)
    )
    assert type(seated) is AuthenticatedImportUseV1
    assert seated.target_symbol == f"python:{top}.value"
    assert top not in session.dependency_graphs
