from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sugar_lift_py_tests.outcome import ExitSet


def _builtin_exception_identity(exception_name: str):
    """Authenticated builtins identity + MRO for a language-owned exception class.

    Ground floors mint exceptions by language law (``1 + "a"`` → TypeError), not
    by reducing a ``raise TypeError(...)`` child.  The assertion boundary matches
    by ``python:exception_type_identity`` coordinates — the same ones
    ``SourceUnit.exception_type_identity`` publishes for the ``pytest.raises``
    expected operand — so the ground door must carry that coordinate or every
    producer → ExitSet → boundary route refuses matching.
    """
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.temporal.builtin_name_bindings import (
        BUILTIN_EXCEPTION_BASES,
        BUILTIN_EXCEPTION_NAMES,
    )

    if exception_name not in BUILTIN_EXCEPTION_NAMES:
        return None, None
    from sugar_lift_py_tests.temporal.builtin_name_bindings import (
        canonical_builtin_exception_name,
    )

    exception_name = canonical_builtin_exception_name(exception_name)

    def identity(name: str):
        return ctor(
            "python:exception_type_identity",
            [str_const("builtins"), str_const(name)],
        )

    # Linearize the closed bases table: leaf first, then each ancestor once.
    ordered: list[str] = []
    seen: set[str] = set()

    def walk(name: str) -> None:
        if name in seen:
            return
        seen.add(name)
        ordered.append(name)
        for base in BUILTIN_EXCEPTION_BASES.get(name, ()):
            walk(base)

    walk(exception_name)
    return identity(exception_name), tuple(identity(name) for name in ordered)


def ground_raise_effect(*, exception_name: str, site, owner: str, raised_value=None):
    """The ONE door that mints a ground exceptional exit's `RaiseEffect`.

    Every ground exit -- IndexError from a proved out-of-bounds constant
    subscript, AssertionError from a proved-false assert, TypeError from
    ``None[...]``, ZeroDivisionError from a proved-zero divisor -- cites the
    same two things: a source locus and the text that locus indexes into.
    They were five copies of one block, which is why they also carried five
    copies of one bug: each read ``site.source``, and a ``SourceFragment``
    has no ``source``. The read was dead because the locus law below always
    fired first on the corpus, so the broken citation never ran. The text
    lives on the fragment's ``unit`` (as ``RaiseSugar`` already reads it).

    The locus law: a ground exit's blame must be workspace-relative. A
    ``SourceMemento`` addresses ``{file, span}`` relative to the workspace and
    ``resolve_span_memento`` re-reads it as ``project_root / file``, so an
    absolute locus is not a longer spelling of the same address -- it is an
    address no other checkout can resolve. An absolute locus means the source
    did not come through ``workspace_path_source``; that stays LOUD, because
    the alternative is a citation that silently cannot be checked.
    """
    import hashlib
    from pathlib import Path

    from sugar_lift_py_tests.effect import RaiseEffect
    from sugar_lift_py_tests.gap.panic import construction_panic_gap

    # A ground exit cites source it can RE-READ: a filename to address and the
    # unit holding the text that filename indexes into. A locus that states
    # neither -- prose, a bare string, anything not carrying a fragment's
    # testimony -- cannot produce that citation at all. Before this arm the
    # locus law below read ``site.filename`` first and died with
    # ``AttributeError: 'str' object has no attribute 'filename'``: a crash
    # wearing a law's clothes, which says nothing about what was wrong or what
    # to thread instead. The requirement is stated, not tripped over.
    filename = getattr(site, "filename", None)
    unit = getattr(site, "unit", None)
    if not isinstance(filename, str) or unit is None:
        construction_panic_gap(
            owner=owner,
            blame=site,
            observed=f"{type(site).__name__} locus stating no source fragment",
            requested="a fragment stating filename and unit",
            fix=(
                "thread the fragment that owns the boundary; a ground exit "
                "cites source it can re-read, which prose cannot address"
            ),
        )
    if Path(filename).is_absolute():
        construction_panic_gap(
            owner=owner,
            blame=site,
            observed="absolute source locus",
            requested="workspace-relative source locus",
            fix="route the source through the workspace-relative lift door",
        )
    source = unit.source
    source_sha256 = (
        hashlib.sha256(source.encode()).hexdigest() if source is not None else None
    )
    blame = str(site)
    type_coordinate, type_mro = _builtin_exception_identity(exception_name)
    if type_coordinate is None:
        construction_panic_gap(
            owner=owner,
            blame=site,
            observed=f"ground exit for {exception_name!r} has no exception_type_identity",
            requested="a language-owned exception with python:exception_type_identity",
            fix="use a builtin exception name or supply authenticated coordinate",
        )
    from sugar_lift_py_tests.effect.authenticated_raise_locus import (
        AuthenticatedRaiseLocus,
    )

    return RaiseEffect(
        exception_type_coordinate=type_coordinate,
        occurrence=AuthenticatedRaiseLocus.of(blame),
        exception_name=exception_name,
        blame=blame,
        source_sha256=source_sha256,
        exception_type_mro=type_mro,
        raised_value=raised_value,
        producer_node_owner=owner,
    )


def ground_exceptional_exit(*, exception_name: str, site, owner: str) -> ExitSet:
    """The whole ground exit: a halt with the cited effect.

    A raise is never a completion.  The effect carries the exception value it
    raises (``raised_value``), which is what an ``except`` clause tests and an
    ``as`` name binds.  The enclosing statement turns the halt into its
    ``Halted`` face, with the state before it.
    """
    from sugar_lift_py_tests.floor import ExceptionValue
    from sugar_lift_py_tests.outcome import ExitSet

    return ExitSet.halted(
        ground_raise_effect(
            exception_name=exception_name,
            site=site,
            owner=owner,
            raised_value=ExceptionValue(exception_name, (), site),
        )
    )


def ground_type_error(*, site, owner: str) -> ExitSet:
    """Authenticated TypeError partition for a source-decided ground pair.

    Ground cross-type operations that Python rejects (``1 < "a"``, ``None + 1``,
    ``[] + 0``, ``~3.5`` for bitwise invert on float) are not RuntimeEffects:
    both operand types are lift-time decided, so the expression halts with a
    cited TypeError.  Undecided native dispatch stays on the named-refusal
    / construction-panic laws; this door is only for the decided TypeError.
    """
    return ground_exceptional_exit(exception_name="TypeError", site=site, owner=owner)
