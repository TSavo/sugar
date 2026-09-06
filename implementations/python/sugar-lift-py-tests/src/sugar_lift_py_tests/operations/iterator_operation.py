"""Synchronous iterator surface: ``__iter__`` / iterable → iterator Floor.

Route:

    IteratorOperation(...)
        → receiver.iter_with(operation, ctx)

Exact containers (list/tuple/…) answer with an authenticated iterator Floor.
Species without authority take the construction-gap default on FloorValue.
ObjectValue answers through ``__iter__`` data-model methods (real coordinates).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar


@dataclass(frozen=True)
class IteratorOperation:
    """One ``__iter__`` demand against one iterable receiver."""

    method_name: ClassVar[str] = "iter_with"

    owner: str
    blame: object

    @property
    def site(self) -> object:
        """The source locus of this demand (recorded under ``blame``).

        Consumers that reduce this operation over an undecided receiver -- an
        ImportMemberValue under an enrolled stdlib body -- read
        ``operation.site``. Sibling operations that lacked it raised
        AttributeError and voided the file (see SubscriptOperation.site).
        """
        return self.blame

    def submit(self, receiver: Any, ctx: Any = None) -> Any:
        """Ask the receiver for its iterator. The receiver owns the answer."""
        return receiver.iter_with(self, ctx)


def discharge_iter(receiver, site, *, owner: str = "project_iter"):
    """Production projector body: established ``iter_with`` floor edge."""
    return IteratorOperation(owner=owner, blame=site).submit(receiver, None)
