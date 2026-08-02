"""One door for each board function count — three sealed meanings.

A board nearly sealed with 18230 when the real population was 27954 because two
sites computed "how many functions" as bare ints and disagreed. That is illegal.

Three distinct sealed types (not one overloaded int):
  FunctionsPopulationV1  — authenticated AST count over the pin
  FunctionsEnumeratedV1  — what construction actually rostered
  FunctionsCleanV1       — measured or refused, never defaulted to zero

Law: a number reaches the sealed board only through board_fields_from_sealed_facts.
Bare int and LocalReading refuse. A second producer of the same meaning cannot
construct a seal that the board accepts. Construct the sealed fact, or panic.
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
        source_cid = "sha256:" + ("a" if file.endswith("a.py") else "b") * 64
        function_keys = [
            {
                "sourceCid": source_cid,
                "file": file,
                "functionSourceCid": source_cid,
                "functionName": f"f{index}",
                "span": {
                    "startLine": index + 1,
                    "startCol": 0,
                    "endLine": index + 1,
                    "endCol": 1,
                },
            }
            for index in range(authenticated)
        ]
        input_key = {
            "sourceCid": source_cid,
            "file": file,
            "functionKeyManifest": function_keys,
            "functionKeyCid": compose.key_manifest_cid(function_keys),
        }
        terminal_kind = "construction-panic" if panic else "constructed"
        panic_payload = {
            "file": file,
            "owner": "FunctionSugar",
            "coordinate": f"{file}:1:0",
            "observed": "UnconstructedFunction",
            "requested": "constructed function",
            "fix": "write the missing function sugar",
            "entrance": "sugar.enumerate:facts",
            "observedEventType": (
                "sugar_lift_py_tests.gap.panic.ConstructionPanic"
            ),
            "construction_trace": [
                {
                    "kind": "source-construct",
                    "constructOwner": "FunctionSugar",
                    "coordinate": f"{file}:1:0",
                }
            ],
            "message": "x",
        }
        return (
            file,
            {
                "category": "panic" if panic else "completed",
                "functionsTotal": authenticated,
                "functionsClean": None if panic else fn,
                "cleanRatioRefused": bool(panic),
                "functionsEnumerated": enumerated,
                "functionsAuthenticated": authenticated,
                "astSites": {"site:function-def": authenticated},
                "families": {"ConstructionPanic": 1} if panic else {},
                "inputKey": input_key,
                "rowId": compose.canonical_cid({"inputKey": input_key}),
                "stageId": compose.STAGE_ENUMERATE_FILE_TERMINAL,
                "observedEventType": (
                    panic_payload["observedEventType"] if panic else "builtins.dict"
                ),
                "terminalKind": terminal_kind,
                "observed_chain_length": 1,
                "blocking_terminal_count": 1 if panic else 0,
                "final_terminal": terminal_kind,
                "edgeWitnesses": {
                    compose.EDGE_ENUMERATE_FILE: compose.key_edge_witness(
                        stage_id=compose.STAGE_ENUMERATE_FILE_TERMINAL,
                        input_keys=function_keys,
                        output_keys=function_keys,
                    ),
                    compose.EDGE_WITH_PARTITION: compose.key_edge_witness(
                        stage_id=compose.STAGE_WITH_TALLY_PARTITION,
                        input_keys=[],
                        output_keys=[],
                    ),
                },
                **({"panic": panic_payload} if panic else {}),
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


def test_authoritative_board_without_sealed_cids_panics() -> None:
    """The 18230 hole: SCOREBOARD_AUTHORITY + bare functionsTotal without seals."""
    forged = {
        "SCOREBOARD_AUTHORITY": True,
        "functionsTotal": 18230,
        "functionsEnumerated": 18230,
        "functionsUnaccounted": 0,
        "denominator": {
            "functions": {
                "total": 18230,
                "enumerated": 18230,
                "unaccounted": 0,
            }
        },
        # sealedFunctionFactCids omitted — second informal total
    }
    with pytest.raises(BFF.BoardFunctionFactError, match="sealedFunctionFactCids|one door"):
        BFF.require_sealed_board_function_fields(forged)


def test_authoritative_board_disagreeing_total_and_denom_panics() -> None:
    """Two producers of the same count cannot both land on one board."""
    pop, enum, clean = _mint_triple(population=27954, enumerated=18230, refused=True)
    fields = BFF.board_fields_from_sealed_facts(pop, enum, clean)
    body = {
        "SCOREBOARD_AUTHORITY": True,
        "functionsTotal": 18230,  # wrong — swapped meaning as bare int
        "functionsEnumerated": fields["functionsEnumerated"],
        "functionsUnaccounted": fields["functionsUnaccounted"],
        "denominator": {"functions": dict(fields["denominator_functions"])},
        "sealedFunctionFactCids": dict(fields["sealedFactCids"]),
    }
    with pytest.raises(BFF.BoardFunctionFactError, match="disagrees|one door"):
        BFF.require_sealed_board_function_fields(body)


def test_population_and_enumerated_cannot_be_the_same_informal_int() -> None:
    """18230 vs 27954: three meanings, three addresses — not one overloaded total."""
    pop, enum, clean = _mint_triple(
        population=27954, enumerated=18230, refused=True
    )
    fields = BFF.board_fields_from_sealed_facts(pop, enum, clean)
    assert fields["functionsTotal"] == 27954
    assert fields["functionsEnumerated"] == 18230
    assert fields["functionsUnaccounted"] == 27954 - 18230
    assert pop.fact_cid != enum.fact_cid
    body = {
        "SCOREBOARD_AUTHORITY": True,
        "functionsTotal": fields["functionsTotal"],
        "functionsEnumerated": fields["functionsEnumerated"],
        "functionsUnaccounted": fields["functionsUnaccounted"],
        "denominator": {"functions": dict(fields["denominator_functions"])},
        "sealedFunctionFactCids": dict(fields["sealedFactCids"]),
    }
    BFF.require_sealed_board_function_fields(body)  # does not panic
