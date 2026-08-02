"""C4 — production topology of seal authority (not denominator truth).

Correct-by-construction of PRODUCTION TOPOLOGY is not correct-by-construction
of DENOMINATORS. C4 green means no second seal path for this fact class. It
never means the board is true. C1 and C2 remain the truth instruments.

Enrollment makes dual production of THIS SEALED MEANING unsealable. Meaning is
fixed by type fields plus witness or twin. SOLE CONSTRUCTOR IS NOT EVIDENCE THE
MEANING IS RIGHT.
"""

from __future__ import annotations

from .board_function_facts import (
    BoardFunctionFactError,
    FunctionsCleanV1,
    FunctionsEnumeratedV1,
    FunctionsPopulationV1,
    LocalReading,
    board_fields_from_sealed_facts,
    require_sealed_board_function_fields,
    seal_functions_clean_v1,
    seal_functions_enumerated_v1,
    seal_functions_population_v1,
)

__all__ = [
    "BoardFunctionFactError",
    "FunctionsCleanV1",
    "FunctionsEnumeratedV1",
    "FunctionsPopulationV1",
    "LocalReading",
    "board_fields_from_sealed_facts",
    "require_sealed_board_function_fields",
    "seal_functions_clean_v1",
    "seal_functions_enumerated_v1",
    "seal_functions_population_v1",
]
