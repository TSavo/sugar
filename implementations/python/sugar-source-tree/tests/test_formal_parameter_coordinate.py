from __future__ import annotations

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile


def _function(source: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(source)
        path = f.name
    return next(SourceFile(path_source(path)).functions())


def test_two_parameter_reads_share_one_authenticated_coordinate() -> None:
    function = _function("def consume(xs):\n return xs[0] + xs[1]\n")
    substituted = function.substitute({})
    refs = [node for node in substituted.walk() if node.kind == "FormalRef"]

    assert len(refs) == 2
    assert refs[0].coordinate is refs[1].coordinate
    assert refs[0].coordinate.coordinate_cid == refs[1].coordinate.coordinate_cid
    assert refs[0].coordinate.ordinal == 0
    assert refs[0].coordinate.declared_name == "xs"
    assert refs[0].coordinate.owner_source_identity_cid == function.unit.source_cid


def test_reassignment_replaces_formal_coordinate_for_later_reads() -> None:
    function = _function("def consume(xs):\n first = xs\n xs = 3\n return xs\n")
    substituted = function.substitute({})
    refs = [node for node in substituted.walk() if node.kind == "FormalRef"]
    returns = [node for node in substituted.walk() if node.kind == "Return"]

    assert len(refs) == 1
    assert returns[0].value.kind == "Constant"
    assert returns[0].value.value == 3


def test_owner_or_ordinal_changes_formal_coordinate_identity() -> None:
    left = _function("def consume(x, y):\n return x\n").substitute({})
    right = _function("def consume(x, y):\n return y\n").substitute({})
    left_ref = next(node for node in left.walk() if node.kind == "FormalRef")
    right_ref = next(node for node in right.walk() if node.kind == "FormalRef")

    assert left_ref.coordinate.ordinal == 0
    assert right_ref.coordinate.ordinal == 1
    assert left_ref.coordinate.coordinate_cid != right_ref.coordinate.coordinate_cid
