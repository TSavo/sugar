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
import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest

from declared_corpus import require_declared_corpus
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.manager_construction import (
    CALL_TARGET_GAP_KINDS,
    _CALL_TARGET_GAP_PRECEDENCE,
    _classify_named_call_target,
    _frame_bound_names,
)
from sugar_source_tree.nodes import (
    Attribute,
    Call,
    ClassDef,
    Constant,
    FunctionDef,
    Name,
    With,
)
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


# --------------------------------------------------------------------------
# The drain, against the shared authenticated table.
#
# The table is addressed by CONTENT KEY, never by name. A name lookup returns
# whatever the shelf happens to hold at test time, which is a moving corpus
# wearing a pin's clothes; a content key returns one artifact or nothing.
# --------------------------------------------------------------------------

#: The declared authenticated ``python-demand-table`` identity: producer
#: ``964dbf95d``, corpus pandas 3.0.3 / 1,421 files, parser
#: ``cpython-3.12`` and runtime ``cpython-3.12.13``. The runtime cell must be
#: genuinely re-minted; the former 3.14.4 bytes cannot satisfy this address.
DEMAND_TABLE_CONTENT_KEY = (
    "blake3-512:0ce7c645a7525f1fe5189b808162b49d3fc3ba3d898bfb3d5086e0f295b8b8d"
    "263fe7f530a6aa34adb125615a21e69fdee249e0314bf199b8f43580375153ab0"
)

#: The CONTENT identity of the enrolled corpus: ``corpus_pin.aggregate_hash``
#: over pandas 3.0.3 / 1,421 files. Distribution and version are inside the
#: preimage alongside every file's path, sha256 and size, so an identical file
#: set relabelled as another pandas version does not compare equal. This is
#: the axis that refuses content drift.
CORPUS_AGGREGATE_HASH = (
    "bbb70a76f4032eda3362102c8bd872ca769b6f8143a91f60a36374fa1066b76c"
)

#: The content manifest the regenerated table carries in its authentication
#: block: ordered relative paths plus each file's BLAKE3-512 content CID.
DEMAND_TABLE_CORPUS_MANIFEST_CID = (
    "blake3-512:6f317a5a489eb7e730064d79792f0d1656723130603309e2f2ed9cbedb604eda"
    "1c4b77a26dc90c980411292ea3994af9015da4cd850b5a307af5a4998b563530"
)

#: Historical SHAPE digest: sha256 over sorted relative path strings only.
#: It remains solely as the refusal twin proving that identical paths with
#: changed bytes are not authenticated corpus identity.
#:
#: It is kept because it is a different question, not because it adds
#: detection: ``CORPUS_AGGREGATE_HASH`` already subsumes the path set. Checked
#: separately and reported separately, the pair gives differential diagnosis --
#: shape alone failing means the file list moved, shape passing while the
#: aggregate fails means the bytes drifted under a stable list.
#:
HISTORICAL_PATH_SHAPE_DIGEST = (
    "sha256:a223a4499d0909f22190748b4aca9144e35a58fec31e84cb924e2c25fd3c03d0"
)

#: The whole ``gapKind`` vocabulary the table is capable of carrying, read off
#: the published artifact. ``value-call-target`` is deliberately not in it --
#: see ``test_table_cannot_testify_about_a_frame_bound_callee``.
DEMAND_TABLE_GAP_KINDS = frozenset({None, "runtime-selected"})

_TABLE_CACHE: dict[str, object] = {}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _pinned_demand_table() -> dict:
    """Pull the pinned table through the shelf and return the enrolled slice.

    Only the rows belonging to the four enrolled files are retained. That is
    not a filter over the measurement -- every row for those files is kept,
    and the shapes are enrolled rather than selected -- it is what keeps a
    232 MB artifact out of the rest of the run.
    """
    if "slice" in _TABLE_CACHE:
        return _TABLE_CACHE["slice"]

    root = _repo_root()
    with tempfile.TemporaryDirectory() as scratch:
        output = Path(scratch) / "demand-table.json"
        completed = subprocess.run(
            [
                str(root / "bin" / "sugarbin"),
                "artifact",
                "pull",
                "--kind",
                "python-demand-table",
                "--content-key",
                DEMAND_TABLE_CONTENT_KEY,
                "--output",
                str(output),
                "--runtime",
                "cpython-3.12.13",
            ],
            cwd=root,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0 or not output.is_file():
            raise AssertionError(
                "the pinned python-demand-table is not on this shelf: "
                f"{DEMAND_TABLE_CONTENT_KEY}\n"
                f"  sugarbin exit {completed.returncode}\n"
                f"  {completed.stderr.strip()[:400]}\n"
                "Publish or fetch that exact key. Do NOT substitute another "
                "table: two owners reading two tables produce two "
                "unfalsifiable results."
            )
        payload = json.loads(output.read_text(encoding="utf-8"))

    # The shelf is content-addressed, but the artifact says who it is and that
    # is what gets checked -- never the filename it arrived under.
    assert payload["contentKey"] == DEMAND_TABLE_CONTENT_KEY
    assert payload["authentication"]["python"] == "cpython-3.12.13"
    assert (
        payload["authentication"]["authenticatedCorpusManifestCid"]
        == DEMAND_TABLE_CORPUS_MANIFEST_CID
    )

    enrolled = {
        _source_cid(_corpus_root() / site.relative_path): site.shape
        for site in ENROLLED_SITES
    }
    rows: dict[str, list] = {shape: [] for shape in enrolled.values()}
    for row in payload["rows"]:
        shape = enrolled.get((row.get("useSite") or {}).get("sourceCid"))
        if shape is not None:
            rows[shape].append(row)

    result = {
        "identity": payload["identity"],
        "authentication": payload["authentication"],
        "rowCount": len(payload["rows"]),
        "gapKinds": frozenset(row.get("gapKind") for row in payload["rows"]),
        "rows": rows,
    }
    _TABLE_CACHE["slice"] = result
    return result


def _source_cid(path: Path) -> str:
    return blake3_512_of(path.read_text(encoding="utf-8").encode("utf-8"))


def _rows_on_line(rows, line: int) -> list:
    return [row for row in rows if (row.get("useSite") or {}).get("startLine") == line]


def test_enrolled_files_are_byte_identical_to_the_tables_corpus() -> None:
    """The table's pandas and this run's pandas are the same four files.

    The table was produced against a different tree than the one these sites
    are enrolled from. Both call themselves pandas 3.0.3, which is a version
    string and not a corpus identity. If the enrolled bytes differ, every row
    below is testimony about a corpus this run never read.
    """
    table = _pinned_demand_table()
    corpus = _corpus_root()
    produced_from = Path(table["authentication"]["pandasPath"]).resolve().parent
    for site in ENROLLED_SITES:
        here = (corpus / site.relative_path).read_bytes()
        there_path = produced_from / site.relative_path
        assert there_path.is_file(), (
            f"{site.relative_path} is absent from the tree the table was "
            f"produced from ({produced_from})"
        )
        assert hashlib.sha256(here).hexdigest() == site.file_sha256
        assert here == there_path.read_bytes(), (
            f"{site.relative_path} differs between this run's corpus and the "
            "tree the table was produced from; the rows do not attribute"
        )


def test_resolvable_call_drains_against_the_pinned_table() -> None:
    """``re.escape`` is named at its own coordinate, with a signature.

    This is what draining means for this shape: the table does not merely
    decline to complain, it produces the callee's symbol and its import
    signature at the exact inner-call coordinate.
    """
    table = _pinned_demand_table()
    site = next(s for s in ENROLLED_SITES if s.shape == "resolvable-call")
    rows = _rows_on_line(table["rows"]["resolvable-call"], site.line)

    escape_rows = [row for row in rows if row.get("targetSymbol") == "python:re.escape"]
    assert len(escape_rows) == 1, (
        f"expected exactly one re.escape row at {site.relative_path}:{site.line}, "
        f"got {[row.get('targetSymbol') for row in rows]}"
    )
    escape = escape_rows[0]
    assert escape.get("importSignature"), "the drained row carries no import signature"
    assert escape.get("gapKind") is None


def test_real_name_ref_site_binds_and_reads_exception_context() -> None:
    """The pinned name-ref site is also the real chained-observation reproducer."""
    table = _pinned_demand_table()
    site = next(s for s in ENROLLED_SITES if s.shape == "name-ref")
    assert table["rows"]["name-ref"], "shared table has no rows for the real file"

    source_file = _source_file(_corpus_root() / site.relative_path)
    with_node = next(
        node
        for node in source_file.nodes()
        if isinstance(node, With) and node.line_col_span().start_line == site.line
    )
    item = with_node.items[0]
    assert isinstance(item.optional_vars, Name)
    assert item.optional_vars.id == "exc_info"
    manager = item.context_expr
    assert isinstance(manager, Call)
    match_argument = next(
        keyword.value for keyword in manager.keywords if keyword.arg == "match"
    )
    assert isinstance(match_argument, Name)

    context_reads = [
        node
        for node in source_file.nodes()
        if isinstance(node, Attribute)
        and node.attr == "__context__"
        and "exc_info.value.__context__" in node.segment()
    ]
    assert len(context_reads) == 1


def test_opaque_callee_is_absent_from_every_row_of_its_file() -> None:
    """``msg`` appears nowhere in the table, and the scope of that is stated.

    The negative is bounded to what was actually searched: every row whose use
    site is in the enrolled file, not "the table" in general.
    """
    table = _pinned_demand_table()
    rows = table["rows"]["opaque-call"]
    assert rows, "no rows at all for the opaque-call file; the lookup is broken"
    naming_msg = [row for row in rows if "msg" in str(row.get("targetSymbol"))]
    assert naming_msg == [], f"expected no msg row, got {naming_msg}"


def test_table_cannot_testify_about_a_frame_bound_callee() -> None:
    """Absence of a row is not a refusal, and the artifact proves it.

    Across the whole published table ``gapKind`` takes two values, and
    ``value-call-target`` is not one of them. So the table has no way to say
    "this callee is a runtime value" -- a frame-bound callee is not an
    import-bound demand, and the artifact records import-bound demands. That
    is a boundary of the artifact, not a defect in it.

    The consequence is the point: from the table alone, "correctly refused"
    and "nobody looked" are the same observation. A drain tooth resting on
    ``msg`` having no row would stay green with the mechanism deleted.
    """
    table = _pinned_demand_table()
    assert table["gapKinds"] == DEMAND_TABLE_GAP_KINDS
    assert "value-call-target" not in table["gapKinds"]
    assert "value-call-target" in CALL_TARGET_GAP_KINDS


def test_construction_names_value_call_target_at_the_opaque_coordinate() -> None:
    """The loudness comes from construction, and the named gap is PRESENT.

    This is the tooth the table cannot supply. The production classifier is
    asked about the real callee in the real frame, and must answer with the
    condition that maps onto ``value-call-target`` -- not with silence, and
    not with a coverage-shaped kind that would send the name to an export door
    that can never resolve it.
    """
    from sugar_lift_py_tests.temporal.builtin_name_bindings import (
        builtin_name_temporal,
    )

    site = next(s for s in ENROLLED_SITES if s.shape == "opaque-call")
    source_file = _source_file(_corpus_root() / site.relative_path)
    argument = _match_argument(_raises_call_on_line(source_file, site.line))
    frame = _enclosing_function(source_file, argument)
    name = _callee_root_name(argument)

    module_definitions = {
        node.name
        for node in source_file.nodes()
        if isinstance(node, (FunctionDef, ClassDef))
    }
    classification = _classify_named_call_target(
        name,
        module_definitions,
        builtin_name_temporal(),
        frame_binders=_frame_bound_names(frame),
    )
    assert classification == "frame-bound-value", (
        f"{name} at {site.relative_path}:{site.line} classified as "
        f"{classification!r}; only frame-bound-value parks a "
        "value-call-target obligation, and every other answer sends the name "
        "to an export door that cannot resolve it"
    )
    assert _CALL_TARGET_GAP_PRECEDENCE.index("value-call-target") == 1


#: The three ``match=`` *pattern* shapes -- what the predicate *means*, once a
#: value is in hand. Distinct from the four argument *expression* shapes above.
#:
#: ``empty-pattern``
#:     ``match="^$"`` -- written empty-message regex. Ground
#:     ``StringValue("^$")`` decides true only for the empty message.
#: ``ordinary-pattern``
#:     ``match="whoops"`` -- an ordinary ground string. ``re.search`` settles
#:     at lift against a ground message.
#: ``accumulated-alternation``
#:     ``msg = "|".join(msgs)`` bound into ``match=msg``. The join is a
#:     constructed ``CallSiteValue``; the message half leaves as
#:     ``MatchRetained(py.re_search(...))``, never as a false predicate.
@dataclass(frozen=True)
class MatchPatternSite:
    """One enrolled pattern-semantic shape with a concrete corpus coordinate."""

    shape: str
    relative_path: str
    line: int
    expression: str
    file_sha256: str
    #: How the pattern value is obtained from the enrolled file.
    construction: str
    #: Authoritative message-predicate disposition for a ground raise.
    disposition: str


ENROLLED_PATTERN_SITES: tuple[MatchPatternSite, ...] = (
    MatchPatternSite(
        shape="empty-pattern",
        relative_path="tests/io/json/test_normalize.py",
        line=175,
        expression='"^$"',
        file_sha256="d8fe146f21dfe51e39b21aa233cdf416e5337efede0938d2930b783dd6a89909",
        construction="literal-string-value",
        disposition="match-decided",
    ),
    MatchPatternSite(
        shape="ordinary-pattern",
        relative_path="tests/test_register_accessor.py",
        line=103,
        expression='"whoops"',
        file_sha256="4d2599448c6b329af3822dbc2295fafe142d9ce84e49821c435d9b1c11fea793",
        construction="literal-string-value",
        disposition="match-decided",
    ),
    MatchPatternSite(
        shape="accumulated-alternation",
        relative_path="tests/indexing/test_indexing.py",
        line=111,
        expression="msg",
        file_sha256="00d2e0ab8b75c16942df2c6cf7b3fc0a0aec02dfe39792d78b5c83d8f973e409",
        construction="join-call-site-value",
        disposition="match-retained",
    ),
)

#: Binding site for the accumulated-alternation pattern: ``msg = "|".join(msgs)``.
ACCUMULATED_ALTERNATION_BINDING_LINE = 108

#: First named gap on the manager-construction path for enrolled match=
#: managers. Soft-Try for ``re.compile`` is past; the live floor is the
#: f-string binary pair inside an inherited method body. Named, not mere
#: refusal -- BinOp owns the pair, Match owns the pattern half above.
MANAGER_FORCE_FLOOR_DETAIL = (
    "binary_operation_exception_floor:SymbolicValue + CallSiteValue"
)


def _pattern_value_for_site(site: MatchPatternSite):
    """Construct the enrolled pattern value from the real corpus coordinate.

    Empty and ordinary patterns desugar the ``match=`` keyword itself. The
    accumulated alternation desugars the binding that produces ``msg`` -- the
    keyword is a bare name, and the join that builds the alternation is the
    shape under test.
    """
    from sugar_source_tree.nodes import Assign

    path = _corpus_root() / site.relative_path
    source_file = _source_file(path)
    if site.shape == "accumulated-alternation":
        binding = next(
            node
            for node in source_file.nodes()
            if isinstance(node, Assign)
            and node.line_col_span().start_line == ACCUMULATED_ALTERNATION_BINDING_LINE
            and "join" in node.segment()
        )
        outcome = binding.value.sugar().desugar()
    else:
        argument = _match_argument(_raises_call_on_line(source_file, site.line))
        outcome = argument.sugar().desugar()
    assert type(outcome).__name__ == "Complete", (
        f"{site.shape} at {site.relative_path}:{site.line} did not complete: "
        f"{outcome!r}"
    )
    return outcome.value


def _raise_effect_with_message(message: str):
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.floor.string_value import StringValue
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.ir import ctor

    identity = TermValue(1).to_term(owner="match-pattern-identity")
    raised = CallSiteValue(
        "ValueError",
        (StringValue(message),),
        ("message",),
        ctor("call:ValueError", []),
        None,
    )

    class _Handler:
        def exception_type_identity(self):
            return identity

    return (
        RaiseEffect(
            exception_name="ValueError",
            exception_type_coordinate=identity,
            occurrence=f"{message}@match-pattern",
            raised_value=raised,
        ),
        _Handler(),
    )


@pytest.mark.parametrize(
    "site",
    ENROLLED_PATTERN_SITES,
    ids=[site.shape for site in ENROLLED_PATTERN_SITES],
)
def test_enrolled_pattern_site_still_holds_its_match_argument(
    site: MatchPatternSite,
) -> None:
    """Content pin: the enrolled pattern coordinate still spells this expression."""
    path = _corpus_root() / site.relative_path
    assert path.is_file(), f"enrolled pattern site missing: {path}"
    observed = hashlib.sha256(path.read_bytes()).hexdigest()
    assert observed == site.file_sha256, (
        f"{site.relative_path} is not the file this pattern row enrolled "
        f"(observed {observed}, enrolled {site.file_sha256})"
    )
    argument = _match_argument(_raises_call_on_line(_source_file(path), site.line))
    assert argument.segment().strip() == site.expression


@pytest.mark.parametrize(
    "site",
    ENROLLED_PATTERN_SITES,
    ids=[site.shape for site in ENROLLED_PATTERN_SITES],
)
def test_enrolled_pattern_constructs_authoritative_message_verdict(
    site: MatchPatternSite,
) -> None:
    """Each pattern shape produces a named verdict -- never mere silence.

    Before this tooth, empty / ordinary / accumulated were only measured as
    manager force-floor refusals. The pattern half is independent of that
    floor: the real argument constructs a value, and
    ``raise_effect_message_verdict`` settles or retains it.
    """
    from sugar_lift_py_tests.authenticated_exception_matching import (
        MatchDecided,
        MatchRetained,
        raise_effect_message_verdict,
    )
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.floor.string_value import StringValue

    pattern = _pattern_value_for_site(site)
    effect, expected = _raise_effect_with_message("whoops")

    if site.shape == "empty-pattern":
        assert isinstance(pattern, StringValue) and pattern.value == "^$"
        empty_effect, _ = _raise_effect_with_message("")
        assert raise_effect_message_verdict(
            empty_effect, expected, pattern
        ) == MatchDecided(True)
        assert raise_effect_message_verdict(effect, expected, pattern) == MatchDecided(
            False
        )
        return

    if site.shape == "ordinary-pattern":
        assert isinstance(pattern, StringValue) and pattern.value == "whoops"
        assert raise_effect_message_verdict(effect, expected, pattern) == MatchDecided(
            True
        )
        other, _ = _raise_effect_with_message("other")
        assert raise_effect_message_verdict(other, expected, pattern) == MatchDecided(
            False
        )
        return

    assert site.shape == "accumulated-alternation"
    assert isinstance(pattern, CallSiteValue)
    assert pattern.target_name == "join"
    verdict = raise_effect_message_verdict(effect, expected, pattern)
    assert isinstance(verdict, MatchRetained)
    assert verdict.obligation.name == "py.re_search"


def test_name_pattern_reaches_authenticated_base_force_floor() -> None:
    """The line-16 manager crosses the generic base, then names the live floor.

    ``RaisesExc(AbstractRaises[T])`` inherits its initializer from a local,
    source-authenticated generic base. Soft-Try for ``re.compile`` is past;
    construction now names the f-string binary pair inside an inherited
    method body. It must not regress to the synthetic ``ExitSet with 3 arms``
    manager-face gap.
    """
    from sugar_lift_py_tests.context_manager_resolution import (
        ContextManagerResolutionGapV1,
        TreeConstructionContextV1,
    )
    from sugar_lift_python_source.manager_summary_derivation import (
        populate_source_derived_resource_refs,
    )

    site = next(site for site in ENROLLED_SITES if site.shape == "name-ref")
    path = _corpus_root() / site.relative_path
    source = path.read_text(encoding="utf-8")
    context = TreeConstructionContextV1.for_source_call_construction()
    source_file = SourceFile(
        (source, str(path), blake3_512_of(source.encode("utf-8"))),
        construction_context=context,
    )

    populate_source_derived_resource_refs(
        source_file, root=_corpus_root().parent, path=path
    )

    row = next(
        result
        for coordinate, result in context.source_derived_contract_refs.items()
        if coordinate.start_line == site.line
    )
    assert isinstance(row, ContextManagerResolutionGapV1)
    assert row.kind == "force-floor"
    assert row.detail == MANAGER_FORCE_FLOOR_DETAIL
    assert "ExitSet with 3 arms" not in row.detail


@pytest.mark.parametrize(
    "site",
    ENROLLED_PATTERN_SITES,
    ids=[site.shape for site in ENROLLED_PATTERN_SITES],
)
def test_pattern_sites_manager_floor_is_named_not_synthetic(
    site: MatchPatternSite,
) -> None:
    """Manager construction at each pattern site names the live binary floor.

    The pattern half above constructs authoritatively. The manager half still
    stops at a named force-floor owned by BinOp's undecided pair law -- not at
    a synthetic ExitSet arm count and not at an unnamed refusal.
    """
    from sugar_lift_py_tests.context_manager_resolution import (
        ContextManagerResolutionGapV1,
        TreeConstructionContextV1,
    )
    from sugar_lift_python_source.manager_summary_derivation import (
        populate_source_derived_resource_refs,
    )

    path = _corpus_root() / site.relative_path
    source = path.read_text(encoding="utf-8")
    context = TreeConstructionContextV1.for_source_call_construction()
    source_file = SourceFile(
        (source, str(path), blake3_512_of(source.encode("utf-8"))),
        construction_context=context,
    )
    call = _raises_call_on_line(source_file, site.line)
    argument = _match_argument(call)
    assert argument.segment().strip() == site.expression

    populate_source_derived_resource_refs(
        source_file, root=_corpus_root().parent, path=path
    )

    row = next(
        result
        for coordinate, result in context.source_derived_contract_refs.items()
        if coordinate.start_line == site.line
    )
    assert isinstance(row, ContextManagerResolutionGapV1)
    assert row.kind == "force-floor"
    assert row.detail == MANAGER_FORCE_FLOOR_DETAIL
    assert "ExitSet with 4 arms" not in row.detail
    assert "ExitSet with 3 arms" not in row.detail


def test_corpus_identity_is_checked_on_content_not_on_the_file_list() -> None:
    """Content identity plus a historical shape refusal twin.

    The regenerated table authenticates ordered relative paths and file bytes
    with ``DEMAND_TABLE_CORPUS_MANIFEST_CID``. The historical sha256 shape
    digest remains independently reproducible only to prove why path names
    alone are insufficient corpus testimony.

    ``corpus_pin.aggregate_hash`` is the identity that refuses. It folds the
    distribution and version into the preimage alongside per-file path, sha256
    and size, so it also refuses the case a byte-only content hash cannot: an
    identical file set relabelled as a different pandas version.

    The independent aggregate pin also includes distribution/version labels;
    it refuses an identical byte tree relabelled as a different distribution.
    """
    from sugar_lift_py_tests.corpus_pin import pin_corpus

    pin = pin_corpus(_corpus_root())

    assert pin.aggregate_hash == CORPUS_AGGREGATE_HASH, (
        "CORPUS CONTENT DRIFT: the enrolled pandas has the same shape but "
        f"different bytes or a different version label.\n"
        f"  observed aggregate:  {pin.aggregate_hash}\n"
        f"  enrolled aggregate:  {CORPUS_AGGREGATE_HASH}\n"
        "Every row and site in this module testifies about the enrolled "
        "corpus. Re-pin deliberately; do not follow the drift."
    )

    shape = _paths_only_manifest_cid(_corpus_root())
    assert shape == HISTORICAL_PATH_SHAPE_DIGEST, (
        "CORPUS SHAPE DRIFT: the enrolled file LIST moved -- a truncated "
        "enrolment, an extra vendored file, or a rename.\n"
        f"  observed shape cid:  {shape}\n"
        f"  enrolled shape cid:  {HISTORICAL_PATH_SHAPE_DIGEST}"
    )


def _paths_only_manifest_cid(root: Path) -> str:
    """Reproduce the table's shape CID from path names alone.

    Deliberately recomputed here rather than read back out of the artifact:
    comparing the artifact's field to itself would be an echo. The preimage is
    the sorted relative paths, exactly as ``authenticated_pytest`` builds it,
    and the fact that no file is read in this function is the point being
    made.
    """
    from sugar_source_tree.tree import SourceTree

    ordered = sorted(str(path.relative_to(root)) for path in SourceTree(root).paths())
    preimage = json.dumps(ordered, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(preimage.encode("utf-8")).hexdigest()
