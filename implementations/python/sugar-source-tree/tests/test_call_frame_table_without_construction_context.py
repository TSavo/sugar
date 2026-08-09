# SPDX-License-Identifier: MIT OR Apache-2.0
"""A context-less open must not crash on the source-call frame table.

``CallSiteSugar`` carries ``source_call_frame_table`` from the construction
context. The table was guarded on ``lexical_row`` -- a DIFFERENT value -- so a
file opened without a construction context dereferenced ``None`` and raised
``AttributeError: 'NoneType' object has no attribute 'source_call_frames'``.

That is an INSTRUMENT failure, not a terminal: it makes the whole file
unmeasured rather than producing something a reader can judge. It surfaced in
recensus run 30989441520, where 41 of 178 files per shard died this way at
``phase=residual`` on the roll-call path -- reachable only once the seat fix
let files be measured at all.

The correct witness was already three lines above: ``coordinate`` is minted
solely under ``isinstance(context, TreeConstructionContextV1)``, so it is the
existing evidence that a context is present.
"""

from __future__ import annotations

import pathlib
import textwrap

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.tree import SourceFile

# A nested definition called from its enclosing scope: the shape that seats a
# lexical call row, which is what made the table arm reachable.
_NESTED_LEXICAL_CALL = textwrap.dedent(
    """
    def frame_table_probe_outer():
        def frame_table_probe_inner(value):
            return value + 1

        return frame_table_probe_inner(41)
    """
)


def _unique_source(tmp_path: pathlib.Path, marker: str) -> pathlib.Path:
    # Unique source text per test: SourceUnits are memoized by
    # (source_cid, workspace-relative filename), so byte-identical fixtures
    # share ONE unit and distinct tmp_path gives zero isolation (#7364).
    path = tmp_path / f"frame_table_{marker}.py"
    path.write_text(f"# {marker}\n{_NESTED_LEXICAL_CALL}")
    return path


def test_context_less_open_constructs_instead_of_raising_attributeerror(
    tmp_path: pathlib.Path,
) -> None:
    """The planted arm: no construction context, and construction still lands.

    ``SourceFile.from_path`` is the bare door -- it builds a tree with no
    construction context, which is exactly the condition the census hit.
    """
    source = _unique_source(tmp_path, "contextless")
    module = SourceFile.from_path(source, construction_context=TreeConstructionContextV1.for_test_without_workspace()).constructed_module.root

    # The point is that this does not raise AttributeError on a None context.
    for statement in module.body:
        statement.sugar()

# NOTE: an "absent rather than invented" arm belongs here too -- proving the
# construction carries no FABRICATED table. It is not included because walking
# sugar children by attribute name was brittle and a tooth that cannot find its
# own subject is worse than none. The arm above is mutation-proved: reverting
# the guard reproduces the exact production failure
# (AttributeError at nodes.py:11288, recensus run 30989441520).
