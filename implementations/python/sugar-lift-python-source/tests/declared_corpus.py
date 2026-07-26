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

Two categories, and only two:

    require_declared_corpus  -- it was declared, so its absence is a FAILURE.
    optional_law_skip        -- genuinely conditional, so the skip is NAMED
                                and COUNTED, never silent.

``tests/test_uid_sensitive_laws_are_executed.py`` at the repo root enforces
that no other skip shape enters the corpus.
"""

from __future__ import annotations

import pytest

# The sanctioned conditional categories. A skip outside these is a law nobody
# decided to leave unrun -- which is the defect, not the exception.
HEAVY_OPT_IN = "heavy-opt-in"
HOST_GRAMMAR = "host-grammar"

OPTIONAL_LAW_CATEGORIES = frozenset({HEAVY_OPT_IN, HOST_GRAMMAR})


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
