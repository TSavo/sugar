"""Federation twins: a callee the Python lifter does not have is an open edge.

"Not bridged" is not a kind of value and not a reason: it is the state of an
edge.  The consumer's proof carries the call's coordinate and an edge whose
target symbol nothing has answered yet.  When a proof that answers that symbol
is staged in ``.sugar/imports/``, the edge binds and the solver decides, with
no change to the Python lifter (the shape of
``examples/python-base64-federation``).  What the callee is implemented in is
never asked: the vendor here happens to be Python, and the consumer's lift
cannot tell.

The consumer project holds the consumer's test and nothing else: the vendor's
source is not in it, so the lifter does not have ``twice``.  The vendor project
holds ``nb_vendor.py``, so its proof speaks ``python:nb_vendor.twice``, the
string the consumer's edge carries; the join is by that string (step 9).
(Before, the consumer project also held a copy of the vendor's source and the
vendor's proof was minted from ``test_witness.py``, so the staged proof spoke
another symbol and joined nothing.)

* truthful consumer claim + imported vendor proof: the claim's row is
  discharged;
* lying consumer claim (the one thing changed) + the same proof: ``unsat``;
* the truthful claim with no imported proof: the call is owed and the row
  stays open (never ``unsat`` from a fabricated fact, never dropped).

Staged, the consumer's source still owes one thing: the ``==`` applied to the
call's result.  At lift that result is a value whose type the lifter does not
have, so the operation is the one two-faced outcome and owes a member with no
symbol at its own site (``unanswered_calls``); nothing joins a member with no
symbol, so it stays owed after the call is answered.  A source that owes
anything is never ``sat`` as a whole (step 8), so the truthful half reads
``open`` through ``prove_verdict`` with its claim row discharged: the twin
states both, and names the one member behind the ``open``.

The second pair is a ``with`` head the lifter does not have: ``_thread`` is
authenticated by no artifact, and ``tempfile`` is pure-Python stdlib off the
enrolled population.  Each is cited as not bridged, one way.  Nothing is
staged for either, so the manager call is owed under its target symbol and
the claim about what ``__enter__`` returned is not decided: the truthful half
is ``open`` by the not-bridged rule, and becomes ``sat`` on the day a proof
for the manager can be imported.  The lying half binds the same name to
source the lifter has, whose ``__enter__`` returns the one value the claim
denies: ``unsat``.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    _stage_cli_project,
    mint_and_prove,
    mint_project,
    prove_verdict,
    run_source_through_real_solver,
)

_VENDOR = (
    "def twice(n):\n"
    "    return n + n\n"
    "\n"
    "\n"
    "def test_vendor():\n"
    "    assert twice(2) == 4\n"
)

# The consumer's call is owed under this symbol until a proof answers it.
_CALL_OWED = "undecided:python:nb_vendor.twice"
# The ``==`` on the call's result, on the consumer's line 5: no symbol, so
# prove names it by file and line.
_OPERATION_OWED = "undecided:test_witness.py:5"


def _consumer(claim: int) -> str:
    return (
        "from nb_vendor import twice\n"
        "\n"
        "\n"
        "def test_consumer():\n"
        f"    assert twice(3) == {claim}\n"
    )


def _vendor_proof(root: Path) -> Path:
    """The vendor's proof, minted in its own project from ``nb_vendor.py``."""
    vendor = root / "vendor"
    _stage_cli_project(vendor, _VENDOR)
    (vendor / "test_witness.py").rename(vendor / "nb_vendor.py")
    mint = mint_project(vendor)
    assert mint.returncode == 0, mint.stderr
    (proof,) = sorted(vendor.glob("*.proof"))
    return proof


def _consumer_prove_doc(root: Path, claim: int, vendor_proof: Path | None) -> dict:
    consumer = root / f"consumer-{claim}-{'import' if vendor_proof else 'none'}"
    _stage_cli_project(consumer, _consumer(claim))
    if vendor_proof is not None:
        imports = consumer / ".sugar" / "imports"
        imports.mkdir(parents=True, exist_ok=True)
        shutil.copy(vendor_proof, imports / vendor_proof.name)
    # Mint and prove through the harness's one door (``mint_and_prove``).
    return mint_and_prove(consumer).prove_doc


def _claim_statuses(prove_doc: dict) -> set[str]:
    """The status of the consumer's claim row(s)."""
    return {
        row["status"]
        for row in prove_doc.get("rows") or []
        if row.get("property") == "consistency:test_consumer"
    }


def _owed(prove_doc: dict) -> set[str]:
    """The name of every member this project owes."""
    return {
        str(row["property"])
        for row in prove_doc.get("rows") or []
        if str(row.get("property") or "").startswith("undecided:")
    }


def test_not_bridged_call_binds_to_an_imported_proof(tmp_path: Path) -> None:
    vendor_proof = _vendor_proof(tmp_path)

    truthful = _consumer_prove_doc(tmp_path, 6, vendor_proof)
    lying = _consumer_prove_doc(tmp_path, 7, vendor_proof)
    unstaged = _consumer_prove_doc(tmp_path, 6, None)

    # Staged: the call is answered, so it is no longer owed, and the claim's
    # row is decided each way.
    assert _claim_statuses(truthful) == {"discharged"}
    assert _claim_statuses(lying) == {"unsatisfied"}
    assert prove_verdict(lying) == "unsat"
    # What the truthful source still owes is the ``==`` on the arrived
    # result, and only that: the source as a whole reads ``open``.
    assert _owed(truthful) == {_OPERATION_OWED}
    assert prove_verdict(truthful) == "open"

    # No proof answers the symbol: the call is owed, the claim is not
    # discharged and never refuted.
    assert _CALL_OWED in _owed(unstaged)
    assert "discharged" not in _claim_statuses(unstaged)
    assert prove_verdict(unstaged) == "open"


_WITH_BODY = (
    "\n"
    "def test_claim_after_not_bridged_manager():\n"
    "    with {name}() as x:\n"
    "        pass\n"
    "    assert x != 8\n"
)

# One head no artifact authenticates (``_thread`` is compiled into the
# interpreter) and one pure-Python stdlib head off the enrolled population.
_NOT_BRIDGED = [("_thread", "allocate_lock"), ("tempfile", "TemporaryDirectory")]


@pytest.mark.parametrize(("module", "name"), _NOT_BRIDGED)
def test_not_bridged_manager_is_cited_and_bridged_source_refutes(
    tmp_path: Path, module: str, name: str
) -> None:
    truthful_source = f"from {module} import {name}\n" + _WITH_BODY.format(name=name)
    # The one thing changed: the name is bound to source the lifter HAS.
    lying_source = (
        f"class {name}:\n"
        "    def __enter__(self):\n"
        "        return 8\n"
        "    def __exit__(self, *exc):\n"
        "        return False\n" + _WITH_BODY.format(name=name)
    )
    truthful = run_source_through_real_solver(tmp_path / "t", truthful_source)
    lying = run_source_through_real_solver(tmp_path / "l", lying_source)
    # Not bridged: the manager call is owed under its own target symbol, and
    # the claim on what ``__enter__`` returned is not decided.
    assert any(
        owed.startswith(f"undecided:python:{module}.")
        for owed in _owed(truthful.prove_doc)
    ), _owed(truthful.prove_doc)
    assert truthful.verdict == "open"
    assert lying.verdict == "unsat"
