"""``for_test_without_workspace()`` may not be used where a workspace IS reachable.

The constructor's name is a claim: *this caller has no workspace*. Its docstring
says the claim must be true per caller, but a docstring does not fail CI and
"read every caller carefully" is an obligation that decays the moment someone is
in a hurry. This is that obligation as a mechanism.

THE DISCRIMINATOR, established by running both arms rather than by reading::

    SourceFile(workspace_path_source(str(path), root=str(tmp_path)))

    for_test_without_workspace()  ->  bridge_source_symbol = None
    a real workspace context      ->  bridge_source_symbol = 'python:subject_mod.f'

``workspace_path_source`` seats a RELATIVE locus, so the absolute-locus refusal
that makes the claim safe elsewhere never fires, and a richer value is genuinely
reachable. Asserting "no workspace" at a site that names its own root is a false
claim in the name of the constructor -- the one thing it must never be used for.

WHY THIS ONE CANNOT BE A READ-SITE GUARD, unlike every other check on this
branch. The deciding fact is *did the caller have a root*, and that fact is not
present at the seat. ``workspace_path_source(path, root=...)`` and an invented
literal both seat a RELATIVE filename -- `'subject_mod.py'` and `'lying.py'` are
indistinguishable strings by the time construction runs. One has a workspace
behind it and the other names a module that exists nowhere, and nothing in the
identity tuple records which.

So the enforcement is syntactic, and it is sound for a syntactic reason: ``root``
is a REQUIRED keyword-only parameter of ``workspace_path_source``. Its presence
in the call is proof that a root was in hand. That is a fact about the source
text, decidable exactly where it is written and nowhere later.

Stated plainly because it cuts against the lesson of the rest of this work: the
read-site guard beat static scanning everywhere else tonight. Here the read site
has strictly less information than the call site, so the scan is not a weaker
substitute -- it is the only place the question can be asked.

THE BOUNDARY ON THE DOCTRINE, which this file is the first instance of::

    enforce at the READ when the deciding fact survives to the read
    enforce at the CALL when the call is where the fact exists

Reading-is-enrollment beat every scan elsewhere on this branch, twice finding
shapes no scan could see. It inverts here because the deciding fact is destroyed
before construction runs.

WHAT THIS GUARD DOES NOT COVER, named because a guard that silently misses a
shape is worse than one that states its limit.

It cannot see the AUTHENTICATED-CORPUS shape::

    corpus = authenticated_pandas_corpus()
    path = corpus.root / CORPUS_REL
    tree = SourceFile((source, str(path), source_cid))

That is a real installed module, at a real path, with a root in hand -- the most
workspace-bearing shape found, and the falsest place the no-workspace claim
could be made. But it hands over an ALREADY-BUILT identity tuple, so no
``workspace_path_source`` appears at the call and there is nothing here to match.

The limit is pinned rather than widened because the tuple **erases the
provenance by construction**: ``(source, str(path), cid)`` records no trace of
whether ``source`` came from a corpus read or a string literal, and recovering
it needs dataflow, not a scan. A syntactic rule broad enough to catch it -- say,
"the filename element is not a literal" -- also flags legitimate synthetic seats
like ``seat = f"{name}.py"``, and a guard that cries wolf is one people learn to
silence. Catching this shape needs provenance carried on the identity, which is
a change to the oracle and not to this file.

Until then it is a READING obligation, and it is discharged by reading: the 41
callers migrated under #7396 were re-checked at SITE granularity for exactly
this shape and none of them reads a corpus, an installed module, or ``__file__``.
"""

from __future__ import annotations

import pathlib

CLAIM = "for_test_without_workspace()"
ROOTED = "workspace_path_source("
OPENERS = ("SourceFile(", "SourceFile.from_path(")

SUITES = (
    "sugar-source-tree",
    "sugar-lift-py-tests",
    "sugar-lift-python-source",
)


def _python_root() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    for parent in here.parents:
        if parent.name == "python" and (parent / "sugar-source-tree").is_dir():
            return parent
    raise AssertionError(f"cannot locate implementations/python from {here}")


def _calls(text: str, opener: str):
    """Every balanced ``opener(...)`` call in ``text``, as source strings."""
    index = 0
    while True:
        start = text.find(opener, index)
        if start < 0:
            return
        cursor = start + len(opener)
        depth = 1
        while depth and cursor < len(text):
            char = text[cursor]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            cursor += 1
        yield text[start:cursor]
        index = cursor


def _offenders() -> list[str]:
    found: list[str] = []
    root = _python_root()
    for suite in SUITES:
        tests = root / suite / "tests"
        if not tests.is_dir():
            continue
        for path in sorted(tests.rglob("*.py")):
            if path.name == pathlib.Path(__file__).name:
                # This file. Its planted fixture in
                # test_the_guard_can_actually_fail is a STRING exhibiting the
                # forbidden shape -- exhibiting it is how the guard is proved
                # non-vacuous, and there is no other way to prove that. It is
                # not a call site: nothing here constructs.
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if CLAIM not in text or ROOTED not in text:
                continue
            for opener in OPENERS:
                for call in _calls(text, opener):
                    if CLAIM in call and ROOTED in call:
                        line = text[: text.index(call)].count("\n") + 1
                        found.append(f"{suite}/tests/{path.name}:{line}")
    return found


def test_the_no_workspace_claim_is_not_made_where_a_root_is_in_hand() -> None:
    """THE GUARD. Also the retroactive check on every already-migrated caller.

    A failure here is not a lint nit. It is a site asserting "no workspace"
    while holding one, which constructs ``bridge_source_symbol=None`` where a
    real symbol was reachable -- a second, poorer answer for the same source,
    with no refusal to mark it.
    """
    offenders = _offenders()
    print("\n=== no-workspace claim made while holding a root ===")
    print(f"    offending sites: {len(offenders)}")
    for site in offenders:
        print(f"      {site}")
    assert offenders == [], (
        "for_test_without_workspace() is used in a call whose identity comes "
        "from workspace_path_source(..., root=...). `root` is a REQUIRED "
        "keyword there, so a workspace IS in hand and a real bridge identity "
        "was reachable. The honest repair is a real workspace context (or "
        "open_source_file_for_construction) -- never this constructor, whose "
        "whole meaning is that no workspace exists:\n  "
        + "\n  ".join(offenders)
    )


def test_the_guard_can_actually_fail() -> None:
    """A containment check that cannot fail proves nothing.

    The scan above reports zero only if zero is true, so this exercises the
    matcher on a planted site with the exact shape it must catch, including the
    multi-line form -- which is how the real ones are written.
    """
    planted = (
        "tree = SourceFile(\n"
        "    workspace_path_source(str(path), root=str(tmp_path)),\n"
        "    construction_context="
        "TreeConstructionContextV1.for_test_without_workspace(),\n"
        ")\n"
    )
    hits = [
        call
        for call in _calls(planted, "SourceFile(")
        if CLAIM in call and ROOTED in call
    ]
    assert hits, "the matcher missed a planted offender -- the guard is vacuous"

    clean = (
        "tree = SourceFile(\n"
        "    path_source(str(path)),\n"
        "    construction_context="
        "TreeConstructionContextV1.for_test_without_workspace(),\n"
        ")\n"
    )
    assert not [
        call
        for call in _calls(clean, "SourceFile(")
        if CLAIM in call and ROOTED in call
    ], "the matcher flags an absolute-locus caller, which is legitimately exempt"
