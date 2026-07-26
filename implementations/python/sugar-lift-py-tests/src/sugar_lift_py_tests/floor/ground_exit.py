from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sugar_lift_py_tests.outcome import Outcome


def ground_raise_effect(*, exception_name: str, site, owner: str):
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
    return RaiseEffect(exception_name, str(site), source_sha256)


def ground_exceptional_exit(*, exception_name: str, site, owner: str) -> Outcome:
    """The whole ground exit: the cited effect plus its exception value."""
    from sugar_lift_py_tests.floor import ExceptionValue, RaiseValue
    from sugar_lift_py_tests.outcome import Complete

    return Complete(
        RaiseValue(
            ground_raise_effect(exception_name=exception_name, site=site, owner=owner),
            exception=ExceptionValue(exception_name, (), site),
        )
    )
