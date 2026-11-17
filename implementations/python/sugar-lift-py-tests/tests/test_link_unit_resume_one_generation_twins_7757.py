"""A file with more link units than one resident generation answers mints.

Run 43960179946 (#7757): 46 pandas files (``core/frame.py``,
``core/series.py``, ``core/generic.py``, ...) answered ``CONSTRUCTION PANIC``
at about 3.4 s and ``sugar mint`` exited 1 with no proof. Every pandas file
with 63 or more ``def`` statements did, bar two. Mint's walk enrolls every
parameter-contract link unit (one per ``def`` with a formal) in one request
and resumes each in its own; the kit keeps the enrolled units in its process
until the resume (``lift_rpc._RETAINED_LINK_UNITS``). The transport retired
the resident generation after 64 successful responses, so the first resume
past that reached a fresh process with no retained unit and refused the whole
file (owner ``parameter-contract-resume``). Mint now holds one generation
from the link-unit scan through the last resume
(``LiftPluginKit::hold_generation``).

The shape is written here: seventy one-formal helpers (seventy link units,
more than one default generation of 64 answers) and a test function whose
claim calls one of them. Each half goes through real ``sugar mint`` then real
``sugar prove`` (``run_source_through_real_solver``), with the transport's
default budget.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    run_source_through_real_solver,
)

HELPERS = 70  # one link unit each: past the transport's default 64 answers

_SOURCE = (
    "".join(f"def h{i}(x):\n    return x\n\n\n" for i in range(HELPERS))
    + "def test_f():\n    assert {claim}\n"
)

_CLAIMS = {
    "truthful": f"h{HELPERS - 1}(3) == 3",
    "lying": f"h{HELPERS - 1}(3) == 4",
}


def _claims_line(source: str) -> int:
    for number, line in enumerate(source.splitlines(), start=1):
        if line.startswith("def test_"):
            return number
    raise AssertionError("the source states no test function")


def _refused_owners(lift_doc: dict) -> list:
    return [
        row["reason"]["refused"]["owner"]
        for row in lift_doc.get("ir", [])
        if row.get("kind") == "undecided" and "refused" in (row.get("reason") or {})
    ]


@pytest.mark.parametrize("half", ["truthful", "lying"])
def test_a_file_with_more_link_units_than_one_generation_mints(
    tmp_path: Path, half: str
) -> None:
    text = _SOURCE.format(claim=_CLAIMS[half])
    native: dict = {}
    exec(text, native)
    if half == "truthful":
        native["test_f"]()
    else:
        with pytest.raises(AssertionError):
            native["test_f"]()
    # A refused resume fails mint, which the harness raises: the file mints.
    result = run_source_through_real_solver(tmp_path / half, text)
    assert "parameter-contract-resume" not in _refused_owners(result.lift_doc)
    verdict = claim_verdict(
        result.prove_doc,
        claims_from_line=_claims_line(text),
        lift_doc=result.lift_doc,
    )
    if half == "lying":
        assert verdict != "sat", result.prove_doc
    else:
        assert verdict != "unsat", result.prove_doc
