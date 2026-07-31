from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.sugar.sugar_base import (
    ConstructedTermSugar,
    require_constructed_term_sugar,
)


@dataclass(frozen=True)
class ReceiverMutationPostStateSugar(ConstructedTermSugar):
    """Project receiver-after from an authenticated shadow mutation.

    The wrapped mutation still owns evaluation and its contribution.  This
    projection is used only for the temporal receiver binding created by the
    shadow AST; it never changes the operation's real Python result.
    """

    mutation: ConstructedTermSugar
    site: object = field(compare=False)

    def __post_init__(self):
        require_constructed_term_sugar(
            self.mutation, owner="ReceiverMutationPostStateSugar.mutation"
        )

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        return self.mutation.desugar(ctx).and_then(
            lambda mutation: mutation.project_receiver_post_state(
                ctx,
                owner="ReceiverMutationPostStateSugar",
                blame=self.site,
            )
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        return ctor(
            "python:receiver-mutation-post-state",
            (self.occurrence_term(owner=owner), self.mutation.to_term(owner=owner)),
            symbol_kind="coordinate",
        )
