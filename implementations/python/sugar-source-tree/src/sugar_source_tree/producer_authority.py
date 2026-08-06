"""The NAMED minting capability a producer door holds.

A producer authority is a capability: holding it is what a mint door can prove
and a hand-assembled value cannot. Spelled ``object()`` it was a bare process
address -- it carried no content whatsoever, and it was not the same value
twice in two processes.

That is fine for a slot nothing ever reads. It is not fine for a slot that
rides on a value which reaches content-addressing. ``ConstructedValueV2`` walks
every dataclass field, met ``builtins.object`` at ``.contract_ref._authority``,
and refused the whole constructed value with ``ConstructedValueCategoryGap`` --
reporting a missing CATEGORY when the truth was a slot that HAD no content to
name. Two different faults wearing one refusal.

Naming the authority splits them. The capability still rides entirely on
IDENTITY: every check is ``is`` against the module-level singleton its producer
owns, and a value-equal forgery minted by a consumer does NOT pass. What the
name buys is the other half -- a content coordinate that is the same string in
every process -- so a value carrying its minting authority stays addressable
instead of collapsing the whole enclosing testimony into a category gap.

This adds no arm to ``_cv2_entries``. A frozen dataclass over one string is a
category that schema already names, which is the point: the repair is to give
the value a category it HAS, never to widen a category to swallow one it has
not. A bare ``object()`` in a constructed value still refuses, and must.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProducerAuthorityV1:
    """One producer's minting capability, held as a module-level singleton.

    Equality is by name, and that is deliberately NOT what gates a mint: the
    gate is ``is`` against the singleton. A forger can build an equal token and
    still not hold the capability, exactly as before. The name exists so the
    token can be SAID -- in a content CID, in a panic, in a receipt.
    """

    name: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError(
                "a producer authority must be NAMED: an unnamed capability "
                "cannot be said in a content coordinate, which is the whole "
                "reason it is not a bare object()"
            )
