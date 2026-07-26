"""The mechanism must actually fail, and actually reject unnamed categories.

Without these, ``declared_corpus`` could quietly degrade back into a skip and
every law using it would pass vacuously again -- the same unfalsifiability the
module exists to remove, hidden one layer deeper. The AST guard at the repo
root proves no raw skip remains in the corpus; these prove the replacement has
teeth.
"""

from __future__ import annotations

import pytest

from declared_corpus import (
    HEAVY_OPT_IN,
    HOST_GRAMMAR,
    OPTIONAL_LAW_CATEGORIES,
    DeclaredCorpusMissing,
    optional_law_skip,
    optional_law_skipif,
    require_declared_corpus,
)


def test_a_missing_declared_corpus_fails_and_is_not_a_skip():
    """The whole point: absence of a promised corpus goes RED, not quiet."""
    with pytest.raises(DeclaredCorpusMissing) as caught:
        require_declared_corpus(
            "numpy is not installed",
            "/nonexistent/site-packages/numpy",
            "sugar-build.toml pin",
            "install the package extra",
        )

    assert not isinstance(caught.value, pytest.skip.Exception), (
        "a declared corpus that is missing must FAIL; skipping reports the "
        "law as green on every machine that lacks it"
    )
    assert isinstance(caught.value, AssertionError)


def test_the_refusal_names_the_corpus_the_contract_and_the_remedy():
    """A refusal that does not name its contract teaches the workaround."""
    with pytest.raises(DeclaredCorpusMissing) as caught:
        require_declared_corpus(
            "pandas is not installed",
            "/nonexistent/pandas",
            "sugar-build.toml (pandas = 3.0.3)",
            "pip install -e '...[test]'",
        )

    message = str(caught.value)
    assert "pandas is not installed" in message
    assert "/nonexistent/pandas" in message
    assert "sugar-build.toml (pandas = 3.0.3)" in message
    assert "pip install -e '...[test]'" in message
    assert "Do NOT convert this back into a skip" in message


def test_an_unsanctioned_skip_category_is_refused():
    """Categories come from a closed set, or the bucket means nothing."""
    with pytest.raises(DeclaredCorpusMissing) as caught:
        optional_law_skip("because-i-said-so", "no reason")

    assert "unsanctioned skip category" in str(caught.value)

    with pytest.raises(DeclaredCorpusMissing):
        optional_law_skipif(True, "because-i-said-so", "no reason")


def test_a_sanctioned_skip_carries_its_named_category():
    """The skip is counted: ``pytest -rs`` groups it under the category."""
    with pytest.raises(pytest.skip.Exception) as caught:
        optional_law_skip(HEAVY_OPT_IN, "set SUGAR_4013_HEAVY_PANDAS=1")

    assert f"[{HEAVY_OPT_IN}]" in str(caught.value)
    assert "set SUGAR_4013_HEAVY_PANDAS=1" in str(caught.value)

    mark = optional_law_skipif(True, HOST_GRAMMAR, "needs except* (3.11+)")
    assert f"[{HOST_GRAMMAR}]" in mark.kwargs["reason"]


def test_the_category_set_is_closed_and_small():
    """A category set that grows freely is an unnamed skip with extra steps."""
    assert OPTIONAL_LAW_CATEGORIES == {HEAVY_OPT_IN, HOST_GRAMMAR}
