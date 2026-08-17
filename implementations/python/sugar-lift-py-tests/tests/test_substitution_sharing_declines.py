"""WHERE SUBSTITUTION SHARING DECLINES TO SHARE.

``Node._substituted_child`` answers ``child.substitute(scope)`` once per
(child, scope) pair, which is what removes the ``u^N`` re-descent of an
already-threaded term (#7411). The whole safety of that memo is the second
half of its key: A DIFFERENT SCOPE IS A DIFFERENT QUESTION, and must be asked
again.

Both sides of the discriminator are here on purpose. The declining side alone
would pass for a memo that never hits at all; the sharing side alone would
pass for a memo that shares unconditionally. Only the pair says anything.

Identity is compared on ``ref``, never on the Node shell: shells are VIEWS
(``backend.materialize`` mints a fresh one per access over a shared field
row), so ``is`` on a shell tests nothing about whether work was shared.
"""

from __future__ import annotations

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Constant, FunctionDef, Return
from sugar_source_tree.tree import SourceFile


def _function(source: str, name: str, filename: str) -> FunctionDef:
    tree = SourceFile((source, filename, blake3_512_of(source.encode())))
    return next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == name
    )


def _two_actuals():
    """Two genuinely distinct bound terms, from two source occurrences."""
    source = "a = 11\nb = 22\n"
    module = SourceFile((source, "actuals.py", blake3_512_of(source.encode())))
    eleven, twenty_two = (
        node for node in module.nodes() if isinstance(node, Constant)
    )
    assert eleven.ref is not twenty_two.ref
    return eleven, twenty_two


def _returned(function: FunctionDef) -> Return:
    return next(node for node in function.walk() if isinstance(node, Return))


# ── DECLINES ──────────────────────────────────────────────────────────────


def test_one_node_two_scopes_gives_two_answers() -> None:
    """THE falsifier. ONE ``return q`` node, TWO scopes binding ``q``.

    A memo keyed on the node alone hands the second asker the FIRST asker's
    term -- one frame reading another frame's value. That is a wrong
    construction, not a slow one, so this is the test that must stay red for
    any unconditional sharing.
    """
    helper = _function("def helper():\n    return q\n", "helper", "declines.py")
    eleven, twenty_two = _two_actuals()

    first = _returned(helper.substitute({"q": eleven}))
    second = _returned(helper.substitute({"q": twenty_two}))

    assert first.value.ref is eleven.ref, "first scope did not reach the return"
    assert second.value.ref is twenty_two.ref, (
        "second scope read the FIRST scope's term through the memo"
    )


def test_a_name_rebound_mid_block_is_not_read_through_the_memo() -> None:
    """A block that rebinds a name between two reads must thread two terms.

    ``_substitute_body_tracked`` mints a FRESH scope per binding, so the second
    read presents a scope the memo has never seen.

    HONEST ABOUT ITS OWN TEETH: this one stayed GREEN under the mutation that
    drops the scope from the memo key. It is protected by the OTHER half of
    the key -- the two reads are two distinct source ``Name`` occurrences, so
    two distinct refs -- and it therefore witnesses the block law, not the
    scope key. ``test_one_node_two_scopes_gives_two_answers`` is the arm with
    teeth for the scope half; it fails under exactly that mutation.
    """
    source = (
        "def subject():\n"
        "    x = 1\n"
        "    first = x\n"
        "    x = 2\n"
        "    second = x\n"
        "    return (first, second)\n"
    )
    subject = _function(source, "subject", "declines_rebind.py")

    returned = _returned(subject.substitute({}))
    rendered = [getattr(element, "value", None) for element in returned.value.elts]

    assert rendered == [1, 2], f"rebind collapsed through the memo: {rendered!r}"


# ── SHARES ────────────────────────────────────────────────────────────────


# The SHARING side of the discriminator is NOT in this file, deliberately.
#
# A first attempt counted ``Call.substitute`` entries while substituting the
# #7411 chain shape directly. It came back GREEN with the memo disabled, which
# means it had no teeth: ONE pass of ``FunctionDef.substitute`` over a chain is
# already linear -- ``Name.substitute`` returns the bound node and never
# descends it. The ``u^N`` re-descent needs the term to be substituted a SECOND
# time, which is what a call frame does when it re-binds formals over an
# already-threaded callee body. A unit test cannot reach that seam without the
# construction context and an authenticated distribution, so a test written
# here would be measuring the wrong pass and reporting it as the right one.
#
# The sharing side is therefore measured where it actually happens, through
# the census entrance, by ``probe-temporal-blowup-shape --synthetic``:
# ``uses=3 nested=True length=12`` costs 21.779s before this memo and 0.151s
# after, and ``length=13`` exhausts a 60s bound before and costs 0.166s after.
