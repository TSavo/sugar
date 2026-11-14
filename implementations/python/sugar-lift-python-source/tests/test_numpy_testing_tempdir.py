"""``with numpy.testing.tempdir()``: stdlib callees and a two-faced finally.

``tempdir`` is ``mkdtemp(...); try: yield; finally: shutil.rmtree(...)`` with
``from tempfile import mkdtemp``.  Two laws close it:

* A name a dependency imports from a module outside its own artifact
  (``artifact-module-absent``) is followed into that module's own
  authenticated artifact; a stdlib definition is then cited
  ``call-target-off-population`` (two faces) instead of
  ``call-target-source-absent``.
* A generator ``finally`` cleanup that may complete or raise halts with its
  raise on one face and, on the other, continues the frame past the
  ``finally`` -- the completed face's statement record is never handed to
  ``__exit__`` as the generator's next transition.
"""

from __future__ import annotations

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.floor.return_value import ReturnValue
from sugar_lift_py_tests.outcome import Completed, Halted, outcome_to_exitset
from sugar_lift_python_source.dependency_artifact import (
    ResolvedPythonObjectV1,
    authenticate_dependency_top_level,
)
from sugar_lift_python_source.dependency_export_adapter import resolve_export
from sugar_lift_python_source.manager_construction import (
    _resolve_in_owning_artifact,
)
from sugar_lift_python_source.resolution_session import SourceResolutionSession
from sugar_source_tree.nodes import FunctionDef

from test_assignment_evaluates_rhs import _rows
from test_numpy_errstate_construction import _corpus, _open
from test_undetermined_raise_except_matching import _exits

TEMPDIR = (
    "from numpy.testing import tempdir\n"
    "def f():\n"
    "    with tempdir():\n"
    "        return 1\n"
)

LOCAL = (
    "import contextlib, shutil\n"
    "@contextlib.contextmanager\n"
    "def cm():\n"
    "    try:\n"
    "        yield 1\n"
    "    finally:\n"
    "        shutil.rmtree('x')\n"
    "{after}"
    "def f():\n"
    "    with cm():\n"
    "        {body}\n"
)


def _session():
    return SourceResolutionSession(
        enrolled_distributions=frozenset({"tiny-corpus", "numpy"})
    )


def test_a_name_imported_from_outside_the_artifact_resolves_in_its_own():
    graph = authenticate_dependency_top_level("numpy")
    session = _session()
    gap = resolve_export(
        graph,
        "bind-cid",
        "numpy.testing._private.utils",
        "mkdtemp",
        (),
        frozenset(),
        session=session,
    )
    assert gap.kind == "artifact-module-absent"
    hopped = _resolve_in_owning_artifact(gap, session=session)
    assert hopped is not None
    resolved, owning = hopped
    assert isinstance(resolved, ResolvedPythonObjectV1)
    assert resolved.module_name == "tempfile"
    assert resolved.definition.name == "mkdtemp"
    assert owning.distribution_artifact_cid != graph.distribution_artifact_cid


def test_a_name_its_own_artifact_does_not_define_keeps_the_gap():
    graph = authenticate_dependency_top_level("numpy")
    session = _session()
    gap = resolve_export(
        graph,
        "bind-cid",
        "numpy.testing._private.utils",
        "isfinite",
        (),
        frozenset(),
        session=session,
    )
    # An in-artifact name is not a hop: only artifact-module-absent moves.
    assert _resolve_in_owning_artifact(gap, session=session) is None


def test_tempdir_returns_under_both_stdlib_calls_and_halts_under_each(tmp_path):
    root = _corpus(tmp_path, **{"e.py": TEMPDIR})
    source_file = _open(root, "e.py", session=_session())
    func = next(
        n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    exits = outcome_to_exitset(func.sugar().desugar()).exits
    owners = {
        face.effect.producer_node_owner
        for face in exits
        if isinstance(face, Halted)
    }
    assert all(
        isinstance(face.effect, UndeterminedRaiseEffect)
        for face in exits
        if isinstance(face, Halted)
    )
    assert any("mkdtemp" in owner for owner in owners)
    assert any("shutil.rmtree" in owner for owner in owners)
    returned = [
        statement.value
        for face in exits
        if isinstance(face, Completed)
        for statement in face.value.record.statements
        if isinstance(statement, ReturnValue)
    ]
    assert returned == [TermValue(1)]


def _split(tmp_path, source):
    rows = _rows(_exits(tmp_path, source))
    returns = [payload for kind, payload, _ in rows if kind == "return"]
    halts = [payload for kind, payload, _ in rows if kind == "halt"]
    return returns, halts


def test_a_two_faced_finally_continues_the_frame_on_its_completed_face(tmp_path):
    returns, halts = _split(tmp_path, LOCAL.format(after="", body="return 1"))
    assert returns == [TermValue(1)]
    (halt,) = halts
    assert isinstance(halt, UndeterminedRaiseEffect)
    assert "shutil.rmtree" in halt.producer_node_owner


def test_statements_after_a_two_faced_finally_still_run(tmp_path):
    source = LOCAL.format(after="    shutil.copy('a', 'b')\n", body="return 1")
    returns, halts = _split(tmp_path, source)
    assert returns == [TermValue(1)]
    owners = sorted(halt.producer_node_owner for halt in halts)
    assert len(owners) == 2
    assert "shutil.rmtree" in owners[1] and "shutil.copy" in owners[0]


def test_a_body_raise_through_a_two_faced_finally(tmp_path):
    returns, halts = _split(tmp_path, LOCAL.format(after="", body="raise ValueError('b')"))
    assert returns == []
    raised = [h for h in halts if isinstance(h, RaiseEffect)]
    undetermined = [h for h in halts if isinstance(h, UndeterminedRaiseEffect)]
    assert [h.exception_name for h in raised] == ["ValueError"]
    assert len(undetermined) == 1
