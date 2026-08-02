"""Teeth for C4 Step 1: three sealed board function meanings.

Split overloaded functionsTotal into:
  FunctionsPopulationV1 / FunctionsEnumeratedV1 / FunctionsCleanV1

Consumer close (not producer privacy):
  board_fields_from_sealed_facts refuses bare int for any of the three.
  LocalReading may exist and cannot seal.
  Second producer minting the same sealed meaning cannot seal.

Enrollment makes dual production of THIS SEALED MEANING unsealable. Meaning is
fixed by type fields plus witness or twin. SOLE CONSTRUCTOR IS NOT EVIDENCE THE
MEANING IS RIGHT.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PKG_SRC = (
    ROOT
    / "implementations/python/sugar-lift-py-tests/src"
)
if str(PKG_SRC) not in sys.path:
    sys.path.insert(0, str(PKG_SRC))

from sugar_lift_py_tests.c4 import board_function_facts as BFF  # noqa: E402

SCRIPTS = ROOT / "implementations/python/sugar-lift-py-tests/scripts"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


TIP = "deadbeef"
PIN = "pin-agg-hash-test"


def _mint_triple(
    *,
    population: int = 5,
    enumerated: int = 3,
    clean: int | None = None,
    refused: bool = True,
):
    pop = BFF.seal_functions_population_v1(
        BFF.LocalReading(population, "functions_total"),
        tip=TIP,
        pin=PIN,
    )
    enum = BFF.seal_functions_enumerated_v1(
        BFF.LocalReading(enumerated, "functions_enumerated"),
        tip=TIP,
        pin=PIN,
    )
    if refused:
        clean_f = BFF.seal_functions_clean_v1(
            BFF.LocalReading(None, "functions_clean"),
            tip=TIP,
            pin=PIN,
            refused=True,
            refuse_reason="test refuse",
        )
    else:
        assert clean is not None
        clean_f = BFF.seal_functions_clean_v1(
            BFF.LocalReading(clean, "functions_clean"),
            tip=TIP,
            pin=PIN,
            refused=False,
        )
    return pop, enum, clean_f


def test_three_meanings_are_distinct_types_and_cids() -> None:
    """Population / enumerated / clean are three facts, three addresses."""
    pop, enum, clean = _mint_triple(population=28264, enumerated=27954, refused=True)
    assert type(pop) is BFF.FunctionsPopulationV1
    assert type(enum) is BFF.FunctionsEnumeratedV1
    assert type(clean) is BFF.FunctionsCleanV1
    assert pop.count == 28264
    assert enum.count == 27954
    assert clean.refused is True
    assert clean.count is None
    # Distinct content addresses — same informal name would have collided as one int.
    assert pop.fact_cid != enum.fact_cid
    assert pop.fact_cid != clean.fact_cid
    assert enum.fact_cid != clean.fact_cid
    assert pop.fact_cid.startswith(("blake3-512:", "sha256:"))


def test_board_fields_from_sealed_facts_wires_three_numbers() -> None:
    pop, enum, clean = _mint_triple(population=12, enumerated=2, refused=True)
    fields = BFF.board_fields_from_sealed_facts(pop, enum, clean)
    assert fields["functionsTotal"] == 12
    assert fields["functionsEnumerated"] == 2
    assert fields["functionsUnaccounted"] == 10
    assert fields["functionsConstructClean"] is None
    assert fields["cleanRatioRefused"] is True
    assert fields["denominator_functions"]["total"] == 12
    assert fields["denominator_functions"]["enumerated"] == 2
    assert fields["sealedFactCids"]["FunctionsPopulationV1"] == pop.fact_cid


def test_consumer_refuses_bare_int_for_population() -> None:
    """TOOTH: compose refuses a bare int for any of the three."""
    _, enum, clean = _mint_triple()
    with pytest.raises(BFF.BoardFunctionFactError, match="bare int|FunctionsPopulationV1"):
        BFF.board_fields_from_sealed_facts(28264, enum, clean)  # type: ignore[arg-type]


def test_consumer_refuses_bare_int_for_enumerated() -> None:
    pop, _, clean = _mint_triple()
    with pytest.raises(BFF.BoardFunctionFactError, match="bare int|FunctionsEnumeratedV1"):
        BFF.board_fields_from_sealed_facts(pop, 27954, clean)  # type: ignore[arg-type]


def test_consumer_refuses_bare_int_for_clean() -> None:
    pop, enum, _ = _mint_triple()
    with pytest.raises(BFF.BoardFunctionFactError, match="bare int|FunctionsCleanV1"):
        BFF.board_fields_from_sealed_facts(pop, enum, 0)  # type: ignore[arg-type]


def test_local_reading_exists_and_cannot_seal_via_consumer() -> None:
    """A LocalReading may exist and cannot seal as a board field."""
    local = BFF.LocalReading(28264, "functions_total", source="worker-shard")
    assert local.is_sealed() is False
    assert local.value == 28264
    _, enum, clean = _mint_triple()
    with pytest.raises(BFF.BoardFunctionFactError, match="LocalReading|FunctionsPopulationV1"):
        BFF.board_fields_from_sealed_facts(local, enum, clean)  # type: ignore[arg-type]


def test_direct_construct_without_seal_token_refuses() -> None:
    """Discrimination: forged constructor without sole-door seal cannot mint."""
    with pytest.raises(BFF.BoardFunctionFactError, match="sealed|SOLE CONSTRUCTOR"):
        BFF.FunctionsPopulationV1(
            tip=TIP,
            pin=PIN,
            count=28264,
            unit=BFF.UNIT,
            witness="forged-second-producer",
            fact_cid="blake3-512:" + "0" * 128,
            _seal=object(),  # wrong token — second producer forge
        )


def test_second_producer_cannot_seal_same_meaning() -> None:
    """Plant a second producer minting the same sealed meaning; prove it cannot seal.

    Python cannot make construction unrepresentable. The load-bearing move is
    consumer close: a second site's forge is not FunctionsPopulationV1 and is
    refused at board_fields_from_sealed_facts.
    """

    class SecondProducerPopulation:
        """Hostile second door claiming the same sealed meaning."""

        def __init__(self, count: int) -> None:
            self.tip = TIP
            self.pin = PIN
            self.count = count
            self.unit = BFF.UNIT
            self.witness = "second-producer/forge"
            self.fact_cid = "blake3-512:" + "f" * 128

        def is_sealed(self) -> bool:
            return True  # lie

    forge = SecondProducerPopulation(28264)
    _, enum, clean = _mint_triple(population=28264, enumerated=27954)
    with pytest.raises(BFF.BoardFunctionFactError, match="FunctionsPopulationV1|bare int"):
        BFF.board_fields_from_sealed_facts(forge, enum, clean)  # type: ignore[arg-type]


def test_clean_never_defaults_absent_to_zero() -> None:
    """FunctionsCleanV1: measured or absent, never defaulted."""
    with pytest.raises(BFF.BoardFunctionFactError, match="refused=True|never default"):
        BFF.seal_functions_clean_v1(
            BFF.LocalReading(None, "functions_clean"),
            tip=TIP,
            pin=PIN,
            refused=False,  # measured path with None is illegal
        )
    refused = BFF.seal_functions_clean_v1(
        BFF.LocalReading(None, "functions_clean"),
        tip=TIP,
        pin=PIN,
        refused=True,
        refuse_reason="would be tautological clean%",
    )
    assert refused.count is None
    assert refused.refused is True
    measured = BFF.seal_functions_clean_v1(
        BFF.LocalReading(100, "functions_clean"),
        tip=TIP,
        pin=PIN,
        refused=False,
    )
    assert measured.count == 100
    assert measured.refused is False


def test_seal_doors_refuse_bare_int_input() -> None:
    with pytest.raises(BFF.BoardFunctionFactError, match="LocalReading"):
        BFF.seal_functions_population_v1(28264, tip=TIP, pin=PIN)  # type: ignore[arg-type]
    with pytest.raises(BFF.BoardFunctionFactError, match="LocalReading"):
        BFF.seal_functions_enumerated_v1(27954, tip=TIP, pin=PIN)  # type: ignore[arg-type]
    with pytest.raises(BFF.BoardFunctionFactError, match="LocalReading"):
        BFF.seal_functions_clean_v1(0, tip=TIP, pin=PIN)  # type: ignore[arg-type]


def test_compose_seal_uses_three_sealed_meanings() -> None:
    """Integration: seal_board_from_aggregate mints via sealed types (local only)."""
    compose = _load(
        "compose_control_effect_board_c4",
        SCRIPTS / "compose_control_effect_board.py",
    )

    def _row(file: str, *, fn: int = 1, auth: int | None = None, panic: bool = False):
        authenticated = fn if auth is None else auth
        enumerated = 0 if panic else fn
        return (
            file,
            {
                "category": "construction-panic" if panic else "completed",
                "functionsTotal": authenticated,
                "functionsClean": None if panic else fn,
                "cleanRatioRefused": bool(panic),
                "functionsEnumerated": enumerated,
                "functionsAuthenticated": authenticated,
                "astSites": {"site:function-def": authenticated},
                "families": {"ConstructionPanic": 1} if panic else {},
                **(
                    {
                        "panic": {
                            "file": file,
                            "type": "ConstructionPanic",
                            "message": "x",
                        }
                    }
                    if panic
                    else {}
                ),
                "R_instrument_blind": 0,
            },
        )

    files = ["pandas/a.py", "pandas/b.py"]
    status, body = compose.compose_k1_from_rows(
        [
            _row("pandas/a.py", fn=3, auth=3),
            _row("pandas/b.py", fn=0, auth=2, panic=True),
        ],
        enrolled_files=files,
        measured_commit="deadbeef",
        aggregate_hash="agg",
        manifest_shape_cid="cid",
    )
    assert status == "sealed"
    assert body["functionsTotal"] == 5
    assert body["functionsEnumerated"] == 3
    assert body["functionsUnaccounted"] == 2
    assert body["functionsConstructClean"] is None
    assert body["cleanRatioRefused"] is True
    # Content addresses of the three sealed meanings land on the board.
    cids = body["sealedFunctionFactCids"]
    assert set(cids) == {
        "FunctionsPopulationV1",
        "FunctionsEnumeratedV1",
        "FunctionsCleanV1",
    }
    assert cids["FunctionsPopulationV1"] != cids["FunctionsEnumeratedV1"]
    denom_fn = body["denominator"]["functions"]
    assert denom_fn["total"] == 5
    assert denom_fn["enumerated"] == 3
    assert denom_fn["factCids"]["population"] == cids["FunctionsPopulationV1"]
