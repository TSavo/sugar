"""Universal write-door contract: validation testimony or explicit refusal."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from sugar_lift_py_tests.repo_root import resolve_repo_root

ROOT = resolve_repo_root()
PKG_SRC = ROOT / "implementations/python/sugar-lift-py-tests/src"
if str(PKG_SRC) not in sys.path:
    sys.path.insert(0, str(PKG_SRC))

from sugar_lift_py_tests.conservation_mint import (  # noqa: E402
    CONSERVATION_WITNESS_SCHEMA,
    ConservationFailure,
    ConservedBody,
    decode_conserved_body,
    key_manifest_cid,
    seal_after_validation,
)


def test_passed_validator_is_the_only_measured_constructor(tmp_path: Path) -> None:
    source = tmp_path / "validator.py"
    source.write_text("def validate(): pass\n", encoding="utf-8")
    inputs = [{"file": "a.py"}, {"file": "b.py"}]
    outputs = list(reversed(inputs))
    called = 0

    def validate() -> None:
        nonlocal called
        called += 1
        assert sorted(row["file"] for row in inputs) == sorted(
            row["file"] for row in outputs
        )

    outcome = seal_after_validation(
        measured_payload={"kind": "example-measured-v1", "totals": {"R": 2}},
        input_key_manifest=inputs,
        output_key_manifest=outputs,
        validator_stage_id="example-validator/v1",
        validator_source_path=source,
        validate=validate,
    )

    assert called == 1
    assert isinstance(outcome, ConservedBody)
    body = outcome.to_wire()
    assert body["measurement"] == "measured"
    witness = body["conservationWitness"]
    assert witness == {
        "witnessSchema": CONSERVATION_WITNESS_SCHEMA,
        "inputKeyManifestCid": key_manifest_cid(inputs),
        "inputKeyCount": 2,
        "outputKeyManifestCid": key_manifest_cid(outputs),
        "outputKeyCount": 2,
        "validatorStageId": "example-validator/v1",
        "validatorSourceCid": witness["validatorSourceCid"],
        "status": "passed",
    }
    assert witness["validatorSourceCid"].startswith(("blake3-512:", "sha256:"))
    assert decode_conserved_body(body).witness.to_wire() == witness


def test_failed_validator_has_no_magnitude_constructor(tmp_path: Path) -> None:
    source = tmp_path / "validator.py"
    source.write_text("raise ValueError('no')\n", encoding="utf-8")

    def validate() -> None:
        raise ValueError("input/output key conservation failed")

    outcome = seal_after_validation(
        measured_payload={
            "kind": "example-measured-v1",
            "residualCount": 47,
            "totals": {"R": 47},
        },
        input_key_manifest=[{"file": "a.py"}, {"file": "b.py"}],
        output_key_manifest=[{"file": "a.py"}],
        validator_stage_id="example-validator/v1",
        validator_source_path=source,
        validate=validate,
    )

    assert isinstance(outcome, ConservationFailure)
    body = outcome.to_wire()
    assert body["measurement"] == "unmeasured"
    assert body["conservationFailure"]["reason"] == (
        "ValueError: input/output key conservation failed"
    )
    assert "residualCount" not in body
    assert "totals" not in body
    assert "47" not in str(body)


def test_consumer_rejects_measured_body_without_witness() -> None:
    with pytest.raises(ValueError, match="conservationWitness"):
        decode_conserved_body(
            {"kind": "lying-measured-v1", "measurement": "measured", "totals": {}}
        )
