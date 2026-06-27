from __future__ import annotations

from .complete import Complete
from .incomplete import Incomplete

Outcome = Complete | Incomplete
