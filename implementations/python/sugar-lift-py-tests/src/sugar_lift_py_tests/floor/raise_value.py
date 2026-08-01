from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from sugar_lift_py_tests.effect import RaiseEffect

from .exception_value import ExceptionValue
from .exception_cause_value import ExceptionCauseValue
from .floor_value import FloorValue


# Placeholder strings that invent exceptional-exit meaning outside the tree.
# Identity/citation must come from Sugar/the tree — never these spellings.
# Retirement: when exception_name is a closed typed constructor that can only
# be built from tree/Sugar testimony (not bare str), delete this denylist.
FABRICATED_EXCEPTIONAL_EXIT_MEANING_LITERALS = frozenset(
    {
        "reraise",
        "unavailable",
        "<unknown raise locus>",
    }
)


@dataclass(frozen=True)
class RaiseValue(FloorValue):
    """A Python raise exit carried by a block frontier.

    This is control-flow data, not an `Incomplete`: a `TrySugar` may route it through
    a matching handler before universe lowering decides what residual effects remain.
    """

    effect: RaiseEffect
    scope: object = None
    exception: ExceptionValue | None = None
    cause: ExceptionCauseValue | None = None

    def follow_rest(self):
        # Code after an unguarded raise never runs and is not part of the
        # block record (unreachable). Drop it — same posture as a hard exit.
        from sugar_lift_py_tests.outcome.follow_step import FollowStep

        return FollowStep.halt(keeps_rest=False)

    def truth(self, site):
        # A raise is not a Python boolean. Expression evaluation already halted
        # with the exceptional exit; demanding truthiness of the raise terminal
        # is a force-floor stage bug (owner=truth, observed=RaiseValue). Re-emit
        # the effect so `if <expr-that-raises>:` propagates rather than panics.
        del site
        from sugar_lift_py_tests.outcome import Incomplete

        return Incomplete(self.effect)

    def guarded(self, formula):
        from sugar_lift_py_tests.floor.guarded_raise import GuardedRaise

        return GuardedRaise(
            guards=(formula,),
            effect=self.effect,
            scope=self.scope,
            cause=self.cause,
        )

    def post_contribution(self):
        return (_exceptional_exit_formula(self.effect),)


def _refuse_uncited_exit(
    effect: RaiseEffect, *, observed: str, requested: str, fix: str
) -> NoReturn:
    """Render-edge mouth: absent evidence is a named throw, never a placeholder.

    Blame for the panic is the effect's own locus when present — never a
    second-mechanism literal standing in for missing tree testimony.
    """
    from sugar_lift_py_tests.gap.panic import construction_panic_gap

    if effect.blame is not None:
        blame: object = effect.blame
    elif effect.occurrence is not None:
        blame = effect.occurrence
    else:
        # No locus on the face: the gap's observed prose is the coordinate.
        blame = observed
    construction_panic_gap(
        owner="RaiseValue.exceptional_exit_term",
        blame=blame,
        observed=observed,
        requested=requested,
        fix=fix,
    )


def _require_authenticated_exceptional_exit_citation(effect: RaiseEffect) -> None:
    """A face with no authenticated identity must never reach FOL emission.

    Throwing is honorable: it means identity or citation evidence is not yet
    on the effect. Fabricating ``"reraise"``, ``"unavailable"``, or
    ``"<unknown raise locus>"`` would mint a citable exit indistinguishable
    from a genuinely authenticated one — the number the project is judged on.

    Legitimate bare ``raise`` re-raise re-emits the in-flight effect's real
    tree-derived identity (see ``RaiseSugar.desugar``); it does not mint the
    string ``"reraise"`` at this edge.

    A face whose ``exception_name`` *is* a fabricated placeholder string is
    the same sin relocated onto the field: refuse it. Empty spelling is not
    tree identity either.
    """
    if effect.exception_name is not None:
        if effect.exception_name == "":
            _refuse_uncited_exit(
                effect,
                observed="raise face exception_name is empty string",
                requested=(
                    "a non-empty tree-derived exception spelling, or a type "
                    "coordinate with exception_name left unset"
                ),
                fix=(
                    "do not mint empty identity; thread the exception name from "
                    "Sugar or leave name unset and use exception_type_coordinate"
                ),
            )
        if effect.exception_name in FABRICATED_EXCEPTIONAL_EXIT_MEANING_LITERALS:
            _refuse_uncited_exit(
                effect,
                observed=(
                    f"raise face exception_name is fabricated placeholder "
                    f"{effect.exception_name!r}"
                ),
                requested=(
                    "a tree-derived exception identity (real class spelling or "
                    "type coordinate), never a render-edge placeholder string"
                ),
                fix=(
                    "do not set exception_name to a fabricated placeholder; bare "
                    "re-raise re-emits the in-flight effect's real identity"
                ),
            )

    has_identity = (
        effect.exception_name is not None
        or effect.exception_type_coordinate is not None
    )
    if not has_identity:
        _refuse_uncited_exit(
            effect,
            observed=(
                "raise face has neither exception_name nor "
                "exception_type_coordinate"
            ),
            requested=(
                "an authenticated exception identity (name or type coordinate) "
                "derived from the tree"
            ),
            fix=(
                "do not fabricate 'reraise'; keep the nameless face loud until "
                "identity is authenticated (bare re-raise re-emits the in-flight "
                "effect)"
            ),
        )
    if effect.blame is None:
        _refuse_uncited_exit(
            effect,
            observed="raise face has no blame locus for exceptional-exit citation",
            requested="a source-derived blame coordinate on the RaiseEffect",
            fix=(
                "do not fabricate '<unknown raise locus>'; thread the construction "
                "locus that owns the raise"
            ),
        )
    if effect.source_sha256 is None:
        _refuse_uncited_exit(
            effect,
            observed="raise face has no source_sha256 for exceptional-exit citation",
            requested="the sha256 of the source text the raise lives in",
            fix=(
                "do not fabricate '#source-sha256=unavailable'; cite only when "
                "the unit text hash is present"
            ),
        )


def _exceptional_exit_formula(effect: RaiseEffect, guards: tuple = ()):
    # Identity and citation are enforced at the term edge. Explicit
    # ``raise Exc(...)`` keeps its constructed name; type-coordinate-only
    # faces pass ``None`` so the term uses the coordinate. Nameless faces
    # never reach emission (see ``_require_authenticated_exceptional_exit_citation``).
    exception_name = effect.exception_name

    from sugar_lift_py_tests.ir import and_, eq, implies, make_var

    exit_formula = eq(
        make_var("out"),
        _exceptional_exit_term(effect, exception_name=exception_name),
    )
    if not guards:
        return exit_formula
    guard = guards[0] if len(guards) == 1 else and_(list(guards))
    return implies(guard, exit_formula)


def _exceptional_exit_term(effect: RaiseEffect, *, exception_name: str | None = None):
    """Project the one source-cited term shared by raise posts and selections.

    Requires authenticated identity and citation evidence. Never substitutes
    placeholder strings for absent fields.
    """
    _require_authenticated_exceptional_exit_citation(effect)

    from sugar_lift_py_tests.ir import ctor, str_const

    resolved_name = (
        exception_name if exception_name is not None else effect.exception_name
    )
    # Kwarg override can still smuggle a fabricated spelling after the face
    # check; refuse it at the same mouth.
    if resolved_name is not None and (
        resolved_name == ""
        or resolved_name in FABRICATED_EXCEPTIONAL_EXIT_MEANING_LITERALS
    ):
        _refuse_uncited_exit(
            effect,
            observed=(
                f"exceptional-exit term resolved_name is fabricated or empty "
                f"{resolved_name!r}"
            ),
            requested="tree-derived exception spelling or type-coordinate path",
            fix="do not pass a fabricated placeholder as exception_name kwarg",
        )
    if effect.exception_type_coordinate is not None and resolved_name is None:
        name_term = effect.exception_type_coordinate
    else:
        if resolved_name is None:
            # Identity check already required name or coordinate; coordinate
            # path taken above. Defensive mouth if both still empty.
            _refuse_uncited_exit(
                effect,
                observed=(
                    "raise face has neither exception_name nor "
                    "exception_type_coordinate"
                ),
                requested=(
                    "an authenticated exception identity (name or type coordinate) "
                    "derived from the tree"
                ),
                fix="do not fabricate 'reraise'; keep the nameless face loud",
            )
        name_term = str_const(resolved_name)
    return ctor(
        "py.exceptional_exit",
        [
            name_term,
            str_const(f"{effect.blame}#source-sha256={effect.source_sha256}"),
        ],
    )
