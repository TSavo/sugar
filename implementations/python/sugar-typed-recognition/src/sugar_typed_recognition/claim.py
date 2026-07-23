"""TypedClaim: ``accepts`` is the shape, ``owns`` is the semantics.

The defect this replaces
------------------------

Today's claim carries ``owns: Callable[[object], bool]``. That ``object`` is
the root defect: an untyped parameter forces every predicate to re-derive
what it is holding before it can ask its real question. Measured on the tree
this package sits beside: **403 ``.observed ==`` string compares** and 105
``.node`` reads, most of them shape re-derivation. ``MethodCallSugar.owns``
is four conjuncts and the first one is ``site.observed == "Call"``.

The replacement is two declarations instead of one predicate:

``accepts: type[SourceFragment]``
    The syntactic shape, checked **by type**, by the catalog, before ``owns``
    is ever called. ``accepts = Call`` is the whole of ``observed == "Call"``,
    and it cannot disagree with the node the way a string compare can.

``owns(cls, site: <accepts>) -> bool``
    The ONE semantic question that distinguishes this claim from other claims
    of the same shape. The parameter is typed as the class ``accepts`` names,
    so the body may reach for that class's fields directly — no ``_require``
    preamble, no defensive re-check.

isinstance on membrane classes is LEGAL and ENCOURAGED
------------------------------------------------------

Stated here, in the code, because if the design does not say it out loud
workers invent kind strings to dodge an imagined ban (#5940 design review,
section 6).

* ``isinstance(site.func, Attribute)`` — **legal.** "Is this callee an
  attribute access" is exactly the question the class hierarchy exists to
  answer. Interior questions about operands are isinstance questions.
* ``isinstance(site.op, Add)`` — **legal.** Operators are membrane classes
  too (singletons), so operator dispatch is the same act.
* ``site.kind == "Call"`` — **banned.** ``kind`` is the wire/CID projection,
  a frozen serialization word. It is not a dispatch mechanism. Any string
  compare against it is the disease coming back.

The rule in one line: **isinstance on OUR classes, never a tag compare on
strings.**

Where multiple dispatch lives
-----------------------------

``accepts`` narrows ONE type: the node's own class. But recognition is
where more than one type meets — a claim for ``Int + Int`` and a claim for
``str + str`` both ``accepts = BinOp`` and disagree about the operands.
``owns`` is where the operand types enter, and that is why a plain type
switch on the node class cannot replace the catalog: the node class is only
the first coordinate of the dispatch key.

The operands can be interrogated at all only because they arrive **already
``Typed``** from their own construction. That is not a convention this layer
asks callers to honor; it is forced by the membrane's construction order
(bottom-up, children before parents, ``construct.py``). Recognition inherits
that order: by the time a claim is asked about a ``BinOp``, its ``left``,
``right`` and ``op`` are finished objects with resolved types. So recognition
is bottom-up because construction is, and the ordering is forced by the
types rather than by documentation.

A child that cannot answer its type is a MISSING and panics. It is NEVER a
quiet ``False`` from ``owns`` — see ``operand_types`` below and
``panic.RecognitionArm.MISSING_OPERAND_TYPE``.
"""

from __future__ import annotations

from dataclasses import fields as dataclass_fields, is_dataclass
from typing import ClassVar, Tuple

from sugar_node_membrane.nodes import SourceFragment, Typeable, Typed
from sugar_node_membrane.operators import Operator

from .panic import RecognitionArm, recognition_panic
from .role import Role


class TypedClaim:
    """One claim. Subclass, declare ``accepts`` + ``role``, implement ``owns``.

    Subclasses are plain classes, not instances: a claim is a singleton
    identified by its class, exactly as today's ``Sugar`` subclasses are.
    """

    #: Dispatch coordinate 0: the syntactic shape, checked by the catalog.
    accepts: ClassVar[type[SourceFragment]]
    #: Dispatch coordinate -1: which question is being asked of the site.
    role: ClassVar[Role]

    def __init_subclass__(cls, **kw: object) -> None:
        super().__init_subclass__(**kw)
        accepts = cls.__dict__.get("accepts", getattr(cls, "accepts", None))
        if accepts is None:
            return  # an intermediate abstract claim; concrete ones declare it
        if not (isinstance(accepts, type) and issubclass(accepts, SourceFragment)):
            recognition_panic(
                RecognitionArm.GAP,
                owner=f"claim.{cls.__name__}",
                observed=f"accepts = {accepts!r}",
                requested="a membrane SourceFragment subclass",
                fix=(
                    "accepts names the node CLASS this claim recognizes "
                    "(e.g. accepts = Call). It is never a kind string."
                ),
            )

    @classmethod
    def name(cls) -> str:
        return cls.__name__

    @classmethod
    def owns(cls, site: SourceFragment) -> bool:
        """The ONE semantic question. ``site`` is an instance of ``accepts``.

        Returning ``True``/``False`` is an ANSWER, and only an answer. If this
        method cannot answer, it does not return ``False`` — nothing here may
        encode a MISSING as a negative. Operand types are guaranteed resolved
        before this is called, so "I could not tell" is not a reachable state.
        """
        raise NotImplementedError


# --------------------------------------------------------------------------
# operand typing: the guarantee that owns() is only ever asked answerable
# questions
# --------------------------------------------------------------------------


def _operator_field_names(cls: type) -> Tuple[str, ...]:
    """Dataclass fields of a membrane class that hold operators.

    Derived from the declared annotations. The membrane writes operator
    annotations as ``BinaryOperator`` / ``UnaryOperator`` / ``BooleanOperator``
    / ``Tuple[ComparisonOperator, ...]`` — every one of them contains the
    substring ``Operator``, and no child or leaf annotation does. This is a
    read of the membrane's own declarations, not a heuristic over arbitrary
    text; if the membrane ever names an operator type without that substring,
    the ``test_operator_fields_cover_every_operator_carrier`` test goes red
    rather than this silently under-reporting.
    """
    cached = _OPERATOR_FIELDS.get(cls)
    if cached is not None:
        return cached
    names: list[str] = []
    if is_dataclass(cls):
        for f in dataclass_fields(cls):
            annotation = (
                f.type if isinstance(f.type, str) else getattr(f.type, "__name__", "")
            )
            if "Operator" in annotation:
                names.append(f.name)
    result = tuple(names)
    _OPERATOR_FIELDS[cls] = result
    return result


_OPERATOR_FIELDS: dict[type, Tuple[str, ...]] = {}


def operand_types(site: SourceFragment) -> Tuple[type, ...]:
    """The resolved types of every operand of ``site``, in grammar order.

    This is the rest of the dispatch key — the coordinates after ``accepts``.
    Computing it is also the enforcement point: every operand must be able to
    answer its own type, and one that cannot panics HERE, before any claim's
    ``owns`` is called. That ordering is the whole point. If the check lived
    inside ``owns``, a claim that could not interrogate an operand would have
    only ``False`` to return, and a hole in the membrane would be
    indistinguishable from a correct negative answer.

    Structural absence is not a MISSING: an ``Optional`` child that is ``None``
    (a bare ``return``, a ``Call`` with no receiver) is an answered question
    whose answer is "nothing is there". It contributes ``type(None)`` to the
    key. A gap would be a MISSING; a declared-absent field is a fact.
    """
    key: list[type] = []
    cls = type(site)

    for name in getattr(cls, "_child_fields", ()):
        value = getattr(site, name)
        if value is None:
            key.append(type(None))
            continue
        if isinstance(value, tuple):
            for index, item in enumerate(value):
                key.append(_resolved_child_type(site, f"{name}[{index}]", item))
            continue
        key.append(_resolved_child_type(site, name, value))

    for name in _operator_field_names(cls):
        value = getattr(site, name)
        if isinstance(value, tuple):
            for index, item in enumerate(value):
                key.append(_resolved_operator_type(site, f"{name}[{index}]", item))
            continue
        key.append(_resolved_operator_type(site, name, value))

    return tuple(key)


def _resolved_child_type(site: SourceFragment, where: str, value: object) -> type:
    if isinstance(value, SourceFragment) and isinstance(value, Typed):
        # Typed.resolve_type() itself panics on an abstract class; a membrane
        # node that is not an instance of a concrete grammar class never
        # reaches a claim.
        return value.resolve_type()
    recognition_panic(
        RecognitionArm.MISSING_OPERAND_TYPE,
        owner="claim.operand_types",
        observed=(
            f"{type(site).__name__}.{where} holds "
            f"{type(value).__name__}"
            + (
                " (Typeable but not Typed: it was never constructed)"
                if isinstance(value, Typeable)
                else " (not a membrane node)"
            )
        ),
        requested="an already-Typed membrane node",
        fix=(
            "operands are Typed by their own construction, bottom-up, before "
            "the parent is recognized. An operand that cannot answer its type "
            "is a hole in the membrane, not a False from owns(). Fix the "
            "construction that produced this child; never make a claim "
            "tolerate it."
        ),
    )


def _resolved_operator_type(site: SourceFragment, where: str, value: object) -> type:
    if isinstance(value, Operator) and type(value).kind:
        return type(value)
    recognition_panic(
        RecognitionArm.MISSING_OPERAND_TYPE,
        owner="claim.operand_types",
        observed=(
            f"{type(site).__name__}.{where} holds {value!r} "
            f"({type(value).__name__})"
        ),
        requested="a concrete membrane Operator singleton",
        fix=(
            "operators are membrane classes, not strings. The operator arrives "
            "from operators.operator_for(), which itself has two arms. A "
            "non-Operator here means something bypassed that door."
        ),
    )
