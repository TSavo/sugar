from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .raise_effect import RaiseEffect


@dataclass(frozen=True)
class NameErrorEffect(RaiseEffect):
    """Deterministic Python halt caused by an unbound source name."""

    name: str = ""
    site: object = field(default=None, compare=False)

    def __post_init__(self) -> None:
        locus = f"{self.site.filename}:{self.site.line}:{self.site.col}"
        source = getattr(getattr(self.site, "unit", None), "source", None)
        object.__setattr__(self, "exception_name", "NameError")
        object.__setattr__(self, "blame", locus)
        object.__setattr__(
            self,
            "source_sha256",
            (
                hashlib.sha256(source.encode()).hexdigest()
                if isinstance(source, str)
                else None
            ),
        )
        object.__setattr__(self, "occurrence", locus)

    @property
    def reason(self) -> str:
        return f"NameError for unbound name {self.name!r} at {self.blame}"
