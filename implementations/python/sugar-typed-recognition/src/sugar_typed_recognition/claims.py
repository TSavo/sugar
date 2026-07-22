"""A representative handful of claims, ported onto the typed layer.

This is proof of the mechanism, not a migration: ~80 concrete grammar
classes and a comparable number of sugars exist, and porting them all would
demonstrate nothing that these nine do not. The set is chosen to cover every
shape the mechanism has to handle:

+-----------------------------+------------------------------------------------+
| claim                       | what its old ``owns`` collapsed to             |
+=============================+================================================+
| ``AssertClaim``             | ENTIRELY to ``accepts``. Old body was          |
|                             | ``site.observed == "Assert"`` — pure shape     |
|                             | re-derivation, nothing else. ``owns`` is now   |
|                             | a constant ``True``.                           |
+-----------------------------+------------------------------------------------+
| ``NameClaim``               | ENTIRELY to ``accepts``. Same story.           |
+-----------------------------+------------------------------------------------+
| ``ReturnClaim``             | Half. ``observed == "Return"`` -> ``accepts``; |
|                             | ``return_value() is not None`` survives as a   |
|                             | real question about a structurally optional    |
|                             | field.                                         |
+-----------------------------+------------------------------------------------+
| ``MethodCallClaim`` /       | One of four conjuncts. The shape leg went to   |
| ``PlainCallClaim`` /        | ``accepts``; the rest were never shape         |
| ``LenCallClaim`` /          | re-derivation but **claim-ordering facts**,    |
| ``KeywordCallClaim``        | and they survive as explicit disjointness.     |
+-----------------------------+------------------------------------------------+
| ``AddOpClaim`` /            | Half, and the surviving half is the point:     |
| ``MultiplyOpClaim`` /       | genuine operand-type dispatch. Three claims,   |
| ``AnnotationUnionClaim``    | one ``accepts``, distinguished only by the     |
|                             | TYPE of ``site.op``.                           |
+-----------------------------+------------------------------------------------+

Two things worth reading closely
--------------------------------

**The call family is where the no-precedence rule shows its teeth.** Today
``MethodCallSugar.owns`` reads::

    site.observed == "Call"
    and site.call_receiver() is not None
    and site.call_qualified_target_name() != "os.exit"
    and not site.call_has_keywords()

Four conjuncts, and it is tempting to say typing deletes three. It deletes
one. The first is shape re-derivation and becomes ``accepts = Call``. The
other two are facts about OTHER claims — ``OsSugar`` owns ``os.exit``,
``KeywordCallSugar`` owns keyword-bearing calls — and today they are
belt-and-braces alongside a ``comes_before`` precedence edge that would have
resolved the overlap anyway. Here there is no precedence edge, so those
conjuncts are not redundant defensiveness: they are the disjointness itself,
and every claim in the call family carries its share of it. That is a real
cost of removing precedence, and it is priced in below rather than hidden.

**The BinOp family is the multiple dispatch.** ``accepts = BinOp`` narrows
nothing between them; ``isinstance(site.op, Add)`` is the entire
discrimination, and ``site.op`` is a membrane ``Operator`` singleton rather
than the string ``"Add"`` that ``site.operator_kind() == "Add"`` compares
against today. Both the node type and the operator type participate in one
dispatch decision. No receiver's vtable can express that; a registry can.
"""

from __future__ import annotations

from typing import ClassVar

from sugar_node_membrane.nodes import (
    Assert,
    Attribute,
    BinOp,
    Call,
    Name,
    Return,
    SourceFragment,
)
from sugar_node_membrane.operators import Add, BitOr, Mult

from .claim import TypedClaim
from .role import Role

#: Builtin callees carved out of ``PlainCallClaim`` because a dedicated claim
#: owns them. Under the no-precedence rule this exclusion is load-bearing, not
#: cosmetic: without it ``PlainCallClaim`` and ``LenCallClaim`` both own
#: ``len(xs)`` and resolution panics AMBIGUOUS.
_DEDICATED_BUILTIN_CALLEES = frozenset({"len"})


# --------------------------------------------------------------------------
# collapsed entirely to accepts — owns asks nothing, because there is nothing
# left to ask
# --------------------------------------------------------------------------


class AssertClaim(TypedClaim):
    """``assert <condition>[, <message>]``.

    Ported from ``AssertSugar.owns``, whose entire body was
    ``site.observed == "Assert"``. There was never a semantic question here:
    the claim owns a shape, and the shape is now the declaration. ``owns``
    returning a constant is the honest outcome, not a stub — the alternative
    would be re-asking by string what ``accepts`` already established by type.
    """

    accepts: ClassVar[type[SourceFragment]] = Assert
    role: ClassVar[Role] = Role.STATEMENT

    @classmethod
    def owns(cls, site: Assert) -> bool:
        return True


class NameClaim(TypedClaim):
    """A bare name. Ported from ``NameSugar.owns`` (``observed == "Name"``)."""

    accepts: ClassVar[type[SourceFragment]] = Name
    role: ClassVar[Role] = Role.TERM

    @classmethod
    def owns(cls, site: Name) -> bool:
        return True


# --------------------------------------------------------------------------
# structural absence: a real question, and NOT a gap
# --------------------------------------------------------------------------


class ReturnClaim(TypedClaim):
    """``return <expr>``. Bare ``return`` is deliberately not owned.

    Ported from ``ReturnSugar.owns``::

        site.observed == "Return" and site.return_value() is not None

    The first conjunct became ``accepts``. The second is a genuine semantic
    question and survives: ``Return.value`` is ``Optional[Expression]``, and
    the two cases mean different things. ``value is None`` here is a
    STRUCTURAL absence being read, which is a fact — not a bare ``None``
    being used as a gap sentinel. Bare ``return`` then reaches ``resolve`` with no
    owner and panics GAP, exactly as the original comment intended ("bare
    return stays a loud factory gap"), and now it is the resolver that makes
    it loud rather than each claim remembering to.
    """

    accepts: ClassVar[type[SourceFragment]] = Return
    role: ClassVar[Role] = Role.STATEMENT

    @classmethod
    def owns(cls, site: Return) -> bool:
        return site.value is not None


# --------------------------------------------------------------------------
# the call family: one accepts, four claims, disjoint by construction
# --------------------------------------------------------------------------


class KeywordCallClaim(TypedClaim):
    """Any call carrying keywords. Ported from ``KeywordCallSugar``'s territory.

    Listed first because the other three define themselves partly by
    excluding it. Keyword-bearing calls bind differently, so the distinction
    is real; what changed is that it is now stated once here and once in each
    peer, instead of being implied by a ``comes_before`` edge.
    """

    accepts: ClassVar[type[SourceFragment]] = Call
    role: ClassVar[Role] = Role.TERM

    @classmethod
    def owns(cls, site: Call) -> bool:
        return bool(site.keywords)


class MethodCallClaim(TypedClaim):
    """``recv.method(<args>)`` — a call whose callee is an attribute access.

    ``isinstance(site.func, Attribute)`` is the ONE real question, and it is
    an isinstance on a membrane class: the blessed form. Today the same
    question is ``site.call_receiver() is not None``, which walks to the
    callee, checks its ast type, and projects the answer through an Optional
    so the caller can compare it to ``None`` — three steps to ask what the
    type system answers in one.
    """

    accepts: ClassVar[type[SourceFragment]] = Call
    role: ClassVar[Role] = Role.TERM

    @classmethod
    def owns(cls, site: Call) -> bool:
        return isinstance(site.func, Attribute) and not site.keywords


class PlainCallClaim(TypedClaim):
    """``f(<args>)`` — a call on a plain name, excluding dedicated builtins.

    The exclusion is the worked example of disjointness replacing precedence.
    Today ``CallSugar`` owns every plain call and ``LenCallSugar`` declares
    ``comes_before=("CallSugar",)`` to win the overlap. Here the overlap is
    not permitted to exist: ``PlainCallClaim`` says what it does NOT own.
    Deleting the exclusion does not silently change which sugar fires — it
    makes ``len(xs)`` panic AMBIGUOUS, which is the test below.
    """

    accepts: ClassVar[type[SourceFragment]] = Call
    role: ClassVar[Role] = Role.TERM

    @classmethod
    def owns(cls, site: Call) -> bool:
        func = site.func
        return (
            isinstance(func, Name)
            and func.id not in _DEDICATED_BUILTIN_CALLEES
            and not site.keywords
        )


class LenCallClaim(TypedClaim):
    """``len(x)``. Ported from ``LenCallSugar``, minus its precedence edge."""

    accepts: ClassVar[type[SourceFragment]] = Call
    role: ClassVar[Role] = Role.TERM

    @classmethod
    def owns(cls, site: Call) -> bool:
        func = site.func
        return isinstance(func, Name) and func.id == "len" and not site.keywords


# --------------------------------------------------------------------------
# the BinOp family: genuine operand-type dispatch
# --------------------------------------------------------------------------


class AddOpClaim(TypedClaim):
    """``a + b``. Ported from ``AddOpSugar.owns``::

        site.observed == "BinOp" and site.operator_kind() == "Add"

    Two string compares become one isinstance on a node class and one
    isinstance on an operator class. ``operator_kind()`` returning ``"Add"``
    is the tag dispatch the membrane's operator classes exist to delete: the
    string could disagree with the node, the type cannot.
    """

    accepts: ClassVar[type[SourceFragment]] = BinOp
    role: ClassVar[Role] = Role.TERM

    @classmethod
    def owns(cls, site: BinOp) -> bool:
        return isinstance(site.op, Add)


class MultiplyOpClaim(TypedClaim):
    """``a * b``. Ported from ``MultiplyOpSugar.owns``."""

    accepts: ClassVar[type[SourceFragment]] = BinOp
    role: ClassVar[Role] = Role.TERM

    @classmethod
    def owns(cls, site: BinOp) -> bool:
        return isinstance(site.op, Mult)


class AnnotationUnionClaim(TypedClaim):
    """``A | B``. Ported from ``AnnotationUnionSugar.owns``, with a caveat.

    The original is three conjuncts::

        site.observed == "BinOp"
        and site.operator_kind() == "BitOr"
        and site.is_within_annotation()

    The first two port exactly. **The third does not port, and that is a
    finding rather than an omission.** ``is_within_annotation()`` is an
    ANCESTOR question — is this node underneath an annotation — and the
    membrane's nodes carry children, not parents. So it is not an operand
    type and ``owns`` cannot ask it here.

    That is not a defect in the typed layer; it is the typed layer surfacing
    something the string-compare version hid. An ancestor fact is a function
    of (module source, node span), exactly like a subtree fact, and #5940's
    design review says so explicitly (part 2 §3: parent links minted at
    interning time make ancestor facts field reads). The membrane as merged
    has no parent links, so this claim is ported as the BitOr shape only, and
    a claim distinguishing union-in-annotation from ordinary bitwise-or on
    the same operator type is blocked on that vocabulary landing.

    Concretely: with parent links, this becomes a fourth dispatch coordinate
    of the same kind as the others — ``isinstance(site.parent_chain_head,
    AnnAssign)`` — and needs no new mechanism. Without them, ``a | b`` in an
    annotation and ``a | b`` in an expression are one dispatch key here.
    """

    accepts: ClassVar[type[SourceFragment]] = BinOp
    role: ClassVar[Role] = Role.TERM

    @classmethod
    def owns(cls, site: BinOp) -> bool:
        return isinstance(site.op, BitOr)


PORTED_CLAIMS: tuple[type[TypedClaim], ...] = (
    AssertClaim,
    NameClaim,
    ReturnClaim,
    KeywordCallClaim,
    MethodCallClaim,
    PlainCallClaim,
    LenCallClaim,
    AddOpClaim,
    MultiplyOpClaim,
    AnnotationUnionClaim,
)
