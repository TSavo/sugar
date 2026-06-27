from __future__ import annotations

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory import FactoryBuildResult, build_next


def lift_source(path: str, source: str) -> FactoryBuildResult:
    return build_next(source, filename=path, role=SugarRole.TERM)
