"""Open must not discard a successful SourceFile function roster.

_json.py has ~49 real functions. Populate walking dependency CM derivation
must not abort the open with BackendDefect and bank zero functions — that is
a false refusal that made 708/1284 corpus rows look empty.

#7063 already cites SugarNotWritten body gaps. Session module-materialize
memo (#7064) shares one SourceFile across definitions; re-seating the same
import-value span on that unit must be a no-op, not a BackendDefect that
throws away the open.
"""

from __future__ import annotations

from importlib import metadata
from pathlib import Path

import pytest


def test_pandas_json_open_keeps_function_roster() -> None:
    from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction

    pandas_distribution = metadata.distribution("pandas")
    install_root = Path(pandas_distribution.locate_file("")).resolve()
    path = install_root / "pandas" / "io" / "json" / "_json.py"
    if not path.is_file():
        pytest.skip(f"pandas _json.py not installed at {path}")

    # Must not raise. Pre-fix: BackendDefect seat_import_value_use_resolution
    # aborted open after ~9s and callers saw zero functions.
    source_file = open_source_file_for_construction(
        path,
        root=install_root,
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
        populate_derived=True,
    )
    functions = tuple(source_file.functions())
    assert len(functions) >= 40, (
        f"_json.py has dozens of real functions; open banked {len(functions)}. "
        f"names={[fn.name for fn in functions[:15]]}"
    )
