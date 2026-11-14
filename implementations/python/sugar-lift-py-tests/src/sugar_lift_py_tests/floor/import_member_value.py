"""A closed import-bound module member coordinate.

The lexical import pass authenticates the head; the static Attribute chain
names the export path.  This floor carries that joined coordinate without
re-asking an opaque module receiver for a member and without inventing
AttributeError.

Operations on this floor share one door: the export is source-authenticated
but its runtime type is not lift-time decided (``runtime_type_is_decided`` is
False). Lookups use the existing undecided_* two-faced helpers. Call,
iteration, and method dispatch stay at the import-member runtime boundary —
never invent CallSite / MethodCall construction here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sugar_lift_py_tests.call_symbol import call_symbol

from .floor_value import FloorValue

_IMPORT_MEMBER_AUTHORITY = object()


@dataclass(frozen=True)
class ImportMemberValue(FloorValue):
    """Source-authenticated ``module.attr[.attr…]`` export coordinate."""

    qualified_name: str
    source_cid: str
    import_binding_cid: str
    use_cid: str
    exported_member_path: tuple[str, ...]
    receipt: object = field(compare=False, repr=False)
    _authority: object = field(
        default=None, compare=False, repr=False,
        metadata={"testimony": "authority"},
    )

    def __post_init__(self):
        from sugar_lift_py_tests.import_binding import AuthenticatedImportUseV1

        if self._authority is not _IMPORT_MEMBER_AUTHORITY:
            raise ValueError("ImportMemberValue is not producer-minted")
        if type(self.receipt) is not AuthenticatedImportUseV1:
            raise TypeError("ImportMemberValue requires exact authenticated receipt")
        self.receipt.revalidate()
        if (
            self.qualified_name != self.receipt.target_symbol.removeprefix("python:")
            or self.source_cid != self.receipt.source_cid
            or self.import_binding_cid != self.receipt.import_binding.cid
            or self.use_cid != self.receipt.use["cid"]
            or self.exported_member_path
            != _import_member_export_path(self.receipt)
        ):
            raise ValueError("ImportMemberValue receipt authority mismatch")

    def denotes_value(self) -> bool:
        """An import-bound export denotes a runtime value at the member path."""
        return True

    def runtime_type_is_decided(self) -> bool:
        """Module export runtime type is not lift-time decided from the path alone."""
        return False

    def test_python_type(self, value, site):
        """Cite this export as the isinstance type operand.

        The source used the import as classinfo. The type identity is the
        authenticated qualified name (``re.Pattern``), not a free ``Pattern``
        Var. A ground string answers False for any authenticated type other
        than ``str``.
        """
        from sugar_lift_py_tests.ir import ctor, str_const

        return value.python_isinstance(
            self.qualified_name,
            ctor("python:type", [str_const(self.qualified_name)]),
            site,
        )

    def to_term(self, *, owner: str):
        """``ref:<target_symbol>``: a closed reference to the vendor's value,
        in the same family as ``call:<target_symbol>`` (#7837).

        The term names the target and nothing about this occurrence: two reads
        of ``np.float64`` are one reference. The import binding and use stay on
        the receipt; the value is the vendor's, so a claim that depends on it
        stays undecided until the join answers the symbol.
        """
        del owner
        from sugar_lift_py_tests.ir import ctor

        return ctor(f"ref:{self.qualified_name}", [], symbol_kind="coordinate")

    def exception_type_identity(self):
        """The same import coordinate the exception authenticator mints."""
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:exception_type_identity",
            [str_const("import"), str_const(self.qualified_name)],
        )

    # ------------------------------------------------------------------
    # Import-member operations door (one surface; type undecided)
    # ------------------------------------------------------------------
    # Wiring: FloorValue already owns undecided_subscript / undecided_attribute /
    # undecided_contains. ImportMemberValue's only job is to enter those doors
    # instead of the default construction-panic "write more Floor" arm — which
    # would miscount an undecided runtime type as OUR missing floor method.

    def subscript(self, index, site):
        """``mod.member[k]`` over a member whose runtime value is not projected.

        The member's type and ``__getitem__`` are undecided, so the #7587
        opaque-subscript law applies exactly as to a bodiless call result: the
        symbolic ``py.subscript(<member>, <key>)`` completes only under
        ``python:subscript.completes(python:subscript(<term>, <site>))`` and
        the complement halts with an ``UndeterminedRaiseEffect``.  No entry is
        chosen and no ``KeyError`` is guessed: the one undecided read,
        ``undecided_subscript``.  A key with no term refuses by its own name
        (the key's ``to_term`` refusal propagates).
        """
        return self.undecided_subscript(index, site, owner="ImportMemberValue.subscript")

    def attribute(self, name, site, ctx):
        del ctx
        return self.undecided_attribute(name, site, owner="ImportMemberValue.attribute")

    def truth(self, site):
        """``if mod.FLAG:`` stands as ``py.truthy(<member>)``.

        The export's runtime value is not projected, so its truth is not
        decided at lift time. Like a call result's truth, the condition stands
        as the symbolic ``py.truthy`` over the authenticated member coordinate
        and both suites stay reachable under their guards. Nothing is folded:
        the member's value is not guessed.
        """
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import py_truthy
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(
            PredicateValue(
                py_truthy(self.to_term(owner="ImportMemberValue.truth")), site
            )
        )

    def contains(self, item, site):
        return self.undecided_contains(item, site, owner="ImportMemberValue.contains")

    def subscript_with(self, operation: Any, ctx: object):
        del ctx
        return self.subscript(operation.index, operation.site)

    def language_callee(self):
        """The ``LanguageCallee`` this member's authenticated binding names
        (its receipt's target symbol), never its spelling; else ``None``."""
        from sugar_source_tree.nodes import LanguageCallee

        return LanguageCallee.of(self.receipt.target_symbol)

    @staticmethod
    def c_floor_semantic_operation(language_callee) -> str | None:
        """The shared ``BuiltinSemanticCallable`` operation of an authenticated
        C-floor callable whose meaning is language-owned (plan Cut 2), keyed on
        its ``LanguageCallee``.  Recognition hands every call of it to that
        operation (``BuiltinSemanticCallable.re_application``), which decides
        it or states it as the one unanswered call -- never a guess."""
        from sugar_source_tree.nodes import LanguageCallee

        return {
            LanguageCallee.RE_SEARCH: "python.re.search",
            LanguageCallee.RE_MATCH: "python.re.match",
            LanguageCallee.RE_FULLMATCH: "python.re.fullmatch",
        }.get(language_callee)

    def callable_application_with(self, operation: Any, ctx: object):
        """Call-through-import: a recognized C-floor semantic, else the
        ordinary boundary effect.

        Runtime type is undecided at lift for an arbitrary import member, so the
        default door names the ImportMemberCallEffect boundary and invents no
        CallSite. But a small closed set of C-floor callables (``re.search`` and
        friends) have language-owned semantics; when THIS authenticated member
        is one of them, its semantic answers the call.

        A builtin decorator called on one positional operand (``final(f)``
        is ``@final`` spelled as a call) is the one decorator application's
        (``builtin_decorator_application``, #7757): applied where it answers
        (``typing.final`` and ``abc.abstractmethod`` return their operand),
        else the ordinary boundary.
        """
        from sugar_source_tree.nodes import builtin_decorator_application

        language_callee = self.language_callee()
        if (
            language_callee is not None
            and not operation.keyword_names
            and len(operation.arguments) == 1
        ):
            step = builtin_decorator_application(
                language_callee, operation.site, self.qualified_name
            )
            if step.kind == "identity":
                return step.applied(None, operation.arguments[0], ctx)
        operation_name = self.c_floor_semantic_operation(language_callee)
        del ctx
        if operation_name is not None:
            from sugar_lift_py_tests.floor.builtin_semantic_callable import (
                BuiltinSemanticCallable,
            )

            return BuiltinSemanticCallable(operation=operation_name).re_application(
                operation, target_symbol=self.receipt.target_symbol
            )
        return _import_member_runtime_effect(
            self,
            site=operation.site,
            shape=f"{self.qualified_name}(...)",
            replacement="ImportMemberCallEffect",
        )

    def iter_with(self, operation: Any, ctx: object):
        del ctx
        return _import_member_runtime_effect(
            self,
            site=operation.site,
            shape=f"iter({self.qualified_name})",
            replacement="ImportMemberIterEffect",
        )

    def equals(self, other, site, ctx):
        """Comparison constructs on the authenticated term, not runtime type.

        Equality uses content-addressed import-member terms already carried by
        ``to_term`` — no runtime-type decision required.
        """
        return super().equals(other, site, ctx)


def _import_member_runtime_effect(
    value: ImportMemberValue, *, site, shape: str, replacement: str
):
    """Shared incomplete for ops that would require evaluating the export."""
    from sugar_lift_py_tests.effect import (
        ImportedModuleRuntimeEffect,
        runtime_effect_evidence_from_terms,
    )
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.outcome import ExitSet

    member = value.to_term(owner="ImportMemberRuntimeEffect")
    operand = ctor(call_symbol("import_member"), [member])
    return ExitSet.halted(
        ImportedModuleRuntimeEffect(
            "import-member runtime boundary: "
            f"`{shape}` requires evaluating authenticated export "
            f"`{value.qualified_name}` (path={value.exported_member_path!r}). "
            "Runtime type is not lift-time decided; source hunting is cut. "
            f"replacement={replacement}; blame={site}",
            **runtime_effect_evidence_from_terms(
                ctor(
                    "python:import_member_floor_operation",
                    [operand, str_const(replacement), str_const(shape)],
                ),
                operand,
                site,
            ),
        )
    )


def _import_member_export_path(receipt) -> tuple[str, ...]:
    """Member path from the use (``re.Pattern``) or the ImportFrom binding.

    A Name use of ``from re import Pattern`` stores an empty
    ``exportedMemberPath`` on the use; the binding already carries
    ``exportedPath=["Pattern"]``. A module-alias Name (``import re``) has
    an empty path on both and is not an import member.
    """
    use_path = tuple(receipt.use.get("exportedMemberPath") or ())
    if use_path:
        return use_path
    value = receipt.import_binding.to_value()
    target = value.get("target")
    if not isinstance(target, dict):
        return ()
    path = target.get("exportedPath")
    if not isinstance(path, list) or any(
        not isinstance(part, str) or not part for part in path
    ):
        return ()
    return tuple(path)


def _mint_import_member_value(receipt):
    """Module-private producer door from exact lexical import testimony."""
    from sugar_lift_py_tests.import_binding import AuthenticatedImportUseV1

    if type(receipt) is not AuthenticatedImportUseV1:
        raise TypeError("ImportMemberValue requires exact authenticated receipt")
    receipt.revalidate()
    target = receipt.target_symbol
    path = _import_member_export_path(receipt)
    if not target.startswith("python:") or not path:
        raise ValueError("ImportMemberValue receipt has no imported member path")
    return ImportMemberValue(
        target.removeprefix("python:"),
        receipt.source_cid,
        receipt.import_binding.cid,
        receipt.use["cid"],
        path,
        receipt,
        _IMPORT_MEMBER_AUTHORITY,
    )
