"""Both failure arms, and the MISSING that must never become a False.

Resolution has two arms: exactly one claim, or panic. These tests hold that
line by driving each panic from a real parsed site wherever one exists, and
by construction only where a real site cannot produce the shape.
"""

import pytest

from sugar_node_membrane import Membrane, SourceUnit, Typeable
from sugar_node_membrane.nodes import BinOp, Call, Name, Return, SourceFragment
from sugar_node_membrane.operators import Add
from sugar_node_membrane.spans import Span

from sugar_typed_recognition import (
    RecognitionArm,
    RecognitionPanic,
    Role,
    TypedCatalog,
    TypedClaim,
    default_catalog,
    operand_types,
)
from sugar_typed_recognition.claims import PORTED_CLAIMS, LenCallClaim, PlainCallClaim


def parse(source: str):
    return Membrane().parse(source)


def only(root, cls):
    found = [n for n in root.walk() if type(n) is cls]
    assert len(found) == 1
    return found[0]


# --------------------------------------------------------------------------
# ARM 1: no claim owns the combination -> GAP -> panic
# --------------------------------------------------------------------------


def test_gap_when_no_claim_owns_the_operand_types():
    """`a - b` is a BinOp, so accepts matches three claims — and every one of
    them says no, because Sub is not Add, Mult or BitOr. Shape alone is not
    ownership."""
    site = only(parse("y = a - b\n"), BinOp)
    with pytest.raises(RecognitionPanic) as exc:
        default_catalog().resolve(Role.TERM, site)
    assert exc.value.arm is RecognitionArm.GAP
    assert "BinOp" in exc.value.observed
    assert "Sub" in exc.value.observed  # the operand type that found no owner


def test_gap_when_no_claim_accepts_the_shape_at_all():
    site = only(
        parse("y = [1]\n"),
        __import__("sugar_node_membrane.nodes", fromlist=["List"]).List,
    )
    with pytest.raises(RecognitionPanic) as exc:
        default_catalog().resolve(Role.TERM, site)
    assert exc.value.arm is RecognitionArm.GAP


def test_bare_return_is_a_loud_gap_not_a_silent_skip():
    """ReturnClaim.owns is False for bare `return` — and False from the ONLY
    candidate means nobody owns it, which panics. The claim declining is not
    the same event as the site being unowned, and only resolve() decides."""
    site = only(parse("def f():\n    return\n"), Return)
    with pytest.raises(RecognitionPanic) as exc:
        default_catalog().resolve(Role.TERM, site)
    assert exc.value.arm is RecognitionArm.GAP


def test_gap_when_the_callee_is_neither_a_name_nor_an_attribute():
    """`(lambda: g)()()`-style callees: a real parsed shape no ported claim
    owns. The call family covers Name and Attribute callees; a Call callee is
    outside it and says so."""
    root = parse("h()()\n")
    outer = [n for n in root.walk() if isinstance(n, Call) and isinstance(n.func, Call)]
    assert len(outer) == 1
    with pytest.raises(RecognitionPanic) as exc:
        default_catalog().resolve(Role.TERM, outer[0])
    assert exc.value.arm is RecognitionArm.GAP


def test_gap_names_the_key_and_the_fix():
    site = only(parse("y = a - b\n"), BinOp)
    with pytest.raises(RecognitionPanic) as exc:
        default_catalog().resolve(Role.TERM, site)
    assert "accepts = BinOp" in exc.value.fix
    assert exc.value.requested == "exactly one term claim"


# --------------------------------------------------------------------------
# ARM 2: two claims own the combination -> AMBIGUOUS -> panic
# --------------------------------------------------------------------------


def test_ambiguity_panics_and_never_picks_the_first():
    """Two claims accepting BinOp and both answering True for Add.

    The catalog does not rank them, does not consult a declaration order, and
    does not return candidates[0]. Registration order is varied below to show
    the outcome does not depend on it.
    """

    class FirstAdd(TypedClaim):
        accepts = BinOp
        role = Role.TERM

        @classmethod
        def owns(cls, site):
            return isinstance(site.op, Add)

    class SecondAdd(TypedClaim):
        accepts = BinOp
        role = Role.TERM

        @classmethod
        def owns(cls, site):
            return isinstance(site.op, Add)

    site = only(parse("y = a + b\n"), BinOp)

    for order in ((FirstAdd, SecondAdd), (SecondAdd, FirstAdd)):
        with pytest.raises(RecognitionPanic) as exc:
            TypedCatalog(order).resolve(Role.TERM, site)
        assert exc.value.arm is RecognitionArm.AMBIGUOUS
        assert "FirstAdd" in exc.value.observed
        assert "SecondAdd" in exc.value.observed


def test_ambiguity_is_the_soundness_guarantee_of_the_ported_disjointness():
    """Remove PlainCallClaim's builtin exclusion and `len(xs)` goes ambiguous.

    This is the receipt that the exclusion is load-bearing rather than
    cosmetic. Today's tree resolves the same overlap with a `comes_before`
    edge; here it is not permitted to exist.
    """

    class PlainCallWithoutExclusion(TypedClaim):
        accepts = Call
        role = Role.TERM

        @classmethod
        def owns(cls, site):
            return isinstance(site.func, Name) and not site.keywords

    site = only(parse("len(xs)\n"), Call)

    with pytest.raises(RecognitionPanic) as exc:
        TypedCatalog((PlainCallWithoutExclusion, LenCallClaim)).resolve(Role.TERM, site)
    assert exc.value.arm is RecognitionArm.AMBIGUOUS

    # With the exclusion as ported, the same site resolves to exactly one.
    assert (
        TypedCatalog((PlainCallClaim, LenCallClaim)).resolve(Role.TERM, site)
        is LenCallClaim
    )


def test_the_ported_catalog_is_unambiguous_over_a_real_corpus():
    """No site in this source resolves to more than one claim. A catalog that
    is ambiguous anywhere is not a function anywhere."""
    catalog = default_catalog()
    root = parse(
        "def f(a, b):\n"
        "    assert len(a) + b * 2\n"
        "    c = a.join(b)\n"
        "    d = g(c, k=1)\n"
        "    return d | c\n"
    )
    checked = 0
    for node in root.walk():
        for role in Role:
            candidates = catalog.candidates_for(role, node)
            assert len(candidates) <= 1, (
                f"{type(node).__name__} under {role.value} has "
                f"{[c.name() for c in candidates]}"
            )
            checked += 1
    assert checked > 0


# --------------------------------------------------------------------------
# THE THIRD THING THAT IS NOT AN ARM: a child that cannot answer its type
# --------------------------------------------------------------------------


class _UnconstructedChild(Typeable):
    """Typeable but never constructed: it can be ASKED for a type and cannot
    give one. Exactly the shape that must not reach owns()."""

    def resolve_type(self):
        raise AssertionError("this child has no type; it was never constructed")


def _unit():
    return SourceUnit(filename="<t>", source="a + b\n")


def test_untyped_child_panics_and_never_reaches_owns():
    """If this were allowed through, a claim would have only False to return,
    and a hole in the membrane would be encoded identically to a correct
    negative answer."""
    asked: list[object] = []

    class Nosy(TypedClaim):
        accepts = BinOp
        role = Role.TERM

        @classmethod
        def owns(cls, site):
            asked.append(site)
            return True

    unit = _unit()
    broken = BinOp(
        unit=unit,
        span=Span(0, 5),
        left=_UnconstructedChild(),  # type: ignore[arg-type]
        op=Add.instance(),
        right=_UnconstructedChild(),  # type: ignore[arg-type]
    )

    with pytest.raises(RecognitionPanic) as exc:
        TypedCatalog((Nosy,)).resolve(Role.TERM, broken)
    assert exc.value.arm is RecognitionArm.MISSING_OPERAND_TYPE
    assert "Typeable but not Typed" in exc.value.observed
    assert asked == [], "owns() must not be called with an uninterrogable operand"


def test_string_operator_panics_rather_than_dispatching():
    """Guarding the regression the operator classes exist to prevent: an
    operator arriving as the tag `"Add"` instead of the singleton."""
    unit = _unit()
    name = Name(unit=unit, span=Span(0, 1), id="a")
    broken = BinOp(
        unit=unit,
        span=Span(0, 5),
        left=name,
        op="Add",  # type: ignore[arg-type]
        right=name,
    )
    with pytest.raises(RecognitionPanic) as exc:
        operand_types(broken)
    assert exc.value.arm is RecognitionArm.MISSING_OPERAND_TYPE
    assert "Operator" in exc.value.requested


def test_non_membrane_site_panics():
    with pytest.raises(RecognitionPanic) as exc:
        default_catalog().resolve(Role.TERM, object())  # type: ignore[arg-type]
    assert exc.value.arm is RecognitionArm.MISSING_OPERAND_TYPE


def test_structural_absence_is_a_fact_not_a_missing():
    """Optional-and-None is an answered question. `return` with no value and
    a Call with no keywords both key cleanly; neither panics."""
    bare = only(parse("def f():\n    return\n"), Return)
    assert operand_types(bare) == (type(None),)


# --------------------------------------------------------------------------
# declaration-time guards
# --------------------------------------------------------------------------


def test_a_kind_string_as_accepts_is_refused_at_class_creation():
    with pytest.raises(RecognitionPanic) as exc:

        class Stringly(TypedClaim):
            accepts = "Call"  # type: ignore[assignment]
            role = Role.TERM

            @classmethod
            def owns(cls, site):
                return True

    assert "SourceFragment subclass" in exc.value.requested


def test_registering_an_instance_rather_than_a_class_is_refused():
    with pytest.raises(RecognitionPanic):
        TypedCatalog((LenCallClaim(),))  # type: ignore[list-item]


def test_operator_fields_cover_every_operator_carrier():
    """The annotation read in claim._operator_field_names must see every
    membrane field that holds an operator. If the membrane ever names an
    operator type without 'Operator' in it, this goes red rather than the
    census silently under-reporting."""
    from dataclasses import fields as dataclass_fields, is_dataclass

    from sugar_node_membrane.nodes import KIND_REGISTRY
    from sugar_node_membrane.operators import Operator

    from sugar_typed_recognition.claim import _operator_field_names

    for cls in KIND_REGISTRY.values():
        if not is_dataclass(cls):
            continue
        declared = set(_operator_field_names(cls))
        for f in dataclass_fields(cls):
            annotation = f.type if isinstance(f.type, str) else ""
            mentions_operator_class = any(
                sub.__name__ in annotation for sub in _all_subclasses(Operator)
            )
            if mentions_operator_class:
                assert f.name in declared, (
                    f"{cls.__name__}.{f.name}: {annotation} holds an operator "
                    "but the field census does not see it"
                )


def _all_subclasses(cls):
    for sub in cls.__subclasses__():
        yield sub
        yield from _all_subclasses(sub)


def test_every_ported_claim_declares_a_membrane_class():
    for claim in PORTED_CLAIMS:
        assert issubclass(claim.accepts, SourceFragment)
        assert isinstance(claim.role, Role)
