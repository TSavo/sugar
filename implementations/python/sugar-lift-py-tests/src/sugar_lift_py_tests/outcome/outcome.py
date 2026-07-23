from __future__ import annotations

from .complete import Complete
from .incomplete import Incomplete
from .exit_set import ExitSet
from sugar_lift_py_tests.caller_parameter_contract import (
    ContractConditionalConstructionV1,
)

Outcome = Complete | Incomplete | ExitSet | ContractConditionalConstructionV1
