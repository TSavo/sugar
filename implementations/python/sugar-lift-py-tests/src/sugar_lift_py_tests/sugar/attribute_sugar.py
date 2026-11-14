"""Attribute access `<receiver>.<name>`.

Reduce the receiver and ask it for the attribute -- the value owns what `.name`
means, exactly as SubscriptSugar asks the receiver what `[index]` means. A
symbolic receiver stays the opaque `py.getattr(recv, "name")` coordinate (the
same EUF vocabulary as `py.subscript`); a value that owns the field folds; a
value with no attribute floor hits its own loud gap. The attribute NAME is a
static identifier carried onto the coordinate, never desugared.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import (
    ConstructedTermSugar,
    require_constructed_term_sugar,
)
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class AttributeSugar(ConstructedTermSugar):
    receiver: ConstructedTermSugar
    name: str
    site: object = dataclass_field(compare=False)

    def __post_init__(self) -> None:
        require_constructed_term_sugar(self.receiver, owner="AttributeSugar.receiver")

    @classmethod
    def witnesses(cls):
        # `z.numerator` on an int is z itself; the pair rides the coordinate's
        # identity vs a contradicting asserted value.
        prefix = "def A(z):\n    return z.numerator\n\n"
        return _call_pair(
            name="attribute_return",
            owner_sugar="AttributeSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:attribute-construction",
            (
                self.occurrence_term(owner=owner),
                self.receiver.to_term(owner=owner),
                str_const(self.name),
            ),
            symbol_kind="coordinate",
        )

    @staticmethod
    def project_attribute(receiver, name: str, site, ctx: object) -> ExitSet:
        """Producer-owned attribute **read** projection (one door).

        The law shared by ordinary AttributeSugar and Attribute AugAssign:

        1. Formal receiver → undischarged ``attribute_named`` carrier
        2. Authenticated CallSiteValue body → ``force_floor`` then attribute
        3. Else Floor ``receiver.attribute(name, site, ctx)`` (a property
           getter applies under the reading caller's ``ctx``)
        Callers that already hold a reduced receiver (AugAssign) enter here
        without re-evaluating the receiver expression.
        """
        from sugar_lift_py_tests.floor import CallSiteValue

        formal_coordinate = getattr(receiver, "formal_coordinate", None)
        if formal_coordinate is not None:
            from sugar_lift_py_tests.caller_parameter_contract import (
                NativeOperationExitCarrierV1,
            )
            from sugar_lift_py_tests.floor import StringValue

            return NativeOperationExitCarrierV1.mint(
                site=site,
                operator="attribute_named",
                operands=(receiver, StringValue(name)),
                coordinates=(formal_coordinate, None),
            )

        if (
            isinstance(receiver, CallSiteValue)
            and receiver.body is not None
            and receiver.source_call_frame_cid is not None
        ):
            receiver = receiver.force_floor(
                ctx,
                owner="authenticated attribute receiver",
                project_callsite=False,
            )

        # Class-definition construction can cache this sugar before its
        # receipt-backed import member is seated.  At reduction, consume only
        # the exact full-Attribute occurrence row minted by the lexical import
        # producer; absent/resolved rows retain the ordinary Floor law below.
        from sugar_source_tree.fragment import SourceFragment

        if type(site) is SourceFragment:
            span = site.line_col_span
            # The force-floor has REACHED this value-use.  If manager receipt
            # seating deferred an unresolved-target refusal here, mint it now as
            # the countable terminal it always was (reachability-scoped: an
            # unreached message-only use never runs this consumer).
            deferred = site.unit.deferred_unresolved_import_value_use(
                (span.start_line, span.start_col, span.end_line, span.end_col)
            )
            if deferred is not None:
                # PROVEN message-only (frame_value_use_is_message_only gated the
                # deferral): the contract does not depend on this value, so the
                # force-floor reaching it here yields a message opacity rather
                # than a refusal, letting the manager construct.
                from sugar_lift_py_tests.floor.message_opaque_value import (
                    MessageOpaqueValue,
                )
                from sugar_lift_py_tests.ir import ctor, str_const
                from sugar_lift_py_tests.outcome import ExitSet

                return ExitSet.completed(
                    MessageOpaqueValue(
                        term=ctor(
                            "python:message-opaque-value",
                            [str_const(deferred.target_symbol)],
                            symbol_kind="coordinate",
                        )
                    )
                )
            receipt = site.unit.import_value_use_resolution(
                (span.start_line, span.start_col, span.end_line, span.end_col)
            )
            if receipt is None:
                context = site.unit.construction_context
                if context is not None:
                    receipt = context.source_import_value_receipts_by_site.get(
                        (
                            site.unit.filename,
                            site.unit.source_cid,
                            span.start_line,
                            span.start_col,
                            span.end_line,
                            span.end_col,
                        )
                    )
            from sugar_lift_py_tests.import_binding import AuthenticatedImportUseV1

            if type(receipt) is AuthenticatedImportUseV1:
                receipt.revalidate()
                use_site = receipt.use["useSite"]
                exported_path = tuple(receipt.use["exportedMemberPath"])
                if (
                    receipt.source_cid != site.unit.source_cid
                    or use_site.get("sourceCid") != site.unit.source_cid
                    or (
                        use_site.get("startLine"),
                        use_site.get("startCol"),
                        use_site.get("endLine"),
                        use_site.get("endCol"),
                    )
                    != (span.start_line, span.start_col, span.end_line, span.end_col)
                    or (exported_path and exported_path[-1] != name)
                    or (
                        not exported_path
                        and _submodule_terminus_module(receipt, name) is None
                    )
                ):
                    from sugar_source_tree.panic import BackendDefect

                    raise BackendDefect(
                        blame=site,
                        owner="AttributeSugar.project_attribute",
                        observed="import member receipt does not own this Attribute",
                        requested="same-source exact member-use occurrence testimony",
                        fix="transport the lexical import-value receipt unchanged",
                    )
                target = receipt.target_symbol
                if not target.startswith("python:"):
                    from sugar_source_tree.panic import BackendDefect

                    raise BackendDefect(
                        blame=site,
                        owner="AttributeSugar.project_attribute",
                        observed=f"target_symbol={target!r}",
                        requested="authenticated python: import target symbol",
                        fix="preserve the receipt targetSymbol unchanged",
                    )
                if not exported_path:
                    # ``import a.b`` binds ``a``; the occurrence ``a.b`` is the
                    # module ``a.b`` itself, not a member of it (#7626).  The
                    # receipt testifies that module, so the read completes as
                    # its structural module coordinate; ``a.b.x`` keeps its own
                    # member receipt at its own occurrence.
                    from sugar_lift_py_tests.floor.symbolic_value import (
                        SymbolicValue,
                    )
                    from sugar_lift_py_tests.ir import ctor, str_const
                    from sugar_lift_py_tests.outcome import ExitSet

                    return ExitSet.completed(
                        SymbolicValue(
                            ctor(
                                "python:module",
                                (str_const(target.removeprefix("python:")),),
                            )
                        )
                    )
                from sugar_lift_py_tests.sugar.import_member_sugar import (
                    ImportMemberSugar,
                )

                return ImportMemberSugar(
                    target.removeprefix("python:"), receipt, site
                ).desugar(ctx)
        unknown = _unknown_receiver_attribute(receiver, name, site)
        if unknown is not None:
            return unknown
        return receiver.attribute(name, site, ctx)

    def desugar(self, ctx: object = None) -> ExitSet:
        return self.receiver.desugar(ctx).and_then(
            lambda receiver: self.project_attribute(receiver, self.name, self.site, ctx)
        )


_ATTRIBUTE_RESULT = "python:attribute_result"


def _submodule_terminus_module(receipt, name: str) -> str | None:
    """The module an ``import a.b`` receipt names at the Attribute ``a.b``.

    The lexical pass enrolls the occurrence that spells a submodule binding's
    whole module with an empty member path (#7626).  That receipt owns an
    Attribute ``.name`` only when its binding is a plain ``import`` (no
    from-import member) of a dotted module whose head is the bound local and
    whose last segment is ``name``.  Anything else is ``None``.
    """
    binding = receipt.import_binding.value
    target = binding.get("target")
    if not isinstance(target, dict) or target.get("exportedPath") != []:
        return None
    symbol = receipt.target_symbol
    if not symbol.startswith("python:"):
        return None
    module = symbol.removeprefix("python:")
    segments = module.split(".")
    if (
        len(segments) < 2
        or segments[0] != binding.get("localSlot")
        or segments[-1] != name
    ):
        return None
    return module


def _unknown_receiver_attribute(receiver, name: str, site):
    """``m.x`` where nothing here resolved ``m``: two faces, never a guess.

    ``import sys`` with no projected ``sys`` leaves ``sys`` a bare symbolic
    name.  When the module binds that name only by an import (or not at all)
    -- the same lexical test an unknown callee passes -- no floor, contract or
    source testified to what ``getattr`` runs, so the read may raise anything
    (``AttributeError``, ``NameError``, a descriptor's own raise).  It
    completes only under ``python:unknown_attribute.completes(
    python:unknown_attribute(<dotted>, <occurrence>))`` with the value
    ``python:attribute_result(<receiver>, <name>, <occurrence>)`` -- each read
    its own unknown, since a module attribute may be rebound between reads --
    and halts with an ``UndeterminedRaiseEffect`` (owner
    ``UnknownAttribute:<dotted>``) under the complement: the #7585 law.  A read
    on such a result is the same unknown again.  A formal receiver, or any
    other symbolic value, keeps its own law.
    """
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.ir import _Ctor, _Var

    if type(receiver) is not SymbolicValue or receiver.formal_coordinate is not None:
        return None
    if site is None:
        return None
    term = receiver.term
    if isinstance(term, _Var):
        from sugar_lift_py_tests.sugar.call_site_sugar import (
            _lexically_unknown_head,
        )

        if not _lexically_unknown_head(site, term.name):
            return None
        dotted = f"{term.name}.{name}"
    elif isinstance(term, _Ctor) and term.name == _ATTRIBUTE_RESULT:
        dotted = f"{_dotted_of(term)}.{name}"
    else:
        return None

    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.ir import atomic, ctor, str_const
    from sugar_lift_py_tests.occurrence import occurrence_key
    from sugar_lift_py_tests.outcome.exit_set import ExitSet

    key = occurrence_key(site)
    completes = atomic(
        "python:unknown_attribute.completes",
        [ctor("python:unknown_attribute", (str_const(dotted), str_const(key)))],
    )
    value = SymbolicValue(
        ctor(_ATTRIBUTE_RESULT, (term, str_const(name), str_const(key)))
    )
    return ExitSet.two_faced(
        value,
        UndeterminedRaiseEffect(
            blame=str(site),
            occurrence=key,
            producer_node_owner=f"UnknownAttribute:{dotted}",
        ),
        guard=completes,
    )


def _dotted_of(term) -> str:
    from sugar_lift_py_tests.ir import _ConstStr, _Ctor, _Var

    if isinstance(term, _Var):
        return term.name
    if isinstance(term, _Ctor) and term.name == _ATTRIBUTE_RESULT:
        inner, attr = term.args[0], term.args[1]
        name = attr.value if isinstance(attr, _ConstStr) else "?"
        return f"{_dotted_of(inner)}.{name}"
    return "?"
