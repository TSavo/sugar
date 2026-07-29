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

from sugar_lift_py_tests.outcome import Outcome
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
    def project_attribute(receiver, name: str, site, ctx: object = None) -> Outcome:
        """Producer-owned attribute **read** projection (one door).

        Complete law shared by ordinary AttributeSugar and Attribute AugAssign:

        1. Formal receiver → undischarged ``attribute_named`` carrier
        2. Authenticated CallSiteValue body → ``force_floor`` then attribute
        3. Else Floor ``receiver.attribute(name, site)``
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
            receipt = site.unit.import_value_use_resolution(
                (span.start_line, span.start_col, span.end_line, span.end_col)
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
                    or not exported_path
                    or exported_path[-1] != name
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
                from sugar_lift_py_tests.sugar.import_member_sugar import (
                    ImportMemberSugar,
                )

                return ImportMemberSugar(
                    target.removeprefix("python:"), receipt, site
                ).desugar(ctx)
        return receiver.attribute(name, site)

    def desugar(self, ctx: object = None) -> Outcome:
        return self.receiver.desugar(ctx).and_then(
            lambda receiver: self.project_attribute(
                receiver, self.name, self.site, ctx
            )
        )
