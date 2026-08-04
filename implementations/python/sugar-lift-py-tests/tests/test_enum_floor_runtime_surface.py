"""Surface tooth for the shared process-floor scanner helpers."""

from __future__ import annotations

from sugar_lift_py_tests.scripts import _enum_floor_runtime


def test_process_floor_runtime_exports_required_cli_helpers() -> None:
    """Partition tests must not pass while the scanner module loses its API."""
    for name in ("add_demand_table_arg", "require_demand_table", "apply_lpt_file_shard"):
        assert callable(getattr(_enum_floor_runtime, name, None)), name
