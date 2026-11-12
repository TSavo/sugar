"""`sugar mint` and the board's door read different content for the same file (#7796).

Plan row 5 (the board reads the one lift). Measured on main at ``af341f3cd``
with a 16-line module: a same-module context manager class, a function that
enters it, and a test function.

What ``sugar mint`` does today on this module:

- 10 ``sugar.enumerate`` demands (``source_files`` 1, ``functions`` 1,
  ``universe`` 1, ``facts`` 1, ``assertions`` 1, ``call_sites`` 5);
- ``distribution`` is ``None`` on all 10 (the only option key sent is
  ``auditFrontier``; no Rust source names a distribution);
- 0 calls to ``populate_source_derived_resource_refs``;
- the ``with`` is refused: ``CONTEXT MANAGER RESOLUTION GAP
  [With._construct_sugar] ... no contract ref: runtime-selected``;
- the mint fails.

What the board's door does on the same file (``facts`` with a distribution
named):

- 1 demand, 1 call to populate;
- the ``with`` has a ``SourceDerivedContextManagerRefV1`` row and is built; the
  audit returns with 0 panics.

So the tree the board counts and the rows a proof is made from have different
content. The twin below states what the module's proof should say and is RED on
main, because the mint fails; it is a plain failing test, not skipped and not
marked. It goes green when mint and the board read the same content.

The second test pins the measured fact itself and passes on main. It pins a
defect, so that nobody can say it was never measured: DELETE it when #7796 is
fixed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root
from sugar_lift_py_tests.witness_harness import (
    _ensure_sugar_bin,
    _stage_cli_project,
    mint_project,
    run_source_through_real_solver,
)

_MODULE = (
    "class Resource:\n"
    "    def __init__(self, target):\n"
    "        self.target = target\n"
    "    def __enter__(self):\n"
    "        return self.target\n"
    "    def __exit__(self, *exc):\n"
    "        pass\n"
    "\n"
    "\n"
    "def f():\n"
    "    with Resource(1) as value:\n"
    "        return value\n"
    "\n"
    "\n"
    "def test_f():\n"
    "    assert f() == {claim}\n"
)


def test_a_with_over_a_same_module_manager_reaches_the_solver(tmp_path: Path) -> None:
    """RED on main: ``f()`` enters ``Resource(1)`` and returns 1.

    The truthful claim is ``sat`` and the lying one ``unsat`` once mint builds
    the ``with`` the board's door already builds.
    """
    truthful = run_source_through_real_solver(tmp_path / "t", _MODULE.format(claim=1))
    lying = run_source_through_real_solver(tmp_path / "l", _MODULE.format(claim=2))
    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"


# Counts populate calls inside whatever interpreter starts with this directory
# first on ``PYTHONPATH``: Python imports ``sitecustomize`` at startup.
_COUNTING_SITECUSTOMIZE = '''
import os

_OUT = os.environ.get("SUGAR_TEST_POPULATE_CALLS")
if _OUT:
    import sugar_lift_python_source.manager_summary_derivation as _msd

    with open(_OUT, "a", encoding="utf-8") as _stream:
        _stream.write("kit-started\\n")
    _populate = _msd.populate_source_derived_resource_refs

    def _counted(source_file, **kwargs):
        with open(_OUT, "a", encoding="utf-8") as stream:
            stream.write("populate\\n")
        return _populate(source_file, **kwargs)

    _msd.populate_source_derived_resource_refs = _counted
'''

# The board's door for one file: ``sugar.enumerate`` level ``facts`` with the
# audit frontier and a distribution named, through the board's own consumer.
_BOARD_DOOR = r'''
import json, sys
from pathlib import Path

sys.path.insert(0, SCRIPTS)
import recensus_enumerate_consumer as consumer
from sugar_lift_py_tests.corpus_pin import pin_corpus
from sugar_lift_python_source.source_oracle import path_source

root = Path(ROOT)
pin_corpus(root, distribution="tiny-corpus", version="0.0.1")
_source, _seat, cid = path_source(str(root / "test_witness.py"))
audit, gaps = consumer.demand_construction_residual(
    workspace_root=root,
    file_rel="test_witness.py",
    source_cid=cid,
    distribution="tiny-corpus",
    source_workspace_root=root,
)
core = (audit or {}).get("semanticCore") or (audit or {})

# What the `with` is on the context that open populated.
from sugar_source_tree.nodes import With
from sugar_source_tree.process_resident_file import _RESIDENT

with_rows = []
for (resident_cid, _resident_seat), entry in list(_RESIDENT.items()):
    context = entry.source_file.unit.construction_context
    if resident_cid != cid or context is None:
        continue
    site = next(n for n in entry.source_file.nodes() if isinstance(n, With))
    line = site.line_col_span().start_line
    refs = context.source_derived_contract_refs
    with_rows = [type(refs[k]).__name__ for k in refs if k.start_line == line]
print("RESULT_JSON " + json.dumps({
    "audit": audit is not None,
    "gaps": len(gaps),
    "panics": len(core.get("panics") or []),
    "with_rows": with_rows,
}))
'''


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def test_mint_never_calls_populate_and_the_board_door_calls_it_once(
    tmp_path: Path, monkeypatch
) -> None:
    """Pins a DEFECT (#7796); delete this test when it is fixed.

    One module, two doors, one counter. During a real ``sugar mint`` the kit
    calls populate zero times; through the board's ``facts`` door it is called
    once, and the file's ``with`` is built.
    """
    hook = tmp_path / "hook"
    hook.mkdir()
    (hook / "sitecustomize.py").write_text(_COUNTING_SITECUSTOMIZE, encoding="utf-8")
    module = _MODULE.format(claim=1)

    # Door 1: real ``sugar mint``. The kit is the process the staged wrapper
    # starts; put the counter first on the PYTHONPATH that wrapper hands it.
    mint_calls = tmp_path / "mint-calls.txt"
    project = tmp_path / "mint"
    _stage_cli_project(project, module)
    wrapper = project / ".sugar" / "lift" / "python" / "proofir_python_lift_capture"
    staged = wrapper.read_text(encoding="utf-8")
    marker = "        'PYTHONPATH': PYTHONPATH,\n"
    assert staged.count(marker) == 1, "the staged kit wrapper changed shape"
    wrapper.write_text(
        staged.replace(
            marker,
            f"        'PYTHONPATH': {str(hook)!r} + os.pathsep + PYTHONPATH,\n",
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SUGAR_TEST_POPULATE_CALLS", str(mint_calls))
    mint_project(project, sugar_bin=_ensure_sugar_bin())
    capture = project / ".sugar" / "lift" / "python" / "lift-rpc-capture.jsonl"
    assert len(_lines(capture)) >= 1, "mint never reached the kit; zero would mean nothing"
    assert "kit-started" in _lines(mint_calls), "the counter did not load in the kit"
    assert _lines(mint_calls).count("populate") == 0

    # Door 2: the board's door, in its own process, under the same counter.
    board_calls = tmp_path / "board-calls.txt"
    root = tmp_path / "board" / "c"
    root.mkdir(parents=True)
    (root / "test_witness.py").write_text(module, encoding="utf-8")
    (tmp_path / "board" / "c.identity.json").write_text(
        json.dumps({"distribution": "tiny-corpus", "version": "0.0.1"}),
        encoding="utf-8",
    )
    scripts = sugar_lift_py_tests_package_root() / "scripts"
    program = f"ROOT = {str(root)!r}\nSCRIPTS = {str(scripts)!r}\n" + _BOARD_DOOR
    env = {
        **os.environ,
        "SUGAR_TEST_POPULATE_CALLS": str(board_calls),
        "PYTHONPATH": os.pathsep.join([str(hook), *[p for p in sys.path if p]]),
    }
    completed = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        timeout=600,
        env=env,
    )
    line = next(
        (ln for ln in completed.stdout.splitlines() if ln.startswith("RESULT_JSON ")),
        None,
    )
    assert line is not None, (
        "the board door produced no result.\n"
        f"returncode={completed.returncode}\n"
        f"stdout tail={completed.stdout[-1500:]}\n"
        f"stderr tail={completed.stderr[-1500:]}"
    )
    assert json.loads(line[len("RESULT_JSON ") :]) == {
        "audit": True,
        "gaps": 0,
        "panics": 0,
        "with_rows": ["SourceDerivedContextManagerRefV1"],
    }
    assert _lines(board_calls).count("populate") == 1
