"""Three sealed board function meanings — C4 Step 1 (topology only).

The board already proved the split is real: population 28264, enumerated 27954,
clean refused. Those are THREE facts that lived under one informal name and
nearly sealed as one number.

Sealed meanings (types, not registry ids):

  FunctionsPopulationV1  — authenticated AST count over the pin
  FunctionsEnumeratedV1  — what the sole construction door actually rostered
  FunctionsCleanV1       — measured or absent, never defaulted

Each carries its own body and content address. Consumers take the type, not an
int. Enforcement lives at the compose consumer (``board_fields_from_sealed_facts``),
not producer privacy — Python cannot give unrepresentable construction.

Law (verbatim, Orange / T):

  Enrollment makes dual production of THIS SEALED MEANING unsealable. Meaning is
  fixed by type fields plus witness or twin. SOLE CONSTRUCTOR IS NOT EVIDENCE THE
  MEANING IS RIGHT.

Correct-by-construction of PRODUCTION TOPOLOGY is not correct-by-construction of
DENOMINATORS. C1 and C2 remain the truth instruments.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

# Per-meaning seal tokens. A second producer cannot mint the sealed type without
# the private token of the sole door module. That is Python-honest sole-ness, not
# rustc unrepresentability (Attack 3).
_POPULATION_SEAL = object()
_ENUMERATED_SEAL = object()
_CLEAN_SEAL = object()

AXIS_POPULATION = "FunctionsPopulationV1"
AXIS_ENUMERATED = "FunctionsEnumeratedV1"
AXIS_CLEAN = "FunctionsCleanV1"
UNIT = "construction-function-locus"


class BoardFunctionFactError(TypeError, ValueError):
    """Bare int / LocalReading / wrong type refused at a sealed meaning door."""


def _blake3_512(data: bytes) -> str:
    try:
        import blake3  # type: ignore

        return "blake3-512:" + blake3.blake3(data, max_threads=1).digest(64).hex()
    except Exception:  # noqa: BLE001
        return "sha256:" + hashlib.sha256(data).hexdigest()


def _fact_cid(
    *,
    tip: str,
    pin: str,
    axis: str,
    body: Mapping[str, Any],
    witness: str,
) -> str:
    """Content address of a sealed fact: h(tip, pin, axis, body, witness)."""
    payload = {
        "tip": tip,
        "pin": pin,
        "axis": axis,
        "body": dict(body),
        "witness": witness,
    }
    rendered = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return _blake3_512(rendered.encode("utf-8"))


def _require_nonempty_str(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BoardFunctionFactError(
            f"{name} must be a non-empty str (got {type(value).__name__!r}={value!r}); "
            f"a sealed meaning without tip/pin has no identity"
        )
    return value.strip()


def _require_int_ge0(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BoardFunctionFactError(
            f"{name} must be a non-negative int (got {type(value).__name__})"
        )
    if value < 0:
        raise BoardFunctionFactError(f"{name} must be >= 0 (got {value})")
    return value


# ---------------------------------------------------------------------------
# LocalReading — any compute site; not a seal; cannot enter compose
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LocalReading:
    """A local measurement any module may hold. Not authoritative. Cannot seal.

    Workers, shards, and scratch counters mint these freely. Only a sole seal
    door upgrades a LocalReading into a sealed meaning type. Compose never
    accepts a LocalReading as a board field.
    """

    value: int | None
    label: str
    source: str = "local"

    def is_sealed(self) -> bool:
        return False


# ---------------------------------------------------------------------------
# Three sealed meanings — distinct types, distinct content addresses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FunctionsPopulationV1:
    """Authenticated AST count over the pin — the population denominator.

    Not enumerated roster mass. Not clean residual. C1 owns whether the count
    is true; C4 owns that only one seal path can mint this meaning.
    """

    tip: str
    pin: str
    count: int
    unit: str
    witness: str
    fact_cid: str
    _seal: object

    def __post_init__(self) -> None:
        if self._seal is not _POPULATION_SEAL:
            raise BoardFunctionFactError(
                "FunctionsPopulationV1 is sealed: use seal_functions_population_v1(...); "
                "a bare int, LocalReading, or second-producer forge has no constructor "
                "for this sealed meaning. Enrollment makes dual production of THIS "
                "SEALED MEANING unsealable. SOLE CONSTRUCTOR IS NOT EVIDENCE THE "
                "MEANING IS RIGHT."
            )
        object.__setattr__(self, "tip", _require_nonempty_str("tip", self.tip))
        object.__setattr__(self, "pin", _require_nonempty_str("pin", self.pin))
        object.__setattr__(
            self, "count", _require_int_ge0("count", self.count)
        )
        object.__setattr__(
            self, "unit", _require_nonempty_str("unit", self.unit)
        )
        object.__setattr__(
            self, "witness", _require_nonempty_str("witness", self.witness)
        )
        object.__setattr__(
            self, "fact_cid", _require_nonempty_str("fact_cid", self.fact_cid)
        )

    def is_sealed(self) -> bool:
        return True

    def body(self) -> dict[str, Any]:
        return {"count": self.count, "unit": self.unit}


@dataclass(frozen=True, slots=True)
class FunctionsEnumeratedV1:
    """What the sole construction door actually rostered (enumerate mementos).

    Distinct from population. unaccounted = population - enumerated is derived
    at compose from the two sealed facts; it is not a third informal int.
    """

    tip: str
    pin: str
    count: int
    unit: str
    witness: str
    fact_cid: str
    _seal: object

    def __post_init__(self) -> None:
        if self._seal is not _ENUMERATED_SEAL:
            raise BoardFunctionFactError(
                "FunctionsEnumeratedV1 is sealed: use seal_functions_enumerated_v1(...); "
                "a bare int, LocalReading, or second-producer forge has no constructor "
                "for this sealed meaning. Enrollment makes dual production of THIS "
                "SEALED MEANING unsealable. SOLE CONSTRUCTOR IS NOT EVIDENCE THE "
                "MEANING IS RIGHT."
            )
        object.__setattr__(self, "tip", _require_nonempty_str("tip", self.tip))
        object.__setattr__(self, "pin", _require_nonempty_str("pin", self.pin))
        object.__setattr__(
            self, "count", _require_int_ge0("count", self.count)
        )
        object.__setattr__(
            self, "unit", _require_nonempty_str("unit", self.unit)
        )
        object.__setattr__(
            self, "witness", _require_nonempty_str("witness", self.witness)
        )
        object.__setattr__(
            self, "fact_cid", _require_nonempty_str("fact_cid", self.fact_cid)
        )

    def is_sealed(self) -> bool:
        return True

    def body(self) -> dict[str, Any]:
        return {"count": self.count, "unit": self.unit}


@dataclass(frozen=True, slots=True)
class FunctionsCleanV1:
    """Measured clean count or absent — never defaulted to zero.

    When any file refuses clean measurement, ``refused`` is True and ``count``
    is None. A bare 0 is not a lawful stand-in for refusal (tautological clean%
    lie). Meaning is fixed by the refused/measured body shape.
    """

    tip: str
    pin: str
    count: int | None
    refused: bool
    refuse_reason: str | None
    unit: str
    witness: str
    fact_cid: str
    _seal: object

    def __post_init__(self) -> None:
        if self._seal is not _CLEAN_SEAL:
            raise BoardFunctionFactError(
                "FunctionsCleanV1 is sealed: use seal_functions_clean_v1(...); "
                "a bare int, LocalReading, or second-producer forge has no constructor "
                "for this sealed meaning. Enrollment makes dual production of THIS "
                "SEALED MEANING unsealable. SOLE CONSTRUCTOR IS NOT EVIDENCE THE "
                "MEANING IS RIGHT."
            )
        object.__setattr__(self, "tip", _require_nonempty_str("tip", self.tip))
        object.__setattr__(self, "pin", _require_nonempty_str("pin", self.pin))
        object.__setattr__(
            self, "unit", _require_nonempty_str("unit", self.unit)
        )
        object.__setattr__(
            self, "witness", _require_nonempty_str("witness", self.witness)
        )
        object.__setattr__(
            self, "fact_cid", _require_nonempty_str("fact_cid", self.fact_cid)
        )
        if self.refused:
            if self.count is not None:
                raise BoardFunctionFactError(
                    "FunctionsCleanV1 refused body forbids a count "
                    f"(got count={self.count!r}); measured-or-absent, never both"
                )
            if not self.refuse_reason or not str(self.refuse_reason).strip():
                raise BoardFunctionFactError(
                    "FunctionsCleanV1 refused body requires a non-empty refuse_reason"
                )
        else:
            if self.count is None:
                raise BoardFunctionFactError(
                    "FunctionsCleanV1 measured body requires a non-negative count; "
                    "absent clean must set refused=True (never default count to 0)"
                )
            object.__setattr__(
                self, "count", _require_int_ge0("count", self.count)
            )
            if self.refuse_reason is not None:
                raise BoardFunctionFactError(
                    "FunctionsCleanV1 measured body forbids refuse_reason"
                )

    def is_sealed(self) -> bool:
        return True

    def body(self) -> dict[str, Any]:
        if self.refused:
            return {
                "count": None,
                "refused": True,
                "refuseReason": self.refuse_reason,
                "unit": self.unit,
            }
        return {
            "count": self.count,
            "refused": False,
            "unit": self.unit,
        }


# ---------------------------------------------------------------------------
# Sole seal doors — one module, one function per sealed meaning
# ---------------------------------------------------------------------------


def seal_functions_population_v1(
    reading: LocalReading,
    *,
    tip: str,
    pin: str,
    witness: str = "compose-aggregate/functions_total",
) -> FunctionsPopulationV1:
    """Sole mint door for FunctionsPopulationV1. Accepts LocalReading only."""
    if not isinstance(reading, LocalReading):
        raise BoardFunctionFactError(
            "seal_functions_population_v1 accepts LocalReading only "
            f"(got {type(reading).__name__}); bare int is not a reading and "
            "cannot upgrade to a sealed meaning"
        )
    if reading.value is None:
        raise BoardFunctionFactError(
            "FunctionsPopulationV1 refuses LocalReading with value=None; "
            "population is an authenticated count, never absent"
        )
    count = _require_int_ge0("population", reading.value)
    tip_s = _require_nonempty_str("tip", tip)
    pin_s = _require_nonempty_str("pin", pin)
    wit = _require_nonempty_str("witness", witness)
    body = {"count": count, "unit": UNIT}
    cid = _fact_cid(
        tip=tip_s, pin=pin_s, axis=AXIS_POPULATION, body=body, witness=wit
    )
    return FunctionsPopulationV1(
        tip=tip_s,
        pin=pin_s,
        count=count,
        unit=UNIT,
        witness=wit,
        fact_cid=cid,
        _seal=_POPULATION_SEAL,
    )


def seal_functions_enumerated_v1(
    reading: LocalReading,
    *,
    tip: str,
    pin: str,
    witness: str = "compose-aggregate/functions_enumerated",
) -> FunctionsEnumeratedV1:
    """Sole mint door for FunctionsEnumeratedV1. Accepts LocalReading only."""
    if not isinstance(reading, LocalReading):
        raise BoardFunctionFactError(
            "seal_functions_enumerated_v1 accepts LocalReading only "
            f"(got {type(reading).__name__}); bare int is not a reading and "
            "cannot upgrade to a sealed meaning"
        )
    if reading.value is None:
        raise BoardFunctionFactError(
            "FunctionsEnumeratedV1 refuses LocalReading with value=None; "
            "enumerated is a rostered count (may be 0), never absent"
        )
    count = _require_int_ge0("enumerated", reading.value)
    tip_s = _require_nonempty_str("tip", tip)
    pin_s = _require_nonempty_str("pin", pin)
    wit = _require_nonempty_str("witness", witness)
    body = {"count": count, "unit": UNIT}
    cid = _fact_cid(
        tip=tip_s, pin=pin_s, axis=AXIS_ENUMERATED, body=body, witness=wit
    )
    return FunctionsEnumeratedV1(
        tip=tip_s,
        pin=pin_s,
        count=count,
        unit=UNIT,
        witness=wit,
        fact_cid=cid,
        _seal=_ENUMERATED_SEAL,
    )


def seal_functions_clean_v1(
    reading: LocalReading,
    *,
    tip: str,
    pin: str,
    refused: bool = False,
    refuse_reason: str | None = None,
    witness: str = "compose-aggregate/functions_clean",
) -> FunctionsCleanV1:
    """Sole mint door for FunctionsCleanV1. Measured or refused — never defaulted."""
    if not isinstance(reading, LocalReading):
        raise BoardFunctionFactError(
            "seal_functions_clean_v1 accepts LocalReading only "
            f"(got {type(reading).__name__}); bare int is not a reading and "
            "cannot upgrade to a sealed meaning"
        )
    tip_s = _require_nonempty_str("tip", tip)
    pin_s = _require_nonempty_str("pin", pin)
    wit = _require_nonempty_str("witness", witness)
    if refused:
        count: int | None = None
        reason = refuse_reason or (
            "one or more files refused functionsClean "
            "(would be tautological clean%)"
        )
        body = {
            "count": None,
            "refused": True,
            "refuseReason": reason,
            "unit": UNIT,
        }
    else:
        if reading.value is None:
            raise BoardFunctionFactError(
                "FunctionsCleanV1 measured path requires a non-None LocalReading.value; "
                "absent clean must set refused=True (never default count to 0)"
            )
        count = _require_int_ge0("clean", reading.value)
        reason = None
        body = {"count": count, "refused": False, "unit": UNIT}
    cid = _fact_cid(
        tip=tip_s, pin=pin_s, axis=AXIS_CLEAN, body=body, witness=wit
    )
    return FunctionsCleanV1(
        tip=tip_s,
        pin=pin_s,
        count=count,
        refused=refused,
        refuse_reason=reason,
        unit=UNIT,
        witness=wit,
        fact_cid=cid,
        _seal=_CLEAN_SEAL,
    )


# ---------------------------------------------------------------------------
# Consumer close — compose enforcement point (not producer privacy)
# ---------------------------------------------------------------------------


def board_fields_from_sealed_facts(
    population: FunctionsPopulationV1,
    enumerated: FunctionsEnumeratedV1,
    clean: FunctionsCleanV1,
) -> dict[str, Any]:
    """Sole path from sealed meanings to board function fields.

    Refuse bare int, LocalReading, wrong type, or a second-producer forge.
    Returns flat + denominator.functions fragments for the sealed board body.

    This is the enforcement point: a bare int cannot become a board field.
    """
    if isinstance(population, int) or not isinstance(
        population, FunctionsPopulationV1
    ):
        raise BoardFunctionFactError(
            "board_fields_from_sealed_facts refuses non-FunctionsPopulationV1 for "
            f"population (got {type(population).__name__}); a bare int or "
            "LocalReading cannot become a board field. Close the consumer: "
            "compose accepts only the sealed meaning type."
        )
    if isinstance(enumerated, int) or not isinstance(
        enumerated, FunctionsEnumeratedV1
    ):
        raise BoardFunctionFactError(
            "board_fields_from_sealed_facts refuses non-FunctionsEnumeratedV1 for "
            f"enumerated (got {type(enumerated).__name__}); a bare int or "
            "LocalReading cannot become a board field. Close the consumer: "
            "compose accepts only the sealed meaning type."
        )
    if isinstance(clean, int) or not isinstance(clean, FunctionsCleanV1):
        raise BoardFunctionFactError(
            "board_fields_from_sealed_facts refuses non-FunctionsCleanV1 for "
            f"clean (got {type(clean).__name__}); a bare int or LocalReading "
            "cannot become a board field. Close the consumer: compose accepts "
            "only the sealed meaning type."
        )
    if not population.is_sealed() or not enumerated.is_sealed() or not clean.is_sealed():
        raise BoardFunctionFactError(
            "board_fields_from_sealed_facts requires sealed facts "
            f"(population.sealed={population.is_sealed()}, "
            f"enumerated.sealed={enumerated.is_sealed()}, "
            f"clean.sealed={clean.is_sealed()})"
        )
    # Tip/pin must agree — three facts about one board observation.
    if not (population.tip == enumerated.tip == clean.tip):
        raise BoardFunctionFactError(
            "board_fields_from_sealed_facts refuses tip mismatch across the three "
            f"sealed meanings: pop={population.tip!r} enum={enumerated.tip!r} "
            f"clean={clean.tip!r}"
        )
    if not (population.pin == enumerated.pin == clean.pin):
        raise BoardFunctionFactError(
            "board_fields_from_sealed_facts refuses pin mismatch across the three "
            f"sealed meanings: pop={population.pin!r} enum={enumerated.pin!r} "
            f"clean={clean.pin!r}"
        )

    unaccounted = max(0, population.count - enumerated.count)
    denom_functions: dict[str, Any] = {
        "total": population.count,
        "enumerated": enumerated.count,
        "unaccounted": unaccounted,
        "unit": UNIT,
        "factCids": {
            "population": population.fact_cid,
            "enumerated": enumerated.fact_cid,
            "clean": clean.fact_cid,
        },
    }
    if clean.refused:
        denom_functions["clean"] = None
        denom_functions["cleanRatioRefused"] = True
        denom_functions["cleanRefuseReason"] = clean.refuse_reason
        construct_clean: int | None = None
        clean_ratio_refused = True
    else:
        denom_functions["clean"] = clean.count
        denom_functions["cleanRatioRefused"] = False
        construct_clean = clean.count
        clean_ratio_refused = False

    return {
        "functionsTotal": population.count,
        "functionsEnumerated": enumerated.count,
        "functionsUnaccounted": unaccounted,
        "functionsConstructClean": construct_clean,
        "cleanRatioRefused": clean_ratio_refused,
        "denominator_functions": denom_functions,
        "sealedFactCids": {
            "FunctionsPopulationV1": population.fact_cid,
            "FunctionsEnumeratedV1": enumerated.fact_cid,
            "FunctionsCleanV1": clean.fact_cid,
        },
    }


def require_sealed_board_function_fields(body: Mapping[str, Any]) -> None:
    """Panic if an authoritative board carries function counts without the one door.

    SCOREBOARD_AUTHORITY boards must land function totals only via
    ``board_fields_from_sealed_facts``. A body with bare ``functionsTotal`` and
    no three sealed fact CIDs is the 18230-vs-27954 hole: two sites computed
    "how many functions" as ints and the board picked one. Construct the sealed
    facts, or panic — never a second informal total.
    """
    if not body.get("SCOREBOARD_AUTHORITY"):
        return
    cids = body.get("sealedFunctionFactCids")
    required = {
        AXIS_POPULATION,
        AXIS_ENUMERATED,
        AXIS_CLEAN,
    }
    if not isinstance(cids, dict) or set(cids.keys()) != required:
        raise BoardFunctionFactError(
            "authoritative board missing sealedFunctionFactCids for the three "
            f"function meanings (need {sorted(required)}, got {cids!r}); "
            "function counts reach the board only through "
            "board_fields_from_sealed_facts — a bare int is not a seal"
        )
    for axis, cid in cids.items():
        if not isinstance(cid, str) or not cid.strip():
            raise BoardFunctionFactError(
                f"sealedFunctionFactCids[{axis!r}] must be a non-empty content "
                f"address (got {cid!r})"
            )
    denom = (body.get("denominator") or {}).get("functions") or {}
    if not isinstance(denom, dict):
        raise BoardFunctionFactError(
            "authoritative board denominator.functions must come from the sealed "
            "door (missing or wrong type)"
        )
    if body.get("functionsTotal") != denom.get("total"):
        raise BoardFunctionFactError(
            "authoritative board functionsTotal disagrees with "
            f"denominator.functions.total "
            f"({body.get('functionsTotal')!r} vs {denom.get('total')!r}); "
            "two producers of the same count cannot both land — one door only"
        )
    if body.get("functionsEnumerated") != denom.get("enumerated"):
        raise BoardFunctionFactError(
            "authoritative board functionsEnumerated disagrees with "
            f"denominator.functions.enumerated "
            f"({body.get('functionsEnumerated')!r} vs {denom.get('enumerated')!r}); "
            "one door only"
        )
    if body.get("functionsUnaccounted") != denom.get("unaccounted"):
        raise BoardFunctionFactError(
            "authoritative board functionsUnaccounted disagrees with "
            f"denominator.functions.unaccounted "
            f"({body.get('functionsUnaccounted')!r} vs {denom.get('unaccounted')!r}); "
            "unaccounted is derived at the seal door, not a third informal int"
        )
