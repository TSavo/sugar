"""A closed import-bound module member coordinate.

The lexical import pass authenticates the head; the static Attribute chain
names the export path.  This floor carries that joined coordinate without
re-asking an opaque module receiver for a member and without inventing
AttributeError.

Operations on this floor share one door: the export is source-authenticated
but its runtime type is not lift-time decided (``runtime_type_is_decided`` is
False). Lookups use the existing undecided_* named-refusal helpers. Call,
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
        chosen and no ``KeyError`` is guessed.  A key with no term, or a
        subscript with no site to key the atom on, stays named-loud.
        """
        from sugar_lift_py_tests.floor.call_site_value import _opaque_subscript_faces
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_source_tree.panic import SugarNotWritten

        if site is None:
            return self.undecided_subscript(
                index, site, owner="ImportMemberValue.subscript"
            )
        try:
            term = ctor(
                "py.subscript",
                [
                    self.to_term(owner="ImportMemberValue.subscript"),
                    index.to_term(owner="ImportMemberValue.subscript"),
                ],
            )
        except SugarNotWritten:
            return self.undecided_subscript(
                index, site, owner="ImportMemberValue.subscript"
            )
        return _opaque_subscript_faces(
            ExitSet.completed(SymbolicValue(term)),
            site,
            producer="ImportMemberValue.subscript",
        )

    def attribute(self, name, site):
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
        its ``LanguageCallee``.  Recognition hands a decidable call to that
        operation; an undecidable one (symbolic operand, or a pattern outside
        the decided subset) falls through to the ordinary import-member
        runtime-effect boundary -- never a guess."""
        from sugar_source_tree.nodes import LanguageCallee

        return {
            LanguageCallee.RE_SEARCH: "python.re.search",
            LanguageCallee.RE_MATCH: "python.re.match",
            LanguageCallee.RE_FULLMATCH: "python.re.fullmatch",
        }.get(language_callee)

    def callable_application_with(self, operation: Any, ctx: object):
        """Call-through-import: a recognized C-floor semantic when the call is
        DECIDABLE, else the ordinary boundary effect.

        Runtime type is undecided at lift for an arbitrary import member, so the
        default door names the ImportMemberCallEffect boundary and invents no
        CallSite. But a small closed set of C-floor callables (``re.search`` and
        friends) have language-owned semantics; when THIS authenticated member
        is one of them and its operands are concrete, decide it here.

        ``typing.final(f)`` tries ``f.__final__ = True``, swallows the failure,
        and returns ``f``: the call is its one positional operand.  The
        ``__final__`` marker is not carried on the returned floor.
        """
        from sugar_source_tree.nodes import LanguageCallee

        language_callee = self.language_callee()
        if (
            language_callee is LanguageCallee.TYPING_FINAL
            and not operation.keyword_names
            and len(operation.arguments) == 1
        ):
            from sugar_lift_py_tests.outcome import ExitSet

            return ExitSet.completed(operation.arguments[0])
        operation_name = self.c_floor_semantic_operation(language_callee)
        if operation_name is not None:
            decided = self._decide_c_floor_semantic(operation_name, operation, ctx)
            if decided is not None:
                return decided
        del ctx
        return _import_member_runtime_effect(
            self,
            site=operation.site,
            shape=f"{self.qualified_name}(...)",
            replacement="ImportMemberCallEffect",
        )

    def _decide_c_floor_semantic(self, operation_name, operation, ctx):
        """Apply the language-owned semantic when the call is decidable; return
        ``None`` to fall through to the undecided boundary effect.

        Decidable means: the semantic's own operand contract is satisfied
        (arity, concrete ``str`` operands) AND -- for ``re`` -- the pattern is
        in the decided subset. Anything else is a genuine undecided at THIS
        boundary, not our missing floor, so it stays a runtime effect."""
        from sugar_lift_py_tests.floor.builtin_semantic_callable import (
            BuiltinSemanticCallable,
        )
        from sugar_lift_py_tests.floor.re_subset_matcher import (
            UnsupportedRegexInput,
            UnsupportedRegexPattern,
            validate_pattern,
        )
        from sugar_lift_py_tests.floor.string_value import StringValue
        from sugar_lift_py_tests.gap.panic import ConstructionPanic

        if operation.keyword_names or len(operation.arguments) < 2:
            return None
        # re.search(pattern, string[, flags]) -- flags beyond the subset make it
        # undecided here, not a panic. Only the two-operand concrete form is
        # decided; a third (flags) operand keeps the boundary.
        if len(operation.arguments) != 2:
            return None
        pattern_v, subject_v = operation.arguments
        if not isinstance(pattern_v, StringValue) or not isinstance(
            subject_v, StringValue
        ):
            return None
        try:
            validate_pattern(pattern_v.value)
        except (UnsupportedRegexPattern, UnsupportedRegexInput):
            return None
        callee = BuiltinSemanticCallable(operation=operation_name)
        try:
            return callee.callable_application_with(operation, ctx)
        except ConstructionPanic:
            # The subset authority already cleared this call; a panic here would
            # be a real defect, not an undecided -- do not swallow it.
            raise

    def iter_with(self, operation: Any, ctx: object):
        del ctx
        return _import_member_runtime_effect(
            self,
            site=operation.site,
            shape=f"iter({self.qualified_name})",
            replacement="ImportMemberIterEffect",
        )

    def equals(self, other, site):
        """Comparison constructs on the authenticated term, not runtime type.

        Equality uses content-addressed import-member terms already carried by
        ``to_term`` — no runtime-type decision required.
        """
        return super().equals(other, site)


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
