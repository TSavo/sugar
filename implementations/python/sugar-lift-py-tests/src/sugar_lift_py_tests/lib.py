from __future__ import annotations

from sugar_lift_py_tests.array_map_lifter import ArrayMapLift, lift_array_map_assertions
from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory import FactoryBuildResult, build_next


def lift_source(
    path: str,
    source: str,
    *,
    memento_file: str | None = None,
) -> ArrayMapLift | FactoryBuildResult:
    array_map = lift_array_map_assertions(
        source=source,
        filename=path,
        memento_file=memento_file,
    )
    if array_map is not None:
        return array_map
    return build_next(source, filename=path, role=SugarRole.TERM)
