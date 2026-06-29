from __future__ import annotations

import ast
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


def is_comment_node(node: ast.AST) -> bool:
    """A comment: a bare string-constant statement (a docstring is the canonical
    case)."""
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def build_comment_sugar(site, ctx):
    if not is_comment_node(site.node):
        raise TypeError("CommentSugar claim built a non-comment statement")
    return CommentSugar()


def _owns(site) -> bool:
    return is_comment_node(site.node)


# A CommentSugar carries the Support role: the factory classifies the comment as
# Support (the inert source-audit category), not TERM.
COMMENT_CLAIM = SugarClaim(
    name="CommentSugar",
    role=SugarRole.SUPPORT,
    owns=_owns,
    build=build_comment_sugar,
)
