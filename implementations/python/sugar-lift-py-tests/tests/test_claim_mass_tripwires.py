from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pytest

from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import audit_lift_file


VENDOR = Path(__file__).parent / "vendor"


@dataclass(frozen=True)
class ClaimMassPin:
    name: str
    relative_path: str
    sha256: str
    assertion_count: int
    lifted_lines: tuple[int, ...]


PINS = (
    ClaimMassPin(
        name="datetime",
        relative_path="cpython-3.11/datetime.py",
        sha256="cc9bcb0f1c2f44e1a6cd51882979e113e973c2e65ed84b9aaedabb48d47aa356",
        assertion_count=45,
        lifted_lines=(53, 60, 65, 67, 131, 137, 144, 328, 867, 1126, 1507, 1510, 2044, 2047),
    ),
    ClaimMassPin(
        name="itsdangerous",
        relative_path="itsdangerous-2.2.0/test_serializer.py",
        sha256="e9620d6a6999a77773e3a5733ca71cb81375dafd06ad0f3a5b2bea9404e66c26",
        assertion_count=22,
        lifted_lines=(
            53,
            66,
            79,
            89,
            93,
            96,
            100,
            111,
            129,
            136,
            137,
            143,
            144,
            154,
            165,
            181,
            184,
            192,
            193,
            194,
        ),
    ),
    ClaimMassPin(
        name="pandas",
        relative_path="pandas-2.3.3/test_frame_equals.py",
        sha256="00599b73d4a67e0a505743c3f61097ba4b5109190dbc31794b567bcf7d44db11",
        assertion_count=18,
        lifted_lines=(15,),
    ),
    ClaimMassPin(
        name="numpy",
        relative_path="numpy-2.3.5/test_exceptions.py",
        sha256="96e313eaf3c875fe8bbb014d1b24fec4b31968a644618385cc5a4c69eb288e81",
        assertion_count=23,
        lifted_lines=(
            20,
            31,
            32,
            33,
            34,
            35,
            36,
            37,
            38,
            39,
            40,
            43,
            44,
            47,
            52,
            55,
            61,
            86,
        ),
    ),
)


@pytest.mark.parametrize("pin", PINS, ids=lambda pin: pin.name)
def test_claim_mass_corpus_never_silently_shrinks(pin: ClaimMassPin) -> None:
    path = VENDOR / pin.relative_path
    data = path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == pin.sha256, (
        f"{pin.name} source drifted; re-pin the source hash, assertion count, "
        "and lifted loci in the same PR"
    )

    source = data.decode("utf-8")
    payload, _gaps = audit_lift_file(source, str(path), hold_panic=True)
    assertions = account_lift_coverage(
        census_source(source, file=str(path)), payload.to_rpc()
    ).to_json()["assertions"]
    lifted_lines = tuple(locus["line"] for locus in assertions["lifted_loci"])
    observed_count = assertions["lifted_cited"] + assertions["refused_loud"]

    assert assertions["silently_unaccounted"] == 0
    assert (observed_count, lifted_lines) == (
        pin.assertion_count,
        pin.lifted_lines,
    ), (
        f"{pin.name} claim mass changed: count={observed_count}, "
        f"lifted={lifted_lines}; improvements must increase lifted coverage with "
        "zero silent and update this pin loudly"
    )
