"""A lookup defect inside manager summary derivation propagates.

``populate_source_derived_resource_refs`` runs under the open's roster-floor
catch, which banks any other populate failure as a named residual.  An
``AttributeError`` (``call.func.id`` on an Attribute callee, seen while
lifting numpy's errstate) went through that catch too: the open "succeeded",
the manager's derived resource refs came back empty, and nothing that reads
them refused.  A missing attribute or name in the lifter's own code is a
defect, not a residual, so it propagates by its own name.  Other populate
failures still keep the banked roster (test_function_roster_floor_law).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from test_function_roster_floor_law import _open, _write_three_functions


@pytest.mark.parametrize("defect", [AttributeError("id"), NameError("missing")])
def test_a_lookup_defect_in_populate_is_not_a_residual(
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
