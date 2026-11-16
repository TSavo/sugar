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
from sugar_lift_py_tests.sugar.witnesses import _assertion_pair


@dataclass(frozen=True)
class AttributeSugar(ConstructedTermSugar):
    receiver: ConstructedTermSugar
    name: str
    site: object = dataclass_field(compare=False)

    def __post_init__(self) -> None:
        require_constructed_term_sugar(self.receiver, owner="AttributeSugar.receiver")

    @classmethod
    def witnesses(cls):
        # `C.x` reads a class attribute of a same-file class literal: the
        # class statement's body binds `x`, and the read of `C` is that
        # class (a definition, never a `global:` input), so the attribute is
        # decided.  The subject was `(5).numerator`, a builtin `int` member
        # the lifter does not state, which left both halves open.
        return _assertion_pair(
            name="attribute_return",
            owner_sugar="AttributeSugar",
            prefix="class C:\n    x = 5\n\n\n",
            statements="",
            truthful="C.x == 5",
            lying="C.x == 6",
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

        1. Formal receiver → its ``field:`` input where the field is one
           (``receiver_dispatch.receiver_field_read``), else the one
           undecided read of arm 2: a read is ``__getattribute__`` then
           ``__getattr__`` and the descriptors they find, a protocol no one
           dispatched method states, so it waits on no caller's actual and
           is no dispatched call, its value keyed per evaluation
           (``floor_value.undecided_attribute_result``, #7757)
        2. Else Floor ``receiver.attribute(name, site, ctx)`` (a property
           getter applies under the reading caller's ``ctx``; a symbolic
           receiver is the same two-faced undecided read,
           ``floor_value.undecided_attribute_result``; a call's result is its
           coordinate, never its callee's body, #7757 step 6)
        Callers that already hold a reduced receiver (AugAssign) enter here
        without re-evaluating the receiver expression.
        """
        formal_coordinate = getattr(receiver, "formal_coordinate", None)
        if formal_coordinate is not None:
            # A field of a parameter whose class and fields are inputs of
            # the contract (#7757): the ``field:<param>.<name>`` input under
            # the plain-read guard prove decides, the undecided read under
            # its complement.
            from sugar_lift_py_tests.receiver_dispatch import receiver_field_read

            field_read = receiver_field_read(receiver, name, site)
            if field_read is not None:
                return field_read
            # The formal's own read, arm 2: no import receipt or call frame
            # names a parameter.
            from sugar_lift_py_tests.floor.object_identity import arrived_outcome

            return arrived_outcome(receiver.attribute(name, site, ctx), site)

        # Class-definition construction can cache this sugar before its
        # receipt-backed import member is seated.  At reduction, consume only
        # the exact full-Attribute occurrence row the unit holds, seated from
        # the lexical import producer; absent/resolved rows retain the
        # ordinary Floor law below.
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
        from sugar_lift_py_tests.floor.object_identity import arrived_outcome

        # What an attribute holds was stored by code this frame may not see:
        # the value reaches the read by binding.  The receiver answers the
        # read, whatever bound it: a symbolic receiver -- a module alias with
        # no member receipt (``import sys``; ``sys.maxsize``) as much as a
        # formal -- is the one two-faced undecided read
        # (``floor_value.undecided_attribute_result``).
        return arrived_outcome(receiver.attribute(name, site, ctx), site)

    def desugar(self, ctx: object = None) -> ExitSet:
        return self.receiver.desugar(ctx).and_then(
            lambda receiver: self.project_attribute(receiver, self.name, self.site, ctx)
        )


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
