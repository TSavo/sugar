from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarClaim, SugarRole
from sugar_lift_py_tests.floor import SupportValue
from sugar_lift_py_tests.outcome import Complete, Outcome


@dataclass(frozen=True)
class CommentSugar:
    """A comment: a docstring / bare-string statement. It is inert metadata -- it is
    present in the source and does nothing. No first-order logic, no scope, no
    effect. The factory composes a CommentSugar for it, which classifies the node as
    Support in the source audit: it always completes and never constrains. It is
    neither refused (it is not unsupported) nor silently dropped.
    """

    def desugar(self, ctx=None) -> Outcome:
        # A comment desugars to Support and ALWAYS completes: no term, no binding,
        # no scope -- it contributes nothing to the first-order logic.
        return Complete(SupportValue())


def _is_comment_site(site) -> bool:
    """A comment: a bare string-constant statement (a docstring is the canonical
    case)."""
    if site.observed != "Expr":
        return False
    terms = site.terms()
    if len(terms) != 1:
        return False
    val_site = terms[0]
    if val_site.observed != "PrimitiveLiteral":
        return False
    return isinstance(val_site.literal_value(), str)


def build_comment_sugar(site, ctx):
    if not _is_comment_site(site):
        raise TypeError("CommentSugar claim built a non-comment statement")
    return CommentSugar()


def _owns(site) -> bool:
    return _is_comment_site(site)


# A comment is a STATEMENT (a member of a block); its OUTCOME is Support. The role
# is the dispatch key (parallel to TERM for expressions), not the category.
COMMENT_CLAIM = SugarClaim(
    name="CommentSugar",
    role=SugarRole.STATEMENT,
    owns=_owns,
    build=build_comment_sugar,
)
