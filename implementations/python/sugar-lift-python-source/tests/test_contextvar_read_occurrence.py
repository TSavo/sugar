"""Each ``ContextVar.get()`` read is keyed by its own call site.

``format_options.get()`` reached through an import use is applied as a
``CallableApplication``, which carries its site as ``site``, not ``blame``;
the read was minted with an empty occurrence, so every such read in numpy
shared one term and two reads were claimed equal.  The bound method now takes
the application's site, and a read with no site at all refuses instead of
sharing a term.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.callable_application import CallableApplication
from sugar_lift_py_tests.floor.language_owned_contextvar import (
    LanguageOwnedContextVarMethodValue,
    LanguageOwnedContextVarReadValue,
    LanguageOwnedContextVarValue,
)
from sugar_lift_py_tests.occurrence import occurrence_key
from sugar_lift_py_tests.outcome import Complete
from sugar_source_tree.panic import SugarNotWritten


def _get(site):
    method = LanguageOwnedContextVarMethodValue(
        variable=LanguageOwnedContextVarValue(name="v", has_default=True),
        method="get",
    )
    return method.callable_application_with(CallableApplication((), (), site=site), None)


def test_a_read_through_an_application_is_keyed_by_its_site():
    outcome = _get("site-a")
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, LanguageOwnedContextVarReadValue)
    assert outcome.value.occurrence == occurrence_key("site-a")


def test_two_sites_are_two_reads():
    left = _get("site-a").value.to_term(owner="t")
    right = _get("site-b").value.to_term(owner="t")
    assert left != right


def test_a_read_with_no_site_refuses():
    with pytest.raises(SugarNotWritten, match="no call site"):
        _get(None)
