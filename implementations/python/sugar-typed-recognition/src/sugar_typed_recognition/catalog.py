"""TypedCatalog: registry-based multiple dispatch over membrane types.

The shape
---------

::

    resolve(role, site)  ->  exactly one TypedClaim   |   RecognitionPanic

Two arms. Never three. ``resolve`` is the only entry point a builder should
call; ``candidates_for`` is exposed for tests and diagnostics and is not a
resolution.

The dispatch key
----------------

Recognition is where more than one type meets. The key is::

    (role, type(site), *operand_types(site))
     ^^^^  ^^^^^^^^^^   ^^^^^^^^^^^^^^^^^^^
     |     |            coordinates 1..n: interrogated by owns(), and
     |     |            available only because operands are already Typed
     |     coordinate 0: matched against claim.accepts by isinstance,
     |     BEFORE owns() is called
     which question is being asked

Each coordinate enters at a different place, and the places are not
interchangeable:

* **role** is matched on the claim's declaration. A cheap equality on an
  enum, not a string.
* **``type(site)``** is matched by ``isinstance(site, claim.accepts)`` in the
  pre-filter below. This is the coordinate that used to be spelled
  ``site.observed == "Call"`` inside every predicate, 403 times.
* **operand types** are interrogated by ``owns``, by ``isinstance`` on
  membrane classes. This is the coordinate a plain type switch cannot
  express, and therefore the reason the catalog exists rather than a
  ``match`` statement on the node class.

Why a type switch is not enough (the load-bearing argument)
-----------------------------------------------------------

If ``accepts`` were the whole key, this could all be a dict from node class
to claim, and the catalog would be a needless indirection. It is not the
whole key. ``AddOpClaim`` and ``MultiplyOpClaim`` and ``AnnotationUnionClaim``
all declare ``accepts = BinOp`` and are distinguished only by the type of
``site.op``; ``MethodCallClaim`` and ``PlainCallClaim`` both declare
``accepts = Call`` and are distinguished only by the type of ``site.func``.
Dispatch on more than one type at once, resolved by a registry rather than
by a receiver's vtable, is multiple dispatch. The catalog IS the dispatch
table.

Why recognition is bottom-up, and why that is forced rather than agreed
-----------------------------------------------------------------------

``owns`` may interrogate operand types only because operands arrive already
``Typed``. The membrane constructs bottom-up (``construct.py``: children
first, every parent built FROM finished children), so the ordering is a
consequence of the type discipline, not a rule recognition asks anyone to
follow. There is no phase to schedule and no traversal order to get wrong:
if you are holding a ``BinOp``, its ``left``, ``right`` and ``op`` are
already resolved, because you could not have been handed the ``BinOp``
otherwise.

``operand_types(site)`` is called before any ``owns``, so a child that
cannot answer its type panics as a MISSING rather than reaching a claim that
would have no vocabulary but ``False``.

No precedence, on purpose
-------------------------

Today's factory resolves overlap with a ``comes_before`` precedence walk
(``factory/build.py:_select_candidate``) and panics only when the walk fails
to produce a unique winner. This layer has no precedence walk. Overlap is
the defect itself: if two claims own the same (role, node type, operand
types) key, the catalog is not a function, and precedence would be a rule
for picking one of two answers to a question that should have had one.
Disjointness is achieved by making ``owns`` predicates disjoint — which the
typed layer makes cheap, because the operand type IS the discriminator.
``PlainCallClaim`` in ``claims.py`` is the worked example: it excludes the
builtin coordinate that ``LenCallClaim`` owns, rather than losing a
precedence contest to it.

See ``REPORT`` notes in the PR: this is the largest behavioral difference
from the design in #5940, and it is a deliberate narrowing.
"""

from __future__ import annotations

from typing import Iterable, Sequence, Tuple

from sugar_node_membrane.nodes import SourceFragment, Typed

from .claim import TypedClaim, operand_types
from .panic import RecognitionArm, recognition_panic
from .role import Role


class TypedCatalog:
    """An immutable set of claims plus the dispatch over them."""

    def __init__(self, claims: Iterable[type[TypedClaim]] = ()) -> None:
        self._claims: Tuple[type[TypedClaim], ...] = tuple(claims)
        for claim in self._claims:
            if not (isinstance(claim, type) and issubclass(claim, TypedClaim)):
                recognition_panic(
                    RecognitionArm.GAP,
                    owner="catalog.TypedCatalog",
                    observed=f"registered {claim!r}",
                    requested="a TypedClaim subclass",
                    fix="a claim is a class, registered by class, never an instance",
                )
            if getattr(claim, "accepts", None) is None:
                recognition_panic(
                    RecognitionArm.GAP,
                    owner="catalog.TypedCatalog",
                    observed=f"claim {claim.__name__} declares no accepts",
                    requested="accepts: type[SourceFragment]",
                    fix="every registered claim declares the node class it recognizes",
                )

    @property
    def claims(self) -> Tuple[type[TypedClaim], ...]:
        return self._claims

    # -- dispatch ---------------------------------------------------------

    def candidates_for(
        self, role: Role, site: SourceFragment
    ) -> Tuple[type[TypedClaim], ...]:
        """Every claim owning this site under this role. Diagnostics only.

        Not a resolution: a caller that acts on this tuple without going
        through ``resolve`` has reintroduced "pick the first".
        """
        self._require_typed_site(site)

        # Interrogating the operands is also the check that they CAN be
        # interrogated. Panics on a MISSING operand type before any owns().
        operand_types(site)

        return tuple(
            claim
            for claim in self._claims
            if claim.role is role
            # coordinate 0, by type, never by string
            and isinstance(site, claim.accepts)
            # coordinates 1..n, inside the claim, on already-Typed operands
            and claim.owns(site)
        )

    def resolve(self, role: Role, site: SourceFragment) -> type[TypedClaim]:
        """THE two-arm match: exactly one claim, or panic.

        ::

            match candidates:
                [one]  => one
                _      => panic
        """
        candidates = self.candidates_for(role, site)
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            self._panic_gap(role, site)
        self._panic_ambiguous(role, site, candidates)

    # -- the two loud arms ------------------------------------------------

    def _panic_gap(self, role: Role, site: SourceFragment) -> None:
        recognition_panic(
            RecognitionArm.GAP,
            owner="catalog.TypedCatalog.resolve",
            observed=(
                f"{_key_description(role, site)} — no claim owns this combination"
            ),
            requested=f"exactly one {role.value} claim",
            fix=(
                f"add a claim with accepts = {type(site).__name__} whose owns() "
                f"answers True for these operand types, or extend an existing "
                f"claim's owns() to cover them. Never widen a claim to swallow "
                f"a shape it does not mean."
            ),
        )

    def _panic_ambiguous(
        self,
        role: Role,
        site: SourceFragment,
        candidates: Sequence[type[TypedClaim]],
    ) -> None:
        names = ", ".join(claim.name() for claim in candidates)
        recognition_panic(
            RecognitionArm.AMBIGUOUS,
            owner="catalog.TypedCatalog.resolve",
            observed=(
                f"{_key_description(role, site)} — {len(candidates)} claims own "
                f"this combination: [{names}]"
            ),
            requested=f"exactly one {role.value} claim",
            fix=(
                "two claims own one dispatch key, so the catalog is not a "
                "function and no answer it gives is defensible. Make the owns() "
                "predicates disjoint — typically by having one of them exclude "
                "the operand type the other exists for. There is no precedence "
                "mechanism here and picking the first is not available: that "
                "would be a third arm."
            ),
        )

    # -- guards -----------------------------------------------------------

    @staticmethod
    def _require_typed_site(site: SourceFragment) -> None:
        if isinstance(site, SourceFragment) and isinstance(site, Typed):
            site.resolve_type()  # panics if abstract; two arms all the way down
            return
        recognition_panic(
            RecognitionArm.MISSING_OPERAND_TYPE,
            owner="catalog.TypedCatalog",
            observed=f"site is {type(site).__name__}",
            requested="a Typed membrane node",
            fix=(
                "recognition dispatches on membrane classes. A site that is not "
                "a constructed membrane node never had a type to dispatch on."
            ),
        )


def _key_description(role: Role, site: SourceFragment) -> str:
    operands = ", ".join(t.__name__ for t in operand_types(site))
    return (
        f"role={role.value} site={type(site).__name__} "
        f"operands=({operands}) at [{site.span.start},{site.span.end})"
    )
