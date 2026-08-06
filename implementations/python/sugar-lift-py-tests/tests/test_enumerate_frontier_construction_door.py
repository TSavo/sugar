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
# The exact text a supplied-but-empty authority must report instead.
LOOKUP_FAILURE = "authenticated preconstruction resolution has no contract ref"


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


def test_facts_leaf_keeps_the_unresolvable_with_a_countable_panic(
    tmp_path: Path,
) -> None:
    """ARM TWO. Supplying the authority must not buy a single ``with`` its way in.

    This manager is a bare formal parameter: nothing authenticates it, so the
    provisional table holds a typed gap row at its use-site and no contract ref
    is manufactured for it. It stays a countable construction panic -- named as
    the product's own lookup failure at ``With._construct_sugar``, not as the
    instrument's missing authority.

    Without this arm, arm one is satisfiable by deleting the demand.
    """
    (tmp_path / "consumer.py").write_text(UNRESOLVABLE_WITH, encoding="utf-8")

    core = _facts_leaf(tmp_path, "consumer.py")
    assert core["status"] == "failed"
    with_gaps = [
        gap
        for gap in _panic_gaps(core)
        if str(gap.get("owner")) == "With._construct_sugar"
    ]
    assert with_gaps, f"the With demand stopped biting: {core['panics']}"
    assert any(LOOKUP_FAILURE in str(gap.get("observed")) for gap in with_gaps), (
        "an unresolvable manager must name the lookup failure, never a missing "
        f"authority: {with_gaps}"
    )
    assert all(
        str(gap.get("observedEventType", "")).endswith(
            ".ContextManagerResolutionConstructionGap"
        )
        for gap in with_gaps
    ), with_gaps


def test_facts_leaf_unmasks_what_sits_behind_the_first_with(tmp_path: Path) -> None:
    """ARM THREE. The point of unmasking: a later function is now measured too.

    The masked board reported ONE panic per file because the file's first
    ``with`` terminated the roll. ``second`` here holds an unrelated, differently
    owned gap. It is only observable once the ``with`` in ``first`` stops being a
    manufactured terminal -- which is why a RISING panic count is discovery.
    """
    (tmp_path / "behind.py").write_text(
        "def first(manager):\n"
        "    with manager:\n"
        "        pass\n"
        "\n"
        "\n"
        "def second():\n"
        "    return undefined_name\n",
        encoding="utf-8",
    )

    core = _facts_leaf(tmp_path, "behind.py")
    owners = {str(gap.get("owner")) for gap in _panic_gaps(core)}
    assert "With._construct_sugar" in owners, owners
    assert owners - {"With._construct_sugar"}, (
        "nothing behind the first `with` was measured -- the file is still "
        f"terminating at it: {core['panics']}"
    )


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

    context = lift_rpc.audit_frontier_construction_context(tmp_path)
    from sugar_lift_py_tests.context_manager_resolution import (
        ContextManagerResolutionGapV1,
    )

    rows = (getattr(context.contract_refs, "by_use_site", None) or {}).values()
    assert all(isinstance(row, ContextManagerResolutionGapV1) for row in rows), (
        "the entrance minted a resolution it was never handed: "
        f"{[type(row).__name__ for row in rows]}"
    )
