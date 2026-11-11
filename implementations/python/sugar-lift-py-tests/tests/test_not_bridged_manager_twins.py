"""Federation twins: a callee the Python lifter does not have is an open edge.

"Not bridged" is not a kind of value and not a reason: it is the state of an
edge.  The consumer's proof carries the call's coordinate and an edge whose
target symbol nothing has answered yet.  When a proof that answers that symbol
is staged in ``.sugar/imports/``, the edge binds and the solver decides, with
no change to the Python lifter (the shape of
``examples/python-base64-federation``).  What the callee is implemented in is
never asked: the vendor here happens to be Python, and the consumer's lift
cannot tell.

* truthful consumer claim + imported vendor proof: ``sat``;
* lying consumer claim (the one thing changed) + the same proof: ``unsat``;
* the truthful claim with no imported proof: the row stays open (never
  ``unsat`` from a fabricated fact, never dropped).

The second pair is the ``with`` head this change routes: ``_thread`` is
authenticated by no artifact, so the lifter does not have
``allocate_lock``.  Before this change the head was refused
(``no-derived-contract``): the interpreter-inspection check cited only C
types.  Now it is cited as not bridged exactly like ``tempfile`` (pure-Python
stdlib off the enrolled population), and the claim after the ``with`` stands
on the completing face.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    _stage_cli_project,
    mint_project,
    prove_verdict,
    run_source_through_real_solver,
    run_sugar_cli,
)

_VENDOR = (
    "def twice(n):\n"
    "    return n + n\n"
    "\n"
    "\n"
    "def test_vendor():\n"
    "    assert twice(2) == 4\n"
)


def _consumer(claim: int) -> str:
    return (
        "from nb_vendor import twice\n"
        "\n"
        "\n"
        "def test_consumer():\n"
        f"    assert twice(3) == {claim}\n"
    )


def _mint(project: Path, source: str, extra: dict[str, str]) -> None:
    _stage_cli_project(project, source)
    for name, text in extra.items():
        (project / name).write_text(text, encoding="utf-8")
    mint = mint_project(project)
    assert mint.returncode == 0, mint.stderr


def _prove(project: Path) -> str:
    prove = run_sugar_cli(project, ["prove", ".", "--json", "--z3", "z3"])
    return prove_verdict(json.loads(prove.stdout))


def _consumer_verdict(root: Path, claim: int, vendor_proof: Path | None) -> str:
    consumer = root / f"consumer-{claim}-{'import' if vendor_proof else 'none'}"
    _stage_cli_project(consumer, _consumer(claim))
    (consumer / "nb_vendor.py").write_text(_VENDOR, encoding="utf-8")
    if vendor_proof is not None:
        imports = consumer / ".sugar" / "imports"
        imports.mkdir(parents=True, exist_ok=True)
        shutil.copy(vendor_proof, imports / vendor_proof.name)
    mint = mint_project(consumer)
    assert mint.returncode == 0, mint.stderr
    return _prove(consumer)


def test_not_bridged_call_binds_to_an_imported_proof(tmp_path: Path) -> None:
    vendor = tmp_path / "vendor"
    _mint(vendor, _VENDOR, {})
    (vendor_proof,) = sorted(vendor.glob("*.proof"))

    assert _consumer_verdict(tmp_path, 6, vendor_proof) == "sat"
    assert _consumer_verdict(tmp_path, 7, vendor_proof) == "unsat"
    # No proof answers the symbol: the edge stays open, never refuted.
    assert _consumer_verdict(tmp_path, 6, None) not in {"unsat", "sat"}


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
    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"
