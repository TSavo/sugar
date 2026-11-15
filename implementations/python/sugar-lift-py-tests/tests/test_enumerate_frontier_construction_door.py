# SPDX-License-Identifier: MIT OR Apache-2.0
"""The ``auditFrontier`` facts leaf opens through the CONSTRUCTION door.

``_roll_call_audit_leaf`` is the census entrance: the Rust driver walks
``source_files -> functions -> facts`` and every countable construction panic on
the board comes out of it. It opened the file with ``SourceFile.from_path`` --
the bare door. A tree opened there has **no construction context**, and
``With._prebound_manager_resolution`` reads a missing context as
``RuntimeSelectedContextManager`` unconditionally. So every file containing a
``with`` halted at its first one with

    owner:    With.sugar
    observed: With manager has no injected authenticated preconstruction authority

regardless of whether that manager was resolvable. That is not a frontier, it is
a mask: the width it reports is a first-terminal lower bound and everything
behind the file's first ``with`` is invisible.

**Absence and lookup-failure must never share a representation.** These are two
different facts:

* the entrance gave construction no authority to resolve against -- an
  *instrument* defect, and the panic above is its correct name;
* the authority was supplied and this exact use-site has no authenticated
  contract in it -- a *product* gap, whose correct name is
  ``ContextManagerResolutionConstructionGap`` at ``With._construct_sugar``.

Supplying the authority does not weaken the ``With`` demand and never
manufactures a contract ref. The second arm below proves the demand still bites:
an unresolvable manager is still a countable construction panic afterwards. Only
its NAME changes -- from the instrument's absence to the product's lookup
failure.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from sugar_lift_py_tests import lift_rpc

# The exact text the masked board reported 772 times, one per file.
ABSENT_AUTHORITY = "With manager has no injected authenticated preconstruction authority"


def _facts_leaf(workspace: Path, file_rel: str) -> dict:
    """One ``sugar.enumerate level=facts auditFrontier`` demand, the census entrance."""
    captured: dict = {}
    original = lift_rpc._send_enumerate_result
    lift_rpc._send_enumerate_result = (
        lambda _mid, nodes, gaps, **_kw: captured.update(nodes=nodes, gaps=gaps)
    )
    try:
        lift_rpc._handle_enumerate(
            1,
            {
                "level": "facts",
                "workspace_root": str(workspace),
                "at": {"file": file_rel},
                "seek": True,
                "options": {"auditFrontier": True},
            },
        )
    finally:
        lift_rpc._send_enumerate_result = original
    assert not captured["gaps"], captured["gaps"]
    assert len(captured["nodes"]) == 1, captured["nodes"]
    leaf = captured["nodes"][0]["audit"]
    return leaf["semanticCore"] if "semanticCore" in leaf else leaf


def _panic_gaps(core: dict) -> list[dict]:
    return [p.get("gap") or {} for p in core["panics"]]


UNRESOLVABLE_WITH = "def use_resource(manager):\n    with manager:\n        pass\n"


def test_facts_leaf_does_not_report_absent_construction_authority(
    tmp_path: Path,
) -> None:
    """ARM ONE. The entrance supplies the authority, so the mask is gone.

    RED against the bare door: with no construction context every ``with`` --
    resolvable or not -- reports ``RuntimeSelectedContextManager`` naming a
    MISSING AUTHORITY. The authority is the entrance's job, and the entrance
    now does it.
    """
    (tmp_path / "consumer.py").write_text(UNRESOLVABLE_WITH, encoding="utf-8")

    core = _facts_leaf(tmp_path, "consumer.py")
    offenders = [
        gap for gap in _panic_gaps(core) if ABSENT_AUTHORITY in str(gap.get("observed"))
    ]
    assert offenders == [], (
        "the census entrance still constructs without preconstruction authority: "
        f"{offenders}"
    )


def test_facts_leaf_builds_a_with_whose_manager_nothing_authenticates(
    tmp_path: Path,
) -> None:
    """ARM TWO. A ``with`` over a manager nothing authenticates is built.

    This manager is a bare formal parameter. The table answers imported calls
    only; every other head keeps the undecided row, and its manager is the
    value the head reduces to (``With._reduced_manager_sugar``): each step of
    it is decided at reduce, two-faced and owing the one undecided member
    where the value's type is not known. So the tree is built -- no
    construction panic, neither the instrument's missing authority nor a
    lookup failure -- and no contract ref is manufactured for it
    (``test_facts_leaf_never_manufactures_a_contract_ref``).

    It used to be a countable construction panic at ``With._construct_sugar``
    (``authenticated preconstruction resolution has no contract ref``); that
    refusal was the source-derived manager pre-pass, which is deleted.
    """
    (tmp_path / "consumer.py").write_text(UNRESOLVABLE_WITH, encoding="utf-8")

    core = _facts_leaf(tmp_path, "consumer.py")
    assert core["status"] == "clean", core
    assert _panic_gaps(core) == [], core["panics"]

    source_file = lift_rpc.open_source_file_for_construction(
        tmp_path / "consumer.py", root=tmp_path
    )
    function = next(source_file.functions())
    (statement,) = function.sugar().statements
    assert type(statement).__name__.startswith("With"), type(statement).__name__


def test_frontier_leaf_never_reaches_the_bare_door(tmp_path: Path) -> None:
    """Enforcement ladder above prose: the leaf's own scope may not name it.

    ``scripts/construction_context_door_law.py`` catches
    ``SourceFile.from_path`` + ``.sugar()`` in one scope. This leaf drives
    construction through ``roll_call.discharge``, which the law's syntactic
    pattern does not see -- so the door law was silent here for as long as the
    defect existed. This tooth closes that blind spot at the one scope that had
    it.
    """
    body = inspect.getsource(lift_rpc._roll_call_audit_leaf)
    assert "SourceFile.from_path" not in body, (
        "the census entrance is back on the bare door; a context-less tree "
        "paints every With RuntimeSelectedContextManager"
    )
    assert "open_source_file_for_construction" in body


@pytest.mark.parametrize("source", [UNRESOLVABLE_WITH, "x = 1\n"])
def test_facts_leaf_never_manufactures_a_contract_ref(
    tmp_path: Path, source: str
) -> None:
    """No use-site is silently promoted: the authority is a table, not a grant."""
    (tmp_path / "t.py").write_text(source, encoding="utf-8")

    context = lift_rpc.enumerate_construction_context(tmp_path)
    from sugar_lift_py_tests.context_manager_resolution import (
        ContextManagerResolutionGapV1,
    )

    rows = (getattr(context.contract_refs, "by_use_site", None) or {}).values()
    assert all(isinstance(row, ContextManagerResolutionGapV1) for row in rows), (
        "the entrance minted a resolution it was never handed: "
        f"{[type(row).__name__ for row in rows]}"
    )


