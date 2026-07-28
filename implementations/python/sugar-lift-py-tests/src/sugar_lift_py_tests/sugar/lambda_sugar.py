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
        frame = self.source_call_frame
        if tuple(frame.parameters) != self.formals:
            raise TypeError("LambdaSugar formals require their authenticated source frame")
        if tuple(coordinate.cid for coordinate in frame.formal_coordinates) != (
            self.formal_coordinate_cids
        ):
            raise TypeError(
                "LambdaSugar formal coordinates require producer-authenticated testimony"
            )
        if frame.definition_fragment_cid != self.site.seal().cid:
            raise TypeError("LambdaSugar source frame requires its exact lambda occurrence")
        if self.body.site.seal().cid != self.body_fragment_cid:
            raise TypeError("LambdaSugar body requires its exact source body testimony")

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
