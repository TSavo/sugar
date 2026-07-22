from __future__ import annotations

from .complete import Complete
from .incomplete import Incomplete
from .exit_set import ExitSet

Outcome = Complete | Incomplete | ExitSet
