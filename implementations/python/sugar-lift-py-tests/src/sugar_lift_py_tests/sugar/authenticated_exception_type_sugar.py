from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.sugar.sugar_base import (
    ConstructedTermSugar,
    require_constructed_term_sugar,
)


@dataclass(frozen=True)
class AuthenticatedExceptionTypeSugar(ConstructedTermSugar):
    value: ConstructedTermSugar
    identity: object
    mro: tuple | None = None
    site: object = dataclass_field(compare=False, default=None)
    class_value: object | None = dataclass_field(compare=False, default=None)

    def __post_init__(self) -> None:
        require_constructed_term_sugar(
            self.value, owner="AuthenticatedExceptionTypeSugar.value"
        )

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.witnesses import _assertion_pair

        # Two arms named by builtin exception classes: the raised
        # ``ValueError`` passes the ``KeyError`` arm and is taken by the
        # ``ValueError`` one, so only the matching identity's arm binds `z`.
        return _assertion_pair(
            name="authenticated_exception_type",
            owner_sugar="AuthenticatedExceptionTypeSugar",
            statements=(
                "z = 5\n"
                "try:\n"
                "    raise ValueError\n"
                "except KeyError:\n"
                "    z = 7\n"
                "except ValueError:\n"
                "    z = 6"
            ),
            truthful="z == 6",
            lying="z == 7",
        )

    def _identity_term(self):
        """The identity coordinate: the undecided citation's is its read's
        (``UndecidedExceptionClassV1.coordinate``)."""
        from sugar_source_tree.nodes import UndecidedExceptionClassV1

        if isinstance(self.identity, UndecidedExceptionClassV1):
            return self.identity.coordinate()
        return self.identity

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        return ctor(
            "python:authenticated-exception-type-construction",
            (
                self.occurrence_term(owner=owner),
                self._identity_term(),
                self.value.to_term(owner=owner),
            ),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx=None):
        """Read the operand; its completing face is the sealed identity.

        An import-bound operand (``mod.Err``, or ``Err`` under ``from m import
        Err``) is read through the one import-member read
        (``ImportMemberSugar.desugar``).  A dotted read runs ``getattr`` where
        it is read and may raise, which the lifter cannot decide: it is the
        two-faced read (``ImportMemberValue.read_faces``), owing the
        ``undecided`` member under the import's target symbol on both faces.
        Its halting face is the operand's halt where the reader reads it (an
        ``except`` arm: the ``try``'s halt at that arm; ``raise mod.Err``: the
        raise's operand halt; a warning category: the call's argument halt).
        Its completing face holds the identity value below in place of the
        reference, so matching and raising read the same identity as before.
        A name a ``from`` import bound is read by name and cannot raise there:
        one completed arm, exactly the identity value.

        Import-bound dotted operands already carry a closed
        ``python:exception_type_identity(import, …)`` coordinate from the
        lexical import pass.  That coordinate *is* the source-visible floor.

        Provider-gated heads (``importorskip`` / optional try-import) seal the
        identity term itself as the carrier: the import provider is not
        resolved again here.  An operand that is not an import-member read
        (an Attribute chain on a module head the table does not bind on every
        path) is not reduced: it must not invent ``SymbolicValue.attribute``
        success or AttributeError.  MRO is only whatever was supplied at
        construction; this door never fabricates it.

        The undecided citation (``UndecidedExceptionClassV1``: a class a star
        import the lifter cannot read may bind) names no class and is never
        refused: the read completes with its own undecided coordinate, which
        no match decides (``adt.is_python_type`` is retained against it, as
        against an import coordinate), and owes the ``undecided`` member
        (reason ``unanswered``) on that arm.
        """
        from sugar_lift_py_tests.sugar.import_member_sugar import ImportMemberSugar

        identified = self._identity_value()
        if not isinstance(self.value, ImportMemberSugar):
            return identified
        return self.value.desugar(ctx).and_then(lambda _reference: identified)

    def _identity_value(self):
        """The one completed arm holding the sealed identity's value."""
        from sugar_lift_py_tests.floor.authenticated_exception_type_value import (
            AuthenticatedExceptionTypeValue,
        )
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_source_tree.nodes import UndecidedExceptionClassV1

        if isinstance(self.identity, UndecidedExceptionClassV1):
            coordinate = self.identity.coordinate()
            return ExitSet.completed(
                AuthenticatedExceptionTypeValue(
                    SymbolicValue(coordinate), coordinate, None, None
                ),
                owed=self.identity.owed(),
            )

        # When construction already projected the exception-class floor (import
        # Attribute paths, source ClassDef graphs), do not re-enter Attribute
        # or other receivers that only exist to name the same identity.
        if self.class_value is not None:
            return ExitSet.completed(
                AuthenticatedExceptionTypeValue(
                    self.class_value,
                    self.identity,
                    self.mro,
                    self.class_value,
                )
            )

        import_floor = _import_bound_exception_floor(self.identity)
        if import_floor is not None:
            return ExitSet.completed(
                AuthenticatedExceptionTypeValue(
                    import_floor, self.identity, self.mro, import_floor
                )
            )

        # Provider-gated / non-import sealed identity: do not re-desugar Attribute
        # chains on opaque module receivers.
        return ExitSet.completed(
            AuthenticatedExceptionTypeValue(
                SymbolicValue(self.identity),
                self.identity,
                self.mro,
                self.class_value,
            )
        )


def _import_bound_exception_floor(identity):
    """The ExceptionClassValue named by an import identity, or None.

    Only the ``import`` kind of ``python:exception_type_identity`` is closed
    without further floor projection: its second argument is the qualified
    export coordinate already joined from the authenticated import target and
    the static Attribute chain.  Builtins and source-class identities keep
    their existing leaf floors.
    """
    from sugar_lift_py_tests.floor.exception_class_value import ExceptionClassValue

    args = getattr(identity, "args", None)
    if args is None or len(args) != 2:
        return None
    kind = getattr(args[0], "value", None)
    qualified = getattr(args[1], "value", None)
    if kind != "import" or not isinstance(qualified, str) or not qualified:
        return None
    return ExceptionClassValue(qualified)
