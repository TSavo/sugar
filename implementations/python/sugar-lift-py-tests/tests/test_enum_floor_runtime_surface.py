"""Surface tooth for the shared process-floor scanner helpers.

Entrance note (#7365): ``scripts/`` is NOT a subpackage of
``sugar_lift_py_tests``. It is a sibling directory of ``src/`` under the
package root, and ``_enum_floor_runtime.production_roots`` names the two as
*separate* roots. The former import here, ``from sugar_lift_py_tests.scripts
import _enum_floor_runtime``, therefore named an entrance that never existed:
the module is tracked, but not reachable by that path. A ModuleNotFoundError
at module scope aborts collection for the WHOLE package, so this one wrong
reference converted the default suite invocation into a run of nothing.

Load it the way ``test_supervised_enum_supervisor.py`` does — by file location
out of the real ``scripts/`` directory, which is the same door the floors open
when invoked as ``scripts/*.py``.
"""

from __future__ import annotations

import importlib.util
import sys

from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root

_SCRIPTS = sugar_lift_py_tests_package_root() / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
_MODULE_PATH = _SCRIPTS / "_enum_floor_runtime.py"
_SPEC = importlib.util.spec_from_file_location("_enum_floor_runtime", _MODULE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(
        "cannot load the process-floor scanner runtime from its only entrance: "
        f"{_MODULE_PATH}. scripts/ is a sibling of src/, never a "
        "sugar_lift_py_tests subpackage (#7365)."
    )
_enum_floor_runtime = importlib.util.module_from_spec(_SPEC)
sys.modules["_enum_floor_runtime"] = _enum_floor_runtime
_SPEC.loader.exec_module(_enum_floor_runtime)


def test_process_floor_runtime_module_is_the_tracked_scripts_file() -> None:
    """The entrance must resolve to the tracked file, not a same-named stray.

    Absence and lookup-failure do not share a representation here: a missing
    scripts/ raises RepoRootUnresolved or ImportError at import time, and a
    module loaded from anywhere else fails this assertion by name.
    """
    expected = sugar_lift_py_tests_package_root() / "scripts" / "_enum_floor_runtime.py"
    assert expected.is_file(), (
        f"the tracked process-floor runtime is absent from its only entrance: "
        f"{expected}. scripts/ is a sibling of src/, never a "
        f"sugar_lift_py_tests subpackage (#7365)."
    )
    assert _enum_floor_runtime.__file__ == str(expected), (
        f"process-floor runtime loaded from {_enum_floor_runtime.__file__!r}, "
        f"expected the tracked package-root scripts file {str(expected)!r}"
    )


def test_process_floor_runtime_exports_required_cli_helpers() -> None:
    """Partition tests must not pass while the scanner module loses its API."""
    for name in ("add_demand_table_arg", "require_demand_table", "apply_lpt_file_shard"):
        assert callable(getattr(_enum_floor_runtime, name, None)), name
