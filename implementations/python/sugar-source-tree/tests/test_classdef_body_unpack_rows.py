"""An unpacking assignment in a class body is a row of the namespace.

#9089 deleted the substitution-time display pairing: ``a, b = p, q`` is the
reduce-time unpack whatever its right-hand side (``Assign.
_dynamic_unpack_target``), and keys none of its names by value
(``target_evaluations`` is empty).  The class body read an assignment's rows
off ``target_evaluations`` alone, so a display unpack in a class body was
refused as ``class field dt1 whose statement carries no evaluation key`` and
the pandas 3.0.3 board file ``tests/indexes/datetimes/test_date_range.py``
(``TestGenRangeGeneration``, line 1026: ``dt1, dt2 = "2017-01-01",
"2017-01-01"``) became a construction panic.

The unpack's sugar binds each name under its projection of the statement's
evaluation (``written_keys``), as in a function or module body: those are
the rows.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from sugar_lift_py_tests.floor import ConstructedClassFieldV1
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.sugar.class_definition_sugar import ClassDefinitionSugar
from sugar_source_tree.nodes import ClassDef


def _class(src: str, name: str) -> ClassDef:
    """The class ``name`` of ``src``, opened as production opens a file
    (``open_source_file_for_construction`` under a workspace root)."""
    root = Path(tempfile.mkdtemp(prefix="class-body-unpack-"))
    path = root / f"{name.lower()}.py"
    path.write_text(src, encoding="utf-8")
    source = open_source_file_for_construction(path, root=root)
    return next(
        node
        for node in source.nodes()
        if isinstance(node, ClassDef) and node.name == name
    )


DISPLAY_UNPACK = (
    "class TestGenRangeGeneration:\n"
    '    dt1, dt2 = "2017-01-01", "2017-01-01"\n'
    "\n"
    "    def test_mismatch(self):\n"
    "        return self.dt1\n"
)


def test_a_class_body_display_unpack_is_a_row_per_name() -> None:
    sugar = _class(DISPLAY_UNPACK, "TestGenRangeGeneration").sugar()
    assert isinstance(sugar, ClassDefinitionSugar)
    rows = {
        field.name: field
        for field in sugar.fields
        if isinstance(field, ConstructedClassFieldV1)
    }
    assert {"dt1", "dt2"} <= set(rows), rows
    # Each row reads the key the unpack binds its name under.
    assert all(rows[name].evaluation_key for name in ("dt1", "dt2")), rows
