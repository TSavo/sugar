"""A missing corpus is a broken environment, not a reason to report green.

``pytest.skip(f"{package}: not installed at {path}")`` answers *"is it
present"* when the suite is asking *"did this law run"*. That is the same shape
as ``dpkg-query`` answering "did apt install b3sum" when the build asked "is
b3sum usable" -- and it is worse than the uid guards, because a missing corpus
is a *routine* condition. A law skipped whenever numpy or pandas is absent is
unrun on every machine that lacks them, permanently and silently, and nobody
ever sees a red.

numpy and pandas are not optional here. ``sugar-build.toml`` pins them
(``numpy = "2.5.1"``, ``pandas = "3.0.3"``) and
``sugar-lift-py-tests/pyproject.toml`` declares them under a table that calls
itself THE SOLE DEPENDENCY AUTHORITY for every CI job touching this package.
The stdlib vendors ship with CPython. The showcase targets are directories in
this checkout. So every one of those absences means the environment is broken,
and the honest report is a failure that names what is missing and why it was
expected -- never a smaller suite.

Three categories, and only three:

    require_declared_corpus  -- it was declared, so its absence is a FAILURE.
    optional_law_skip        -- genuinely conditional, so the skip is NAMED
                                and COUNTED, never silent.
    optional_law_import      -- the same, for a law whose condition IS an
                                importable provider. ``pytest.importorskip``
                                is this shape done anonymously: it answers
                                "is it present" and leaves no bucket saying
                                the law did not run.

``tests/test_no_law_goes_unrun.py`` at the repo root enforces
that no other skip shape enters the corpus.
"""

from __future__ import annotations

import pytest

# The sanctioned conditional categories. A skip outside these is a law nobody
# decided to leave unrun -- which is the defect, not the exception.
HEAVY_OPT_IN = "heavy-opt-in"
HOST_GRAMMAR = "host-grammar"
# A pluggable backend the architecture declares must never be required.
# sugar-source-tree's pyproject states it outright: "The core membrane stays
# stdlib-only. A PROVIDER is an optional extra: installing one must never be a
# condition of the membrane working, and the membrane must never depend on any
# single parser." A law about ONE provider is therefore genuinely conditional
# -- but it is still counted, so nobody mistakes an absent provider for a
# passing backend.
OPTIONAL_PROVIDER = "optional-provider"

OPTIONAL_LAW_CATEGORIES = frozenset({HEAVY_OPT_IN, HOST_GRAMMAR, OPTIONAL_PROVIDER})


class DeclaredCorpusMissing(AssertionError):
    """A corpus the environment promised to provide was not there.

    An ``AssertionError``, so it lands as a FAILURE. Skipping here would report
    an unrun law as green in exactly the environments that were supposed to run
    it.
    """


def require_declared_corpus(what, where, declared_by, remedy):
    """Refuse by name when a declared corpus is absent.

    ``declared_by`` is the point of the refusal: it names the contract that
    promised this would be present, so the reader learns whether to fix the
    environment or to change the declaration -- rather than reaching for the
    workaround that makes the law silently stop running.
    """
    raise DeclaredCorpusMissing(
        f"declared corpus missing: {what} (looked at {where}). "
        f"It is declared by {declared_by}, so its absence means the "
        f"environment is broken, not that this law is inapplicable. "
        f"replacement: {remedy}. Do NOT convert this back into a skip: a "
        f"skipped law reports green on every machine that lacks the corpus, "
        f"which is how a whole class of laws stops running unnoticed."
    )


def optional_law_skip(category, reason):
    """Skip a genuinely conditional law, named and counted.

    The category is mandatory and comes from a closed set, so the skip is a
    reported bucket rather than an anonymous absence: ``pytest -rs`` groups
    them and they can be counted per category.
    """
    if category not in OPTIONAL_LAW_CATEGORIES:
        raise DeclaredCorpusMissing(
            f"unsanctioned skip category {category!r}; a law may only be left "
            f"unrun under a named category from {sorted(OPTIONAL_LAW_CATEGORIES)}. "
            "Anything else is an unrun law reported as green."
        )
    pytest.skip(f"[{category}] {reason}")


def optional_law_skipif(condition, category, reason):
    """``pytest.mark.skipif`` counterpart, carrying the same named category."""
    if category not in OPTIONAL_LAW_CATEGORIES:
        raise DeclaredCorpusMissing(
            f"unsanctioned skip category {category!r}; a law may only be left "
            f"unrun under a named category from {sorted(OPTIONAL_LAW_CATEGORIES)}."
        )
    return pytest.mark.skipif(condition, reason=f"[{category}] {reason}")


def optional_law_import(module_name, category, reason=None):
    """Import a provider, or skip under a NAMED, COUNTED category.

    ``pytest.importorskip`` is exactly this without the name: the law stops
    running and the report carries no bucket saying so. Returns the module, so
    it substitutes directly at a call site.
    """
    import importlib

    if category not in OPTIONAL_LAW_CATEGORIES:
        raise DeclaredCorpusMissing(
            f"unsanctioned skip category {category!r}; a law may only be left "
            f"unrun under a named category from {sorted(OPTIONAL_LAW_CATEGORIES)}."
        )
    try:
        return importlib.import_module(module_name)
    except ImportError:
        # allow_module_level, because a provider gate is normally evaluated at
        # module scope -- that is what importorskip did, and without the flag
        # pytest turns the skip into a COLLECTION ERROR, which shrinks the
        # denominator instead of reporting a counted skip.
        pytest.skip(
            f"[{category}] {reason or f'{module_name} not installed'}",
            allow_module_level=True,
        )
