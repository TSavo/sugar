"""A narrow expression-bodied lambda callable."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar, Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class LambdaSugar(ConstructedTermSugar):
    """Plain positional formals plus one already-constructed body expression."""

    formals: tuple[str, ...]
    body: Sugar
    source_call_frame: object
    formal_coordinate_cids: tuple[str, ...]
    body_fragment_cid: str
    site: object = dataclass_field(compare=False)

    def __post_init__(self) -> None:
        from sugar_source_tree.panic import SugarNotWritten

        frame = self.source_call_frame
        if tuple(frame.parameters) != self.formals:
            raise SugarNotWritten(
                owner="LambdaSugar.formals",
                blame=self.site,
                observed=(
                    f"frame.parameters={tuple(frame.parameters)!r} "
                    f"!= formals={self.formals!r}"
                ),
                requested="formals identical to the authenticated source_call_frame",
                fix=(
                    "construct LambdaSugar only from Lambda._construct_sugar with "
                    "the producer frame; do not invent formals"
                ),
            )
        if tuple(coordinate.cid for coordinate in frame.formal_coordinates) != (
            self.formal_coordinate_cids
        ):
            raise SugarNotWritten(
                owner="LambdaSugar.formal_coordinate_cids",
                blame=self.site,
                observed="formal_coordinate_cids disagree with frame.formal_coordinates",
                requested="producer-authenticated formal coordinate CID tuple",
                fix="carry coordinate CIDs from the source_visible_call_frame only",
            )
        if frame.definition_fragment_cid != self.site.seal().cid:
            raise SugarNotWritten(
                owner="LambdaSugar.source_call_frame",
                blame=self.site,
                observed=(
                    f"frame.definition_fragment_cid={frame.definition_fragment_cid!r} "
                    f"!= lambda site cid={self.site.seal().cid!r}"
                ),
                requested="source frame pinned to this exact lambda occurrence",
                fix="mint the frame at the Lambda node; do not reuse another definition",
            )
        if self.body.site.seal().cid != self.body_fragment_cid:
            raise SugarNotWritten(
                owner="LambdaSugar.body",
                blame=getattr(self.body, "site", self.site),
                observed=(
                    f"body site cid={self.body.site.seal().cid!r} "
                    f"!= body_fragment_cid={self.body_fragment_cid!r} "
                    f"(body type={type(self.body).__name__})"
                ),
                requested=(
                    "body sugar whose site.seal().cid equals the exact source "
                    "body fragment CID captured at construction"
                ),
                fix=(
                    "construct the body from the Lambda expression body node "
                    "before rewrite; a substituted/rewritten body with a different "
                    "fragment is an honest gap until rewrite preserves body "
                    "occurrence identity — refuse specifically, never TypeError"
                ),
            )

    @classmethod
    def witnesses(cls):
        prefix = "def A(v):\n    return (lambda x: x)(v)\n\n"
        return _call_pair(
            name="lambda_identity_call",
            owner_sugar="LambdaSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        from sugar_lift_py_tests.floor import LambdaCallable

        sealed = self.site.seal()
        construction_identity = (
            f"{sealed.source_cid}@{sealed.start}:{sealed.end}#{sealed.cid}"
        )
        return Complete(
            LambdaCallable(
                parameters=self.formals,
                body=self.body,
                construction_identity=construction_identity,
                source_call_frame=self.source_call_frame,
            )
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, num, str_const

        body_occurrence = self.body.site.seal()

        return ctor(
            "python:lambda-construction",
            (
                self.occurrence_term(owner=owner),
                ctor(
                    "python:lambda-formals",
                    tuple(
                        ctor(
                            "python:lambda-formal",
                            (str_const(name), str_const(coordinate_cid)),
                            symbol_kind="coordinate",
                        )
                        for name, coordinate_cid in zip(
                            self.formals, self.formal_coordinate_cids, strict=True
                        )
                    ),
                ),
                ctor(
                    "python:lambda-body",
                    (
                        str_const(body_occurrence.source_cid),
                        num(body_occurrence.start),
                        num(body_occurrence.end),
                        str_const(self.body_fragment_cid),
                    ),
                    symbol_kind="coordinate",
                ),
                str_const(self.source_call_frame.frame_cid),
            ),
            symbol_kind="coordinate",
        )
