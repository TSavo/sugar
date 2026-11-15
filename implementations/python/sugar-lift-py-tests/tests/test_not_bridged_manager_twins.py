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

The consumer's source owes a second member: the ``==`` applied to the call's
result.  At lift that result is a value whose type the lifter does not have,
so the operation is the one two-faced outcome and owes a member with no symbol
at its own site (``unanswered_calls``).  No contract answers it by name.
Staged, the vendor's post states what the call returned (``out = n + n`` at
``n = 3``, an ``int``), so at prove the solver decides that the ``==``
completes: the member is answered by the joined contract, reported
``discharged`` (``answered: ...``), and nothing is owed (step 9, #7766).  The
truthful half is ``sat``.  Unstaged nothing decides the operand, and it stays
owed beside the call.

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
# prove names its member by file and line.
_OPERATION = "undecided:test_witness.py:5"


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


def _member_rows(prove_doc: dict) -> list[dict]:
    """This project's ``undecided`` member rows: owed, or answered at prove."""
    return [
        row
        for row in prove_doc.get("rows") or []
        if str(row.get("property") or "").startswith("undecided:")
    ]


def _owed(prove_doc: dict) -> set[str]:
    """The name of every member this project owes."""
    return {
        str(row["property"])
        for row in _member_rows(prove_doc)
        if row["status"] != "discharged"
    }


def _answered(prove_doc: dict) -> dict[str, str]:
    """Every member prove answered: its name and the reason it gives."""
    return {
        str(row["property"]): str(row["reason"])
        for row in _member_rows(prove_doc)
        if row["status"] == "discharged"
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
    # The ``==`` on the arrived result is answered by the joined contract:
    # the vendor's post pins the result to an int, so the solver decides the
    # comparison completes.  Nothing is owed and the source reads ``sat``.
    assert _owed(truthful) == set()
    assert truthful["owed"] == 0
    answered = _answered(truthful)
    assert set(answered) == {_OPERATION}
    assert answered[_OPERATION].startswith("answered: ")
    assert "python:nb_vendor.twice" in answered[_OPERATION]
    assert "python:compare.completes" in answered[_OPERATION]
    assert prove_verdict(truthful) == "sat"
    # The lying half's ``==`` completes too (it returns False): its member is
    # answered, and the claim's own row carries the refutation.
    assert set(_answered(lying)) == {_OPERATION}

    # No proof answers the symbol: the call is owed, the ``==`` on its
    # result is owed beside it, and the claim is not discharged and never
    # refuted.
    assert {_CALL_OWED, _OPERATION} <= _owed(unstaged)
    assert _answered(unstaged) == {}
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
