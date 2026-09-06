"""Floor-owned iterable demand for list slice assignment RHS.

Python: ``xs[lo:hi] = iterable`` materializes the RHS once into a finite
member sequence before writing.  Exact containers answer with authenticated
members; decided non-iterables are TypeError; unresolved iterability stays
loud.  No ``getattr`` probe over value species.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar


@dataclass(frozen=True)
class SliceAssignIterableOperation:
    """One demand: materialize slice-assignment RHS members from a Floor value."""

    method_name: ClassVar[str] = "slice_assign_iterable_with"

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
        return receiver.slice_assign_iterable_with(self, ctx)
