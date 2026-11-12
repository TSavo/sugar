"""A lookup defect inside manager summary derivation propagates.

An ``AttributeError`` (``call.func.id`` on an Attribute callee, seen while
lifting numpy's errstate) once went through the opener's populate catch: the
open "succeeded", the manager's derived resource refs came back empty, and
nothing that reads them refused. The catch is gone (#7795), so this is one case
of the general rule in ``test_function_roster_floor_law``: every populate
failure propagates by its own name.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from test_function_roster_floor_law import _open, _write_three_functions


@pytest.mark.parametrize("defect", [AttributeError("id"), NameError("missing")])
def test_a_lookup_defect_in_populate_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, defect
) -> None:
    path = tmp_path / "target.py"
    _write_three_functions(path)

    def boom(source_file, **_k):
        del source_file
        raise defect

    monkeypatch.setattr(
        "sugar_lift_python_source.manager_summary_derivation."
        "populate_source_derived_resource_refs",
        boom,
    )
    with pytest.raises(type(defect)):
        _open(tmp_path, path)
