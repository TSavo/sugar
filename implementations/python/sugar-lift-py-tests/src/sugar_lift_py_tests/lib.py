from __future__ import annotations

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory import build_next


def lift_source(
    path: str,
    source: str,
    *,
    memento_file: str | None = None,
) -> object:
    return build_next(
        source=source,
        filename=path,
        role=SugarRole.TERM,
        memento_file=memento_file,
    )
