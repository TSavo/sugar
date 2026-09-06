"""Synchronous iterator surface: ``__next__`` → value or named StopIteration.

Route:

    NextOperation(...)
        → receiver.next_with(operation, ctx)

Exact iterators yield ``NextResult(value, advanced)`` or a named StopIteration
face. Other exceptional faces stay distinct. Missing authority is the
construction-gap default on FloorValue.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar


@dataclass(frozen=True)
class NextOperation:
    """One ``__next__`` demand against one iterator receiver."""

    method_name: ClassVar[str] = "next_with"

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
        """Ask the iterator for the next value. The iterator owns the answer."""
        return receiver.next_with(self, ctx)


def discharge_next(receiver, site, *, owner: str = "project_next"):
    """Production projector body: established ``next_with`` floor edge."""
    return NextOperation(owner=owner, blame=site).submit(receiver, None)
