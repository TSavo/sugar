"""The four ``pytest.raises(..., match=...)`` argument shapes, pinned to real sites.

``match=`` is one of the four assertion-``With`` shapes. Unlike a plain halt,
the ``With`` item carries an *argument expression*, and that expression is where
the resolution question lives: some of them name a value the source can produce,
and some of them name a value only a running frame can produce. Fusing those two
under one number is the failure this module exists to prevent -- an opaque call
that comes back quietly reads exactly like a drained one.

**Four shapes, and why exactly these four.** They are not a taxonomy invented
here; they are what an AST walk of the pinned corpus (pandas 3.0.3) actually
contains at ``raises(..., match=<expr>)``, grouped by what construction has to
do to reach the value:

``literal``
    ``match="whoops"`` -- a ``Constant``. The value is present at the call
    coordinate. Nothing to resolve, and nothing a demand table can change.
``name-ref``
    ``match=match`` -- a ``Name`` bound by an ``Assign`` in the same frame.
    Source-resolvable through the assertion-``With`` observation binding seam
    (#6457, ``649fd4977``), which routes this binding through ``Assign``.
``resolvable-call``
    ``match=re.escape(msg)`` -- a ``Call`` on a free name whose definition the
    authenticated export door can reach. **This is the shape to drain.**
``opaque-call``
    ``match=msg("slice")`` where ``msg`` is bound by the enclosing definition
    itself -- a local (here a lambda) or a parameter. No export lookup can ever
    resolve it, because there is nothing to look up: it is a runtime value.
    ``manager_construction`` already names this condition ``value-call-target``
    and holds it apart from the three coverage-shaped conditions that the old
    fused ``opaque-call-target`` key hid. **This is the shape to leave loud.**

The third and fourth are the pair the whole exercise is about. They are
adjacent in the source -- both are ``Call`` nodes in argument position, both
spell a bare name -- and they are opposite in kind. A drain that cannot tell
them apart drains the second one too, and reports coverage it does not have.

**Sites are real, and pinned by content.** Each row names a concrete pandas
file, line, and the sha256 of that file as enrolled. A synthesized carrier
would be cheaper and would test less: the carrier has no import graph behind
it, so the export door it exercises is not the door the corpus exercises. The
content pin is there because a site that drifts to a different line is a
different site, and a row that silently follows it is testifying about
something nobody chose.

**What is staged and what is not.** Locating the sites and classifying the
argument expression needs no demand table and runs here.

Driving each site through to a *classification* does not run yet, and the
reason is measured rather than assumed. Calling
``populate_source_visible_call_frames`` on each of the four files, unpinned,
completed for all four and installed **nothing** at any of them: zero source
call frames and zero opaque call obligations. The resolvable-call file walked
far enough into the distribution to raise ``SugarNotWritten`` from
``Assign.sugar`` at ``pandas/core/arrays/sparse/array.py:1424:12`` -- a site in
a different file entirely -- and the whole four-file probe took roughly fifteen
minutes. So the pre-table state is not "the drain says opaque"; it is "the
drain says nothing at all", which is precisely the quiet return the owner named
as the failure mode.

Those assertions therefore land when the authenticated table publishes, against
that table and no other -- two owners reading two tables produce two
unfalsifiable results.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pytest

from declared_corpus import require_declared_corpus
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.manager_construction import _frame_bound_names
from sugar_source_tree.nodes import Attribute, Call, Constant, FunctionDef, Name
from sugar_source_tree.tree import SourceFile


@dataclass(frozen=True)
class MatchArgumentSite:
    """One enrolled ``match=`` site: shape, coordinate, and content identity."""

    shape: str
    relative_path: str
    line: int
    #: The ``match=`` argument expression as written, for the reader.
    expression: str
    #: sha256 of the whole enrolled file. Identity is (path, content).
    file_sha256: str
    #: What construction must do with the argument, once the table is shared.
    disposition: str


#: The four shapes, one real site each. ``expression`` is quoted from source.
ENROLLED_SITES: tuple[MatchArgumentSite, ...] = (
    MatchArgumentSite(
        shape="literal",
        relative_path="tests/test_register_accessor.py",
        line=103,
        expression='"whoops"',
        file_sha256="4d2599448c6b329af3822dbc2295fafe142d9ce84e49821c435d9b1c11fea793",
        disposition="resolved-at-site",
    ),
    MatchArgumentSite(
        shape="name-ref",
        relative_path="tests/test_optional_dependency.py",
        line=16,
        expression="match",
        file_sha256="2ec3a6a4425d5c8213c8f3b55b178f978acfe3676168a40d5230104e79ffa029",
        disposition="resolved-through-assign",
    ),
    MatchArgumentSite(
        shape="resolvable-call",
        relative_path="tests/series/test_ufunc.py",
        line=463,
        expression="re.escape(msg)",
        file_sha256="b89a2b0e713bf7663e321c36413af86ac5f2956aa4bab4cab233fa895fabd963",
        disposition="drain",
    ),
    MatchArgumentSite(
        shape="opaque-call",
        relative_path="tests/series/indexing/test_where.py",
        line=242,
        expression='msg("slice")',
        file_sha256="48d7e57a203fe1b9a0401403f4afb3c34029782681c2f0219420602638001c91",
        disposition="typed-loud",
    ),
)


def _corpus_root() -> Path:
    """The enrolled pandas package root, or a named failure.

    pandas is pinned by ``sugar-build.toml`` at 3.0.3 and declared by
    ``sugar-lift-py-tests/pyproject.toml``. Its absence is a broken
    environment, never a smaller suite -- see ``declared_corpus``.
    """
    try:
        import pandas
    except ImportError:
        pandas = None
    if pandas is None or not getattr(pandas, "__file__", None):
        require_declared_corpus(
            what="pandas 3.0.3 source corpus",
            where="the active interpreter's site-packages",
            declared_by=(
                'sugar-build.toml (pandas = "3.0.3") and '
                "sugar-lift-py-tests/pyproject.toml"
            ),
            remedy="install the pinned pandas into the environment under test",
        )
    return Path(pandas.__file__).resolve().parent


def _source_file(path: Path) -> SourceFile:
    """The real file through the real membrane -- no synthesized carrier."""
    source = path.read_text(encoding="utf-8")
    return SourceFile((source, str(path), blake3_512_of(source.encode("utf-8"))))


def _raises_call_on_line(source_file: SourceFile, line: int) -> Call:
    """The outermost ``Call`` beginning on ``line``.

    Shapes three and four put a second ``Call`` on the same line, in argument
    position. Selecting by smallest start column takes the enclosing
    ``raises(...)``; the inner one is reached through its arguments, so the row
    never has to guess which of the two it meant.
    """
    candidates = [
        node
        for node in source_file.nodes()
        if isinstance(node, Call) and node.line_col_span().start_line == line
    ]
    assert candidates, f"no Call begins on line {line}"
    return min(candidates, key=lambda node: node.line_col_span().start_col)


def _match_argument(call: Call):
    """The ``match=`` keyword argument expression of a ``raises`` call."""
    for keyword in call.keywords:
        if keyword.arg == "match":
            return keyword.value
    raise AssertionError("enrolled site carries no match= keyword")


def _callee_root_name(call: Call) -> str:
    """The leftmost name of a callee: ``re`` for ``re.escape``, ``msg`` for ``msg``.

    The root is what binding resolution actually looks up. ``escape`` is an
    attribute of whatever ``re`` turns out to be, so asking about ``escape``
    would ask the wrong question.
    """
    func = call.func
    while isinstance(func, Attribute):
        func = func.value
    assert isinstance(func, Name), f"callee root is {type(func).__name__}, not a Name"
    return func.id


def _enclosing_function(source_file: SourceFile, node) -> FunctionDef:
    """The innermost ``FunctionDef`` whose span contains ``node``.

    ``_frame_bound_names`` answers about one frame, so it has to be given the
    frame the call is actually written in -- not the module and not the class.
    Nodes carry no parent link, so containment is decided by span, and the
    innermost container is the narrowest one that contains the node.
    """
    span = node.span
    containers = [
        candidate
        for candidate in source_file.nodes()
        if isinstance(candidate, FunctionDef)
        and candidate.span.start <= span.start
        and candidate.span.end >= span.end
    ]
    assert containers, "enrolled site is not inside a function definition"
    return min(
        containers, key=lambda candidate: candidate.span.end - candidate.span.start
    )


@pytest.mark.parametrize(
    "site", ENROLLED_SITES, ids=[site.shape for site in ENROLLED_SITES]
)
def test_enrolled_site_still_holds_its_match_argument(
    site: MatchArgumentSite,
) -> None:
    """The pinned coordinate still carries the ``match=`` this row named.

    The expected spelling comes from pandas on disk, not from this test. A row
    whose expected value the test itself supplied would be green whether or not
    anything read the corpus.
    """
    path = _corpus_root() / site.relative_path
    assert path.is_file(), f"enrolled site missing: {path}"
    observed = hashlib.sha256(path.read_bytes()).hexdigest()
    assert observed == site.file_sha256, (
        f"{site.relative_path} is not the file this row enrolled "
        f"(observed {observed}, enrolled {site.file_sha256}). "
        "Re-read the site and re-pin it deliberately -- following a moved "
        "line silently testifies about a site nobody chose."
    )
    argument = _match_argument(_raises_call_on_line(_source_file(path), site.line))
    assert argument.segment().strip() == site.expression


@pytest.mark.parametrize(
    "site", ENROLLED_SITES, ids=[site.shape for site in ENROLLED_SITES]
)
def test_argument_expression_kind_matches_enrolled_shape(
    site: MatchArgumentSite,
) -> None:
    """Each row's shape is the node kind the corpus actually has there."""
    path = _corpus_root() / site.relative_path
    argument = _match_argument(_raises_call_on_line(_source_file(path), site.line))
    expected = {
        "literal": Constant,
        "name-ref": Name,
        "resolvable-call": Call,
        "opaque-call": Call,
    }[site.shape]
    assert isinstance(argument, expected), (
        f"{site.shape} at {site.relative_path}:{site.line} is "
        f"{type(argument).__name__}, not {expected.__name__}"
    )


def test_the_two_call_shapes_are_not_the_same_condition() -> None:
    """The drain pair is distinguishable before any table is consulted.

    Both are ``Call`` nodes spelling a bare name in argument position. What
    separates them is where the callee is bound: ``re.escape`` is free in its
    frame and reaches the export door, ``msg`` is bound by the enclosing
    definition and is a runtime value. If this ever stops holding, the drain
    would consume the opaque site quietly, which is the failure mode the owner
    named.
    """
    root = _corpus_root()
    by_shape = {site.shape: site for site in ENROLLED_SITES}
    resolvable = by_shape["resolvable-call"]
    opaque = by_shape["opaque-call"]

    resolvable_file = _source_file(root / resolvable.relative_path)
    opaque_file = _source_file(root / opaque.relative_path)
    resolvable_arg = _match_argument(
        _raises_call_on_line(resolvable_file, resolvable.line)
    )
    opaque_arg = _match_argument(_raises_call_on_line(opaque_file, opaque.line))

    assert isinstance(resolvable_arg, Call) and isinstance(opaque_arg, Call)

    # The production predicate decides, not a literal restated here. This is
    # the same ``_frame_bound_names`` that ``manager_construction`` consults
    # before installing a source frame, so a change that fuses the two
    # conditions again fails here rather than in a number nobody can audit.
    resolvable_callee = _callee_root_name(resolvable_arg)
    opaque_callee = _callee_root_name(opaque_arg)
    assert resolvable_callee == "re"
    assert opaque_callee == "msg"

    assert opaque_callee in _frame_bound_names(
        _enclosing_function(opaque_file, opaque_arg)
    ), (
        "msg is no longer bound by its enclosing definition; the opaque site "
        "would stop classifying as value-call-target and the drain would "
        "consume it quietly"
    )
    assert resolvable_callee not in _frame_bound_names(
        _enclosing_function(resolvable_file, resolvable_arg)
    ), "re is frame-bound at the resolvable site; it is no longer a free name"
