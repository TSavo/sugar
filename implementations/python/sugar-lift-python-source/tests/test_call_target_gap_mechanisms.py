"""The four conditions ``opaque-call-target`` used to fuse into one name.

One kind named four structurally different failures, three of them carrying a
callee spelling in the key.  ``opaque-call-target:func`` was the largest single
term on the pinned pandas board (#6371) -- a *capability* gap (calling a value)
wearing a vendor-looking name, indistinguishable from a *coverage* gap (stdlib
outside the artifact) and from a *defect* (an in-artifact symbol the export door
failed on).  A measurement a vendor rename can move is not a measurement.

Splitting these apart REATTRIBUTES rows; it drains none of them.  The capability
itself is open work (#6409), as is the door defect (#6410).  Corpus row counts
from the pre-`d10774abc` ledger are deliberately not restated here: that
collection universe was short by 290 laws and the figures are pending
re-baseline.

Each mechanism gets both faces here:

* ``value-call-target`` -- the callee is bound by the enclosing definition, as a
  parameter or as a local.  Higher-order dispatch; no export lookup can ever
  resolve it.  Negative face: the same call, same spelling, where the name is a
  module-level definition instead -- and it constructs.
* ``call-target-source-absent`` -- the export door declines: no defining source
  in this artifact.  Coverage.
* ``call-target-export-unresolved`` -- the door authenticates an object that IS
  in this artifact and projecting its frame still fails.  A defect that was
  invisible while it shared a bucket with the other two.
* ``call-graph-cycle`` -- recursion.  Carries no symbol at all.

Plus the law the whole split exists to serve: the kind is the structural key and
never contains a callee spelling; the spelling rides ``detail``.

All fixture source is neutral and written for this test.  No vendor text, no
vendor names, no name arms.
"""

from __future__ import annotations

import csv
import importlib.metadata
from pathlib import Path

import pytest

from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.import_binding import authenticated_import_use_receipts
from sugar_lift_py_tests.ir import _term_content_cid
from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.dependency_artifact import (
    DependencyArtifactGraph,
    ResolvedPythonObjectV1,
    resolve_import_binding as _resolve_import_binding,
)
from sugar_lift_python_source import manager_construction
from sugar_lift_python_source.manager_construction import (
    CALL_TARGET_GAP_KINDS,
    ConstructedCallActualV1,
    ConstructedManagerBehaviorV1,
    ManagerConstructionGapV1,
    _frame_bound_names,
    construct_manager_behavior as _construct_manager_behavior,
    resolve_source_visible_frame,
)
from sugar_lift_python_source.resolution_session import (
    SOURCE_CALL_CLOSURE_FRAME_BOUND,
    SourceResolutionSession,
)
from sugar_source_tree.binding_provenance import ConstructedValueTestimonyV1
from sugar_source_tree.nodes import Call, Constant, FunctionDef
from sugar_source_tree.panic import OpaqueSourceCallResolutionGap
from sugar_source_tree.tree import SourceFile


def _session_enrolling_graph(graph):
    name = graph.distribution_name
    if not name:
        raise AssertionError("call-target graph test requires a distribution name")
    return SourceResolutionSession(enrolled_distributions=frozenset({name}))


def resolve_import_binding(*args, graph, session=None, **kwargs):
    if session is None:
        session = _session_enrolling_graph(graph)
    return _resolve_import_binding(*args, graph=graph, session=session, **kwargs)


def construct_manager_behavior(*args, graph, session=None, **kwargs):
    if session is None:
        session = _session_enrolling_graph(graph)
    return _construct_manager_behavior(*args, graph=graph, session=session, **kwargs)


def _distribution(
    root: Path, modules: dict[str, str]
) -> importlib.metadata.Distribution:
    """One authenticated distribution whose file manifest is exactly ``modules``."""
    package = root / "arbitrary"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        "from arbitrary.manager import make_guard\n", encoding="utf-8"
    )
    names = ["arbitrary/__init__.py"]
    for name, source in modules.items():
        (package / f"{name}.py").write_text(source, encoding="utf-8")
        names.append(f"arbitrary/{name}.py")
    metadata = root / "arbitrary_dist-1.0.dist-info"
    metadata.mkdir(parents=True)
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: arbitrary-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    names += [
        "arbitrary_dist-1.0.dist-info/METADATA",
        "arbitrary_dist-1.0.dist-info/RECORD",
    ]
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for name in names:
            writer.writerow((name, "", ""))
    return importlib.metadata.Distribution.at(metadata)


def _construct(root: Path, manager_source: str, **extra_modules: str):
    """Construct ``arbitrary.make_guard(23)`` from authenticated source."""
    graph = DependencyArtifactGraph.authenticate(
        _distribution(root, {"manager": manager_source, **extra_modules})
    )
    consumer = "import arbitrary\narbitrary.make_guard(23)\n"
    path = root / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    source_cid = blake3_512_of(consumer.encode())
    receipts, _ = authenticated_import_use_receipts(root, path, consumer, source_cid)
    resolved = resolve_import_binding(receipts[0], graph=graph)
    assert isinstance(resolved, ResolvedPythonObjectV1), resolved
    source_file = SourceFile((consumer, str(path), source_cid))
    call = next(item for item in source_file.nodes() if isinstance(item, Call))
    literal = next(item for item in call.args if isinstance(item, Constant))
    actual = TermValue(23)
    supplied = ConstructedCallActualV1(
        literal,
        actual,
        ConstructedValueTestimonyV1.mint(
            literal.fragment, _term_content_cid(actual.to_term(owner="test"))
        ),
    )
    return construct_manager_behavior(
        resolved, graph=graph, actuals=(supplied,), call_site=call.fragment
    )


def _opaque_gap(root: Path, manager_source: str, **extra_modules: str):
    with pytest.raises(OpaqueSourceCallResolutionGap) as raised:
        _construct(root, manager_source, **extra_modules)
    return raised.value


# --------------------------------------------------------------------------
# value-call-target -- the callee is a VALUE bound by the enclosing definition
# --------------------------------------------------------------------------


def test_called_parameter_is_a_value_call_target_not_a_missing_import(tmp_path):
    """POSITIVE: a formal parameter that is called is higher-order dispatch.

    ``helper`` is never imported and never defined -- it is *bound*, as the
    enclosing definition's own parameter.  No export door can resolve it,
    because there is nothing to look up.  Reporting this as an unresolvable
    external symbol claims a coverage problem that does not exist.
    """
    gap = _opaque_gap(
        tmp_path,
        "def make_guard(helper):\n    return helper()\n",
    )

    assert gap.observed == "value-call-target:helper"


def test_called_local_binding_is_a_value_call_target(tmp_path):
    """POSITIVE: a function-LOCAL binding is a value for the same reason.

    Different binder, same mechanism: the callee is produced at runtime inside
    this frame.  Parameter and local must not split into two kinds, because the
    missing capability is one capability.
    """
    gap = _opaque_gap(
        tmp_path,
        "def picked(value):\n"
        "    return value\n"
        "\n"
        "def make_guard(expected):\n"
        "    helper = picked\n"
        "    return helper(expected)\n",
    )

    assert gap.observed == "value-call-target:helper"


def test_module_level_definition_of_the_same_spelling_constructs(tmp_path):
    """NEGATIVE FACE: identical call text, and it constructs.

    The only difference from the positive twin is what BINDS ``helper``.  If
    this arm also refused, the classification would be reading the spelling.
    """
    result = _construct(
        tmp_path,
        "class Slot:\n"
        "    def __init__(self, label):\n"
        "        self.label = 7\n"
        "\n"
        "def helper():\n"
        "    return Slot(7)\n"
        "\n"
        "def make_guard(expected):\n"
        "    return helper()\n",
    )

    assert isinstance(result, ConstructedManagerBehaviorV1), result


def test_parameter_shadowing_a_module_definition_is_still_a_value(tmp_path):
    """A local binding SHADOWS a module-level definition of the same name.

    ``helper`` is both a parameter of ``make_guard`` and a module-level
    definition.  Python binds the parameter, so the callee is the value passed
    in -- not the definition.  Classifying by the module's definition set first
    would resolve a frame the call never reaches, which is a soundness bug and
    not only a reporting one.
    """
    gap = _opaque_gap(
        tmp_path,
        "class Slot:\n"
        "    def __init__(self, label):\n"
        "        self.label = 7\n"
        "\n"
        "def helper():\n"
        "    return Slot(7)\n"
        "\n"
        "def make_guard(helper):\n"
        "    return helper()\n",
    )

    assert gap.observed == "value-call-target:helper"


def test_parameter_shadowing_a_builtin_is_still_a_value(tmp_path):
    """A parameter shadows the builtin temporal too, for the same reason."""
    gap = _opaque_gap(
        tmp_path,
        "def make_guard(len):\n    return len(7)\n",
    )

    assert gap.observed == "value-call-target:len"


# --------------------------------------------------------------------------
# call-target-source-absent vs call-target-export-unresolved
# --------------------------------------------------------------------------


def test_callee_outside_the_artifact_is_coverage_not_a_defect(tmp_path):
    """POSITIVE: the export door declines -- no defining source in the artifact."""
    gap = _opaque_gap(
        tmp_path,
        "def make_guard(expected):\n    return unbound_helper(expected)\n",
    )

    assert gap.observed == "call-target-source-absent:unbound_helper"


def test_missing_module_cast_is_still_source_absent(tmp_path):
    """A missing ``cast`` import stays coverage-absent; it is not typing.cast."""
    gap = _opaque_gap(
        tmp_path,
        "from missing_mod import cast\n"
        "def make_guard(expected):\n"
        "    return cast(object, expected)\n",
    )

    assert gap.observed == "call-target-source-absent:cast"


def test_in_artifact_callee_carries_nested_refusal_to_nested_consumer(tmp_path):
    """The callee resolves; its reached opaque child names its own consumer.

    ``support.build_slot`` is a real definition inside this artifact's own file
    manifest, statically exported and reached through the same door.  Therefore
    the outer ``build_slot`` call is not the refusal: ordinary control flow
    reaches ``absent_from_artifact`` inside its authenticated body.
    """
    gap = _opaque_gap(
        tmp_path,
        "from arbitrary.support import build_slot\n"
        "\n"
        "def make_guard(expected):\n"
        "    return build_slot(expected)\n",
        support="def build_slot(label):\n    return absent_from_artifact(label)\n",
    )

    assert gap.observed == "call-target-source-absent:absent_from_artifact"


def test_resolved_outer_callee_does_not_relabel_the_nested_gap(tmp_path):
    """DISCRIMINATION: direct and nested routes identify the same consumer.

    The nested route adds an authenticated ``build_slot`` frame.  If eager frame
    preparation still adjudicated the route, it would relabel the refusal at
    that outer call rather than carrying the reached inner obligation.
    """
    absent = _opaque_gap(
        tmp_path / "absent",
        "def make_guard(expected):\n    return unbound_helper(expected)\n",
    )
    defect = _opaque_gap(
        tmp_path / "defect",
        "from arbitrary.support import build_slot\n"
        "\n"
        "def make_guard(expected):\n"
        "    return build_slot(expected)\n",
        support="def build_slot(label):\n    return absent_from_artifact(label)\n",
    )

    assert absent.observed == "call-target-source-absent:unbound_helper"
    assert defect.observed == "call-target-source-absent:absent_from_artifact"


_UNBINDABLE_CALLEE = (
    "class Marker:\n"
    "    pass\n"
    "\n"
    "def build_slot(label):\n"
    "    return Marker(label)\n"
)


@pytest.mark.parametrize(
    ("manager_source", "observed"),
    [
        (
            "from arbitrary.support import build_slot\n"
            "\n"
            "def make_guard(expected):\n"
            "    return build_slot(expected)\n",
            "call-target-export-unresolved:build_slot",
        ),
        (
            "from arbitrary import support\n"
            "\n"
            "def make_guard(expected):\n"
            "    return support.build_slot(expected)\n",
            "call-target-export-unresolved:python:arbitrary.support.build_slot",
        ),
    ],
    ids=["free-name-call", "module-attribute-call"],
)
def test_callee_whose_inner_call_cannot_bind_is_an_unresolved_export(
    tmp_path, manager_source, observed
):
    """POSITIVE: a binding gap inside a callee parks that callee, by name.

    ``Marker`` defines no ``__init__`` of its own, so its source frame has no
    formal to receive ``label``: projecting ``build_slot`` raises
    ``SourceCallBindingGap``.  That is the door authenticating an object in
    this artifact and failing to project its frame -- the same condition a
    ``SugarNotWritten`` body is, and it ends in the same named kind at the
    call that reached it.  It used to leave as a bare ``ValueError`` and take
    the whole enclosing file's enumeration with it.

    Both doors that follow a call into another definition park it: the free
    name and the attribute of an imported module.
    """
    gap = _opaque_gap(tmp_path, manager_source, support=_UNBINDABLE_CALLEE)

    assert gap.observed == observed


def test_callee_whose_inner_call_binds_is_not_parked(tmp_path):
    """NEGATIVE FACE: same call text, a class that takes the argument.

    The only difference from the positive twin is that ``Marker`` declares the
    formal.  If this route were parked too, the kind would be reading the
    callee's shape rather than a failed binding.
    """
    result = _construct(
        tmp_path,
        "from arbitrary.support import build_slot\n"
        "\n"
        "def make_guard(expected):\n"
        "    return build_slot(expected)\n",
        support=(
            "class Marker:\n"
            "    def __init__(self, label):\n"
            "        self.label = 7\n"
            "\n"
            "def build_slot(label):\n"
            "    return Marker(label)\n"
        ),
    )

    assert isinstance(result, ConstructedManagerBehaviorV1), result


def test_binding_gap_in_the_outer_target_itself_stays_loud(tmp_path):
    """LYING TWIN: the entry door does not park its own target's defect.

    Here the unbindable call sits in ``make_guard`` -- the definition being
    constructed, not a callee it reaches.  There is no outer frame to preserve
    and no call site to park an obligation at, so reporting an unresolved
    export would name a callee that does not exist.  The gap leaves under its
    own class.
    """
    with pytest.raises(SourceCallBindingGap, match="unconsumed call actual"):
        _construct(
            tmp_path,
            "class Marker:\n"
            "    pass\n"
            "\n"
            "def make_guard(expected):\n"
            "    return Marker(expected)\n",
        )


# --------------------------------------------------------------------------
# call-closure-over-bound -- the definition reaches too many others to project
# --------------------------------------------------------------------------


def _call_chain(length: int) -> tuple[str, dict[str, str]]:
    """``make_guard`` calling ``length`` definitions in a line, one per module.

    ``make_guard`` -> ``step1`` -> ... -> ``step<length>``, so the call closure
    of ``make_guard`` is ``length + 1`` definitions.  One module each: calls
    inside one module ride the caller's frame and are not what is bounded.
    """
    modules = {}
    for index in range(1, length):
        modules[f"link{index}"] = (
            f"from arbitrary.link{index + 1} import step{index + 1}\n"
            "\n"
            f"def step{index}(label):\n"
            f"    return step{index + 1}(label)\n"
        )
    modules[f"link{length}"] = (
        "class Marker:\n"
        "    def __init__(self, label):\n"
        "        self.label = 7\n"
        "\n"
        f"def step{length}(label):\n"
        "    return Marker(label)\n"
    )
    manager = (
        "from arbitrary.link1 import step1\n"
        "\n"
        "def make_guard(expected):\n"
        "    return step1(expected)\n"
    )
    return manager, modules


def test_call_closure_one_past_the_bound_is_refused_by_name(tmp_path):
    """POSITIVE: one definition too many and the root is refused, by name.

    Projection follows source calls eagerly, and theirs.  Unbounded, that walk
    is the whole reachable call graph -- minutes for one entry point, and the
    file never reaches a terminal.  The refusal is counted in definitions, so
    it is the same on every machine: no clock decides it.
    """
    manager, modules = _call_chain(SOURCE_CALL_CLOSURE_FRAME_BOUND)

    result = _construct(tmp_path, manager, **modules)

    assert isinstance(result, ManagerConstructionGapV1), result
    assert result.kind == "call-closure-over-bound"
    assert str(SOURCE_CALL_CLOSURE_FRAME_BOUND) in result.detail
    # The refusal says who refused, what shape was illegal, and what replaces
    # it -- not only that a number was exceeded.
    for part in ("owner: ", "illegal shape: ", "replacement: "):
        assert part in result.detail, result.detail


def test_call_closure_at_the_bound_constructs(tmp_path):
    """LYING TWIN: the same chain one link shorter fits, and constructs.

    If this were refused too, the kind would be naming "calls something that
    calls something" rather than a closure past the bound.
    """
    manager, modules = _call_chain(SOURCE_CALL_CLOSURE_FRAME_BOUND - 1)

    result = _construct(tmp_path, manager, **modules)

    assert isinstance(result, ConstructedManagerBehaviorV1), result


def _resolved_definition(root: Path, graph, consumer: str, name: str):
    path = root / f"{name}.py"
    path.write_text(consumer, encoding="utf-8")
    source_cid = blake3_512_of(consumer.encode())
    receipts, _ = authenticated_import_use_receipts(root, path, consumer, source_cid)
    session = _session_enrolling_graph(graph)
    resolved = resolve_import_binding(receipts[0], graph=graph, session=session)
    assert isinstance(resolved, ResolvedPythonObjectV1), resolved
    return resolved


def test_memoized_callee_still_counts_toward_the_closure(tmp_path):
    """A warm session cannot make an over-bound closure fit.

    ``step2`` is projected first, on its own: its closure is under the bound,
    so it constructs and is memoized.  ``make_guard`` then reaches it through
    ``step1``.  Only two definitions are projected fresh, but ``make_guard``
    still reaches one more than the bound, and is refused exactly as it is in
    a cold session.  If a memo hit counted as one definition, the verdict on
    ``make_guard`` would depend on what the session had seen before it.
    """
    manager, modules = _call_chain(SOURCE_CALL_CLOSURE_FRAME_BOUND)
    graph = DependencyArtifactGraph.authenticate(
        _distribution(tmp_path, {"manager": manager, **modules})
    )
    inner = _resolved_definition(
        tmp_path, graph, "from arbitrary.link2 import step2\nstep2(23)\n", "inner"
    )
    outer = _resolved_definition(
        tmp_path, graph, "import arbitrary\narbitrary.make_guard(23)\n", "outer"
    )
    session = _session_enrolling_graph(graph)

    warm = resolve_source_visible_frame(inner, graph=graph, session=session)
    refused = resolve_source_visible_frame(outer, graph=graph, session=session)

    assert not isinstance(warm, ManagerConstructionGapV1), warm
    assert isinstance(refused, ManagerConstructionGapV1), refused
    assert refused.kind == "call-closure-over-bound"
    # The refusal is the root's alone: the callee that fit is still served.
    assert resolve_source_visible_frame(inner, graph=graph, session=session) == warm


# --------------------------------------------------------------------------
# dependency seats -- which tops a session has seated so far decides nothing
# --------------------------------------------------------------------------


def _elsewhere_graph(root: Path, flag: int) -> DependencyArtifactGraph:
    """A second authenticated distribution, top level ``elsewhere``."""
    package = root / "elsewhere"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(f"FLAG = {flag}\n", encoding="utf-8")
    metadata = root / "elsewhere_dist-1.0.dist-info"
    metadata.mkdir(parents=True)
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: elsewhere-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for name in (
            "elsewhere/__init__.py",
            "elsewhere_dist-1.0.dist-info/METADATA",
            "elsewhere_dist-1.0.dist-info/RECORD",
        ):
            writer.writerow((name, "", ""))
    return DependencyArtifactGraph.authenticate(
        importlib.metadata.Distribution.at(metadata)
    )


def _seat_fixture(tmp_path: Path, monkeypatch, body: str):
    """``arbitrary.make_guard`` with ``body``; counts real frame projections."""
    manager = f"import elsewhere\n\ndef make_guard(expected):\n    {body}\n"
    graph = DependencyArtifactGraph.authenticate(
        _distribution(tmp_path / "own", {"manager": manager})
    )
    resolved = _resolved_definition(
        tmp_path, graph, "import arbitrary\narbitrary.make_guard(23)\n", "outer"
    )
    session = _session_enrolling_graph(graph)
    projected: list[str] = []
    project = manager_construction._resolve_source_visible_frame_uncached

    def counted(resolved, **kwargs):
        projected.append(resolved.definition.name)
        return project(resolved, **kwargs)

    monkeypatch.setattr(
        manager_construction, "_resolve_source_visible_frame_uncached", counted
    )

    def ask(held=None):
        # A real caller seeds its roster from the session's seats.
        roster = dict(session.dependency_graphs) if held is None else held
        return resolve_source_visible_frame(
            resolved, graph=graph, session=session, dependency_graphs=roster
        )

    return session, ask, projected


def test_frame_and_module_are_built_once_however_many_tops_get_seated(
    tmp_path, monkeypatch
):
    """TRUTHFUL TWIN: a top seated later, that the definition never reads.

    The memo keys named every top the session had authenticated so far.  That
    roster grows as doors ask for tops, so each new top forgot every projected
    frame and every materialized module: ``pandas.io.stata.StataReader`` was
    projected six times in one open of ``tests/io/test_stata.py``, the pandas
    megamodules materialized nine.  ``make_guard`` reads nothing of
    ``elsewhere``; seating it changes nothing ``make_guard`` means.
    """
    session, ask, projected = _seat_fixture(tmp_path, monkeypatch, "return 7")

    cold = ask()
    session.dependency_graphs["elsewhere"] = _elsewhere_graph(tmp_path / "e", 7)
    warm = ask()

    assert not isinstance(cold, ManagerConstructionGapV1), cold
    assert warm == cold
    assert projected == ["make_guard"]
    assert len(session.module_materializations) == 1


def test_row_built_without_a_top_is_rebuilt_once_that_top_is_seated(
    tmp_path, monkeypatch
):
    """LYING TWIN: the definition DOES read the top that is seated later.

    The import value-use door answers a top with no seat with the bare
    receipt.  A row built on that answer is served only while it is still the
    answer: once ``elsewhere`` is seated the frame is projected again, once,
    against the module already materialized.
    """
    session, ask, projected = _seat_fixture(
        tmp_path, monkeypatch, "return elsewhere.FLAG"
    )

    ask()
    ask()
    assert projected == ["make_guard"], "an unchanged session reads the memo"

    session.dependency_graphs["elsewhere"] = _elsewhere_graph(tmp_path / "e", 7)
    ask()
    assert projected == ["make_guard"] * 2, (
        "a row built while 'elsewhere' had no seat was served after it was seated"
    )
    ask()
    assert projected == ["make_guard"] * 2, "the rebuilt row reads no unseated top"
    assert len(session.module_materializations) == 1


def test_row_is_not_served_across_two_artifacts_of_one_top(tmp_path, monkeypatch):
    """LYING TWIN: one top, two artifacts -- that IS a different question.

    Dropping the roster from the key must not drop the artifact.  An asker
    holding ``elsewhere`` at another artifact than the session's seat gets its
    own row, and after the session's seat itself moves, rows built before the
    move answer nobody.
    """
    session, ask, projected = _seat_fixture(tmp_path, monkeypatch, "return 7")
    first = _elsewhere_graph(tmp_path / "e1", 7)
    second = _elsewhere_graph(tmp_path / "e2", 8)
    assert first.distribution_artifact_cid != second.distribution_artifact_cid

    session.dependency_graphs["elsewhere"] = first
    ask()
    assert projected == ["make_guard"]

    ask({"elsewhere": second})
    assert projected == ["make_guard"] * 2, (
        "a row built against one artifact of 'elsewhere' answered an asker "
        "holding another"
    )

    session.dependency_graphs["elsewhere"] = second
    ask()
    assert projected == ["make_guard"] * 3, (
        "a row built before the session's seat moved was served after it"
    )


# --------------------------------------------------------------------------
# The law the split exists to serve
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "manager_source",
    [
        "def make_guard(helper):\n    return helper(7)\n",
        "def make_guard(expected):\n    return unbound_helper(expected)\n",
        "def make_guard(len):\n    return len(7)\n",
    ],
)
def test_the_kind_is_a_structural_key_and_never_carries_a_spelling(
    tmp_path, manager_source
):
    """Every reported kind is a member of the closed vocabulary, unfused.

    The old reporting layer minted ``f"{kind}:{detail}"`` and truncated it to 80
    chars.  A key that can be truncated is not an identity, and a key whose
    cardinality is the cardinality of callee spellings is a name table.
    """
    gap = _opaque_gap(tmp_path, manager_source)
    kind, spelling = gap.observed.split(":", 1)

    assert kind in CALL_TARGET_GAP_KINDS, kind
    assert ":" not in kind
    # The spelling exists -- it just is not the key.
    assert spelling and ":" not in spelling


def test_ordinary_control_flow_selects_the_first_reached_blocker(tmp_path):
    """Every blocker is parked; statement order decides which one is reached."""
    gap = _opaque_gap(
        tmp_path,
        "def make_guard(expected):\n"
        "    zulu(expected)\n"
        "    alpha(expected)\n"
        "    return mike(expected)\n",
    )

    assert gap.observed == "call-target-source-absent:zulu"


# --------------------------------------------------------------------------
# _frame_bound_names -- the binder walk, read directly
# --------------------------------------------------------------------------


def _definition(source: str, name: str) -> FunctionDef:
    tree = SourceFile((source, "binders.py", blake3_512_of(source.encode())))
    return next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == name
    )


def test_frame_bound_names_reads_every_binding_form(tmp_path):
    """POSITIVE: parameters and each local binding syntax, from the AST alone."""
    definition = _definition(
        "def frame(param, *args, keyword=None, **rest):\n"
        "    assigned = 1\n"
        "    annotated: int = 2\n"
        "    augmented = 0\n"
        "    augmented += 1\n"
        "    first, *starred = (1, 2, 3)\n"
        "    for looped in ():\n"
        "        pass\n"
        "    with open('x') as managed:\n"
        "        pass\n"
        "    try:\n"
        "        pass\n"
        "    except ValueError as caught:\n"
        "        pass\n"
        "    import json\n"
        "    from os import path as renamed\n"
        "    if (walrus := 3):\n"
        "        pass\n"
        "    def nested():\n"
        "        inner_only = 1\n"
        "        return inner_only\n"
        "    return nested\n",
        "frame",
    )

    assert _frame_bound_names(definition) == frozenset(
        {
            "param",
            "args",
            "keyword",
            "rest",
            "assigned",
            "annotated",
            "augmented",
            "first",
            "starred",
            "looped",
            "managed",
            "caught",
            "json",
            "renamed",
            "walrus",
            "nested",
        }
    )


def test_frame_bound_names_excludes_names_this_frame_does_not_bind(tmp_path):
    """NEGATIVE FACE: a comprehension target and a nested frame's local.

    A comprehension binds in its OWN scope, so claiming it here would be a
    claim this walk cannot authenticate -- such a callee stays a free name and
    still goes to the export door, exactly as before this walk existed.
    """
    definition = _definition(
        "def frame():\n"
        "    values = [comprehended for comprehended in ()]\n"
        "    def nested(nested_param):\n"
        "        nested_local = 1\n"
        "        return nested_local\n"
        "    return values, nested\n",
        "frame",
    )
    binders = _frame_bound_names(definition)

    assert "values" in binders
    assert "nested" in binders
    assert "comprehended" not in binders
    assert "nested_param" not in binders
    assert "nested_local" not in binders


# --------------------------------------------------------------------------
# The scan reaches METHODS, not only module-level functions
#
# The class arm was absent, and its absence was not a reporting gap: a method
# calling a name with no authenticated defining source CONSTRUCTED, and the
# unresolvable call was content-addressed into the manager-construction CID.
# Whether a body is spelled as a function or as a method is syntax; it must not
# decide whether construction authenticates its callees.
# --------------------------------------------------------------------------


_ABSENT_FROM_ARTIFACT_METHOD = (
    "class Slot:\n"
    "    def __init__(self, label):\n"
    "        self.label = absent_from_artifact(label)\n"
    "\n"
    "def make_guard(expected):\n"
    "    return Slot(expected)\n"
)

_CALLED_PARAMETER_METHOD = (
    "class Slot:\n"
    "    def __init__(self, helper):\n"
    "        self.label = helper()\n"
    "\n"
    "def make_guard(expected):\n"
    "    return Slot(expected)\n"
)


def test_method_calling_an_absent_symbol_refuses_instead_of_fabricating(tmp_path):
    """LYING TWIN, and the reason this arm exists.

    Before the class arm, this exact source produced a
    ``ConstructedManagerBehaviorV1`` whose receiver field held a
    ``CallSiteValue`` with ``body=None``, ``source_call_frame_cid=None`` and
    ``authenticated_target_symbol=None`` -- an unauthenticated call, carried
    into ``receiver_state.identity`` and from there into
    ``manager_construction_cid``.  A construction CID asserting an
    authenticated receiver over a call the system could not see through is a
    fabricated contract, which ``_resolve_external_call_frame`` explicitly
    promises never to yield.
    """
    gap = _opaque_gap(tmp_path, _ABSENT_FROM_ARTIFACT_METHOD)

    assert gap.observed == "call-target-source-absent:absent_from_artifact"


def test_method_calling_a_parameter_is_a_value_call_target(tmp_path):
    """A called parameter is higher-order dispatch inside a method too."""
    gap = _opaque_gap(tmp_path, _CALLED_PARAMETER_METHOD)

    assert gap.observed == "value-call-target:helper"


def test_method_calling_a_module_definition_still_constructs(tmp_path):
    """TRUTHFUL TWIN: the arm refuses unauthenticated callees, not methods.

    Same class, same call shape, callee authenticated in this artifact.  If
    this went red the arm would be refusing syntax rather than opacity.
    """
    result = _construct(
        tmp_path,
        "def picked(value):\n"
        "    return 7\n"
        "\n"
        "class Slot:\n"
        "    def __init__(self, label):\n"
        "        self.label = picked(label)\n"
        "\n"
        "def make_guard(expected):\n"
        "    return Slot(expected)\n",
    )

    assert isinstance(result, ConstructedManagerBehaviorV1), result


@pytest.mark.parametrize(
    "spelling,source",
    [
        ("method", _ABSENT_FROM_ARTIFACT_METHOD),
        (
            "function",
            "def make_guard(expected):\n    return absent_from_artifact(expected)\n",
        ),
    ],
)
def test_both_spellings_of_the_same_opacity_reach_the_same_kind(
    tmp_path, spelling, source
):
    """DISCRIMINATION: the two faces must AGREE.

    Asserting each spelling separately would still pass if one silently
    constructed -- which is exactly what the method face used to do.  This is
    the assertion that cannot: same condition, same kind, whichever syntax
    carries it.
    """
    gap = _opaque_gap(tmp_path, source)

    assert gap.observed == "call-target-source-absent:absent_from_artifact", spelling


def test_scanned_definitions_reaches_methods_and_nothing_else(tmp_path):
    """The scan universe, read directly off a class and a function."""
    from sugar_lift_python_source.manager_construction import _scanned_definitions
    from sugar_source_tree.nodes import ClassDef

    source = (
        "class Slot:\n"
        "    field = 1\n"
        "    def first(self):\n"
        "        return 1\n"
        "    def second(self):\n"
        "        return 2\n"
        "\n"
        "def loose():\n"
        "    return 3\n"
    )
    tree = SourceFile((source, "scan.py", blake3_512_of(source.encode())))
    klass = next(n for n in tree.root.body if isinstance(n, ClassDef))
    function = next(
        n for n in tree.root.body if isinstance(n, FunctionDef) and n.name == "loose"
    )

    assert tuple(d.name for d in _scanned_definitions(klass)) == ("first", "second")
    assert tuple(d.name for d in _scanned_definitions(function)) == ("loose",)


# --------------------------------------------------------------------------
# A reachable class's import receipts are seated before ANY class sugar
#
# A subclass builds its local base's sugar.  A Name sugar built over an
# imported coordinate that is not seated yet is a free name for the life of
# the node, so the base's ``isinstance(x, Pattern)`` used to halt on a free
# ``Pattern`` unless the module happened to be rebuilt after seating.
# --------------------------------------------------------------------------


_BASE_READS_IMPORTED_TYPE = (
    "from re import Pattern\n"
    "\n"
    "\n"
    "class Base:\n"
    "    def __init__(self, expected):\n"
    "        self.is_pattern = isinstance(expected, Pattern)\n"
    "\n"
    "\n"
    "class Guard(Base):\n"
    "    def __init__(self, expected):\n"
    "        super().__init__(expected)\n"
    "\n"
    "    def __enter__(self):\n"
    "        return self\n"
    "\n"
    "    def __exit__(self, *exc):\n"
    "        return False\n"
    "\n"
    "\n"
    "def make_guard(expected):\n"
    "    return Guard(expected)\n"
)


def test_base_class_import_member_is_cited_on_the_first_build(tmp_path):
    """POSITIVE: one build decides ``isinstance(23, re.Pattern)``.

    The base class reads the imported ``Pattern``; the subclass is the one
    constructed.  The receiver completes with the field decided, not halted
    on a free ``Pattern``.
    """
    built = _construct(tmp_path, _BASE_READS_IMPORTED_TYPE)

    state = built.receiver_state
    assert type(state).__name__ == "ObjectValue", state
    assert state.class_name == "Guard"
    assert {f.name: type(f.value).__name__ for f in state.fields} == {
        "is_pattern": "FalseBoolLiteralSugar"
    }
    assert "_Var(name='Pattern')" not in repr(built)


def test_module_bound_spelling_is_not_cited_as_the_import_member(tmp_path):
    """LYING TWIN: the same spelling bound by the module itself is no import.

    Nothing authenticates a module-level ``Pattern`` as ``re.Pattern``, so the
    type operand stays the dynamic boundary and no decided field appears.
    """
    local = _BASE_READS_IMPORTED_TYPE.replace(
        "from re import Pattern\n", "class Pattern:\n    pass\n"
    )
    built = _construct(tmp_path, local)

    state = built.receiver_state
    assert type(state).__name__ == "ReceiverStatePartitionValue", state
    assert "DynamicTypeOperandRuntimeEffect" in repr(state)
    assert "re.Pattern" not in repr(built)


# --------------------------------------------------------------------------
# function-local import -- a frame binder that names a static export
# --------------------------------------------------------------------------


def test_function_local_import_callee_resolves_like_a_module_import(tmp_path):
    """POSITIVE: ``from m import g`` inside the frame is the export ``m.g``.

    The module-level spelling and the function-local spelling bind the same
    static export, so both faces get the same verdict from the same door
    (here the stdlib callee is off-population). Neither is a
    value-call-target.
    """
    module_level = _construct(
        tmp_path / "module",
        "from contextlib import nullcontext\n\n"
        "def make_guard(expected):\n    return nullcontext()\n",
    )
    local = _construct(
        tmp_path / "local",
        "def make_guard(expected):\n"
        "    if expected:\n"
        "        from contextlib import nullcontext\n\n"
        "        return nullcontext()\n"
        "    return None\n",
    )
    assert isinstance(module_level, ManagerConstructionGapV1)
    assert isinstance(local, ManagerConstructionGapV1)
    assert local.kind == module_level.kind == "call-target-off-population"


def test_local_import_that_does_not_dominate_the_call_stays_a_value(tmp_path):
    """NEGATIVE: the import runs only on one branch; the call runs after it.

    With ``expected=23`` the import is skipped and Python raises
    ``UnboundLocalError`` at the call, so the call is not the export.
    """
    gap = _opaque_gap(
        tmp_path,
        "def make_guard(expected):\n"
        "    if not expected:\n"
        "        from contextlib import nullcontext\n"
        "    return nullcontext()\n",
    )
    assert gap.observed == "value-call-target:nullcontext"


def test_local_import_rebound_in_the_frame_stays_a_value(tmp_path):
    """NEGATIVE: another binder of the same name makes the callee a value."""
    gap = _opaque_gap(
        tmp_path,
        "def make_guard(expected):\n"
        "    from contextlib import nullcontext\n"
        "    nullcontext = expected\n"
        "    return nullcontext()\n",
    )
    assert gap.observed == "value-call-target:nullcontext"
