"""Membership testimony: exempt the exhausted seat, and ONLY the exhausted seat.

The ceiling worked — eight shards ran to completion, no hangs — and then shard
4 refused itself anyway, because `core/groupby/generic.py` produced no
relation-membership testimony and the membership check knew only two outcomes:
testified, or silent. A seat the bound stopped never got far enough to testify,
so refusing the shard for that absence punishes it for the bound working.

The mirror of the discriminator already in this branch. Both arms, because a
blanket "tolerate missing membership" would re-open the hole the ceiling
closed: every seat that actually FINISHED must still testify.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import compose_control_effect_board as compose  # noqa: E402
from recensus_enumerate_consumer import (  # noqa: E402
    RELATION_MEMBERSHIP_ROW_FIELD,
    shard_relation_membership_attestation,
)

_RELATIONS = compose.RELATION_MEMBERSHIP_RELATIONS


def _testifying_row() -> dict:
    return {
        "category": "completed",
        "terminalKind": "constructed",
        RELATION_MEMBERSHIP_ROW_FIELD: {
            relation: {"expected": [], "observed": []} for relation in _RELATIONS
        },
    }


def _silent_row() -> dict:
    """Walked, finished, said nothing. Still a refusal."""
    return {"category": "completed", "terminalKind": "constructed"}


def _exhausted_row(file: str = "core/groupby/generic.py") -> dict:
    return {
        "category": "measurement-exhausted",
        "terminalKind": "measurement-exhausted",
        "measurementExhaustion": {
            "file": file,
            "boundSeconds": 300.0,
            "construct": "SubstituteStatement",
            "coordinate": "pandas/core/groupby/generic.py:1324 Return",
        },
    }


# --------------------------------------------------------------------------
# ARM ONE: the exhausted seat is exempt, and NAMED.
# --------------------------------------------------------------------------


def test_exhausted_seat_does_not_refuse_the_shard() -> None:
    """Shard 4's exact shape: 177 testifying seats and one the bound stopped."""
    rows = [(f"f{index}.py", _testifying_row()) for index in range(177)]
    rows.append(("core/groupby/generic.py", _exhausted_row()))
    attestation, reason = shard_relation_membership_attestation(rows)
    assert reason is None, reason
    assert attestation is not None


def test_the_exemption_names_the_bound_and_the_coordinate() -> None:
    """Not a tolerance — testimony about why testimony is absent.

    "absent because measurement stopped" is a different fact from "absent
    because nothing was found", and a bare exemption list would let them
    share a representation.
    """
    attestation, reason = shard_relation_membership_attestation(
        [("core/groupby/generic.py", _exhausted_row())]
    )
    assert reason is None
    seats = attestation["measurementExhaustedSeats"]
    assert [seat["file"] for seat in seats] == ["core/groupby/generic.py"]
    assert seats[0]["boundSeconds"] == 300.0
    assert seats[0]["coordinate"] == "pandas/core/groupby/generic.py:1324 Return"
    assert seats[0]["construct"] == "SubstituteStatement"


def test_the_exemption_survives_the_seal_door() -> None:
    """The authenticator must accept it and carry it into the conserved wire.

    An exemption the seal drops is an exemption no board reader can audit.
    """
    attestation, _ = shard_relation_membership_attestation(
        [("g.py", _exhausted_row()), ("ok.py", _testifying_row())]
    )
    verdict = compose.authenticate_relation_membership(attestation)
    assert verdict.refusal_reason() is None
    wire = verdict.conserved_wire()
    assert [seat["file"] for seat in wire["measurementExhaustedSeats"]] == ["g.py"]


def test_attendance_conserves_walked_equals_testified_plus_exempt() -> None:
    rows = [("a.py", _testifying_row()), ("b.py", _testifying_row())]
    rows.append(("g.py", _exhausted_row()))
    attestation, reason = shard_relation_membership_attestation(rows)
    assert reason is None
    assert len(attestation["measurementExhaustedSeats"]) == 1
    # 3 walked = 2 testified + 1 exempt. The producer raises if that fails;
    # this is the arm that proves the sum is over real counts.
    assert len(rows) == 2 + len(attestation["measurementExhaustedSeats"])


# --------------------------------------------------------------------------
# ARM TWO: the requirement STILL BITES for every seat that finished.
# --------------------------------------------------------------------------


def test_a_finished_seat_that_says_nothing_still_refuses_the_shard() -> None:
    """The whole point of not making this a blanket tolerance."""
    attestation, reason = shard_relation_membership_attestation(
        [("ok.py", _testifying_row()), ("quiet.py", _silent_row())]
    )
    assert attestation is None
    assert reason is not None
    assert "quiet.py" in reason


def test_a_silent_seat_beside_an_exhausted_one_still_refuses() -> None:
    """An exempt seat must not carry a silent neighbour through with it."""
    attestation, reason = shard_relation_membership_attestation(
        [("g.py", _exhausted_row()), ("quiet.py", _silent_row())]
    )
    assert attestation is None
    assert "quiet.py" in reason
    assert "g.py" not in reason


@pytest.mark.parametrize(
    "damage,label",
    [
        ({"measurementExhaustion": None}, "no exhaustion payload"),
        ({"measurementExhaustion": {"boundSeconds": 300.0}}, "no coordinate"),
        (
            {"measurementExhaustion": {"coordinate": "g.py:1 Return"}},
            "no bound",
        ),
    ],
)
def test_a_row_that_merely_spells_the_kind_is_not_exempt(
    damage: dict, label: str
) -> None:
    """AUTHENTICATED, not asserted.

    If spelling `terminalKind` were enough, "exempt" would be a word a shard
    could write beside any silent file, and the exemption becomes the blanket
    tolerance it must never be.
    """
    row = {**_exhausted_row(), **damage}
    attestation, reason = shard_relation_membership_attestation([("g.py", row)])
    assert attestation is None, f"{label} was accepted as an exemption"
    assert "g.py" in reason


# --------------------------------------------------------------------------
# The seal door's own tooth: an exemption must be backed by a real row.
# --------------------------------------------------------------------------


_DEMAND_CID = "blake3-512:table-a"


def _demand_identity() -> dict:
    from sugar_lift_py_tests.demand_table_identity import DemandTableIdentityV1
    from compose_control_effect_board import cid_of_json

    seed = DemandTableIdentityV1(
        content_key="",
        corpus_manifest_cid="blake3-512:corpus-a",
        schema_version="python-demand-table/v1",
        producer_source_cid="blake3-512:producer-a",
        resolution_config_cid="blake3-512:config-a",
        parser_identity="cpython-3.12",
        file_count=2,
    )
    return DemandTableIdentityV1(
        content_key=cid_of_json(dict(seed.preimage())),
        corpus_manifest_cid=seed.corpus_manifest_cid,
        schema_version=seed.schema_version,
        producer_source_cid=seed.producer_source_cid,
        resolution_config_cid=seed.resolution_config_cid,
        parser_identity=seed.parser_identity,
        file_count=seed.file_count,
    ).as_dict()


def _plan(files: list[str]) -> dict:
    return compose.build_plan(
        enrolled_files=sorted(files),
        shard_count=1,
        measured_commit="c" * 40,
        aggregate_hash="a" * 64,
        manifest_shape_cid="sha256:" + "b" * 64,
        bins=[sorted(files)],
        split_mode="k1",
        prior_hits=0,
        prior_misses=0,
        estimated_loads=[0.0],
        demand_table_cid=_DEMAND_CID,
        demand_table_identity=_demand_identity(),
    )


def test_an_unsupported_exemption_is_refused_at_the_partial_door() -> None:
    """The attestation is written by the shard whose seats it exempts.

    So a shape check there proves nothing. mint_partial is the one place that
    holds the terminal rows AND the attestation, and it refuses an exemption
    with no measurement-exhausted row behind it.
    """
    rows = [("quiet.py", _silent_row())]
    forged = {
        "schema": compose._RELATION_MEMBERSHIP_SCHEMA,
        "relations": {
            relation: {
                "expected": compose._member_manifest_wire(relation, []),
                "observed": compose._member_manifest_wire(relation, []),
            }
            for relation in _RELATIONS
        },
        "measurementExhaustedSeats": [
            {
                "file": "quiet.py",
                "boundSeconds": 300.0,
                "construct": "X",
                "coordinate": "quiet.py:1 Return",
            }
        ],
    }
    partial = compose.mint_partial(
        plan=_plan(["quiet.py"]),
        shard_index=0,
        terminal_rows=rows,
        measured_commit="c" * 40,
        demand_table_cid=_DEMAND_CID,
        demand_table_identity=_demand_identity(),
        relation_membership_attestation=forged,
    )
    assert partial["measured"] is False
    assert "exemption-unsupported" in str(partial["unmeasuredReason"])
    assert "quiet.py" in str(partial["unmeasuredReason"])


def test_a_supported_exemption_lets_the_shard_publish_a_partial() -> None:
    """The other side of the same discriminator — run both.

    This is the whole point: shard 4 must be able to write `measured=True`
    with the bounded seat in it.
    """
    rows = [("ok.py", _testifying_row()), ("g.py", _exhausted_row())]
    attestation, reason = shard_relation_membership_attestation(rows)
    assert reason is None
    partial = compose.mint_partial(
        plan=_plan(["ok.py", "g.py"]),
        shard_index=0,
        terminal_rows=rows,
        measured_commit="c" * 40,
        demand_table_cid=_DEMAND_CID,
        demand_table_identity=_demand_identity(),
        relation_membership_attestation=attestation,
    )
    assert partial["measured"] is True, partial["unmeasuredReason"]
    assert partial["status"] == "completed"


def test_an_exhausted_seat_is_not_a_shard_instrument_defect() -> None:
    """The instrument worked exactly as specified; calling that a defect
    reports a harness fault for a product fact."""
    rows = [("g.py", _exhausted_row())]
    attestation, _ = shard_relation_membership_attestation(rows)
    partial = compose.mint_partial(
        plan=_plan(["g.py"]),
        shard_index=0,
        terminal_rows=rows,
        measured_commit="c" * 40,
        demand_table_cid=_DEMAND_CID,
        demand_table_identity=_demand_identity(),
        relation_membership_attestation=attestation,
    )
    residuals = partial["shardResiduals"]
    assert residuals["instrumentDefects"] == []
    assert residuals["constructionPanics"] == []
    assert residuals["R_measurement_exhausted_shard"] == 1
    assert residuals["measurementExhausted"][0]["file"] == "g.py"
    assert (
        residuals["measurementExhausted"][0]["coordinate"]
        == "pandas/core/groupby/generic.py:1324 Return"
    )


def test_a_lying_twin_cannot_buy_exemption_with_a_payload_alone() -> None:
    """THE tooth. A seat that CONSTRUCTED but carries an exhaustion payload.

    Every other silent fixture in this file lacks the payload, so they are all
    still refused even if the terminal-kind check is deleted — which means
    none of them can tell whether that check does any work. This one can: it
    is well-formed in every respect the payload validator looks at, and the
    ONLY thing standing between it and an exemption is that its terminalKind
    says it constructed.

    If this passes without the kind check, "exempt" is purchasable with a
    payload, and the exemption is the blanket tolerance it must never be.
    """
    twin = {
        "category": "completed",
        "terminalKind": "constructed",
        "measurementExhaustion": {
            "file": "twin.py",
            "boundSeconds": 300.0,
            "construct": "SubstituteStatement",
            "coordinate": "twin.py:1 Return",
        },
    }
    attestation, reason = shard_relation_membership_attestation([("twin.py", twin)])
    assert attestation is None, (
        "a constructed seat bought a membership exemption with a payload"
    )
    assert "twin.py" in reason


def test_the_honest_twin_of_that_pair_is_still_exempt() -> None:
    """Both sides of the discriminator. Same payload, exhausted kind."""
    honest = {
        "category": "measurement-exhausted",
        "terminalKind": "measurement-exhausted",
        "measurementExhaustion": {
            "file": "twin.py",
            "boundSeconds": 300.0,
            "construct": "SubstituteStatement",
            "coordinate": "twin.py:1 Return",
        },
    }
    attestation, reason = shard_relation_membership_attestation([("twin.py", honest)])
    assert reason is None
    assert [s["file"] for s in attestation["measurementExhaustedSeats"]] == ["twin.py"]


def test_the_exempt_seat_reaches_the_corpus_board_by_name() -> None:
    """The union must carry it, not just the shard.

    A seat that is exempt in s4 and invisible on the corpus board is a width
    sealed over a file no reader can see was never measured — the unknown
    denominator this attestation exists to make impossible.
    """
    shard = shard_relation_membership_attestation(
        [("ok.py", _testifying_row()), ("g.py", _exhausted_row())]
    )[0]
    verdict = compose.authenticate_relation_membership(shard)
    composed = {
        "schema": compose._RELATION_MEMBERSHIP_SCHEMA,
        "relations": verdict.conserved_wire()["relations"],
        "measurementExhaustedSeats": verdict.conserved_wire()[
            "measurementExhaustedSeats"
        ],
    }
    corpus = compose.authenticate_relation_membership(composed)
    assert corpus.refusal_reason() is None
    assert [s["file"] for s in corpus.conserved_wire()["measurementExhaustedSeats"]] == [
        "g.py"
    ]


def test_two_shards_claiming_the_same_exempt_seat_are_refused() -> None:
    """A file belongs to exactly one bin.

    The same name twice is two shards claiming one seat, which is a fault to
    name — not a duplicate to quietly collapse.
    """
    seat = {
        "file": "g.py",
        "boundSeconds": 300.0,
        "construct": "SubstituteStatement",
        "coordinate": "g.py:1 Return",
    }
    composed = {
        "schema": compose._RELATION_MEMBERSHIP_SCHEMA,
        "relations": {
            relation: {
                "expected": compose._member_manifest_wire(relation, []),
                "observed": compose._member_manifest_wire(relation, []),
            }
            for relation in _RELATIONS
        },
        "measurementExhaustedSeats": [dict(seat), dict(seat)],
    }
    verdict = compose.authenticate_relation_membership(composed)
    assert verdict.refusal_reason() is not None
