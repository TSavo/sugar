"""#7838, inventory item 44: a proof member does not depend on process history.

The same file is minted three ways, each by real ``sugar mint`` in its own
process: alone, after a predecessor file that builds mutation shadow nodes of
its own, and alone under a different ``PYTHONHASHSEED``. The members that come
from the shared file must be the same members, by CID, every time.
"""

from __future__ import annotations

import json
from pathlib import Path

import cbor2

from sugar_lift_py_tests.witness_harness import _stage_cli_project, mint_project

_SHARED = """\
def build(n):
    out = []
    i = 0
    while i < n:
        out.append(i)
        i += 1
    out.append(0)
    return out


def test_build():
    got = build(2)
    assert len(got) == 3
"""

_PREDECESSOR = """\
def churn(n):
    acc = []
    acc.append(n)
    acc.append(n + 1)
    seen = {}
    seen.update({n: 1})
    return acc


def test_churn():
    assert len(churn(1)) == 2
"""


def _shared_members(project: Path) -> dict[str, bytes]:
    run = mint_project(project)
    assert run.returncode == 0, run.stderr[-4000:]
    (proof,) = list(project.glob("*.proof"))
    catalog = cbor2.loads(proof.read_bytes())
    members = {}
    for cid, raw in catalog["members"].items():
        text = raw.decode() if isinstance(raw, bytes) else json.dumps(raw)
        if "test_witness.py" in text and "a_predecessor.py" not in text:
            members[cid] = raw
    return members


def test_shared_members_are_identical_whatever_ran_before(
    tmp_path: Path, monkeypatch
) -> None:
    alone = tmp_path / "alone"
    _stage_cli_project(alone, _SHARED)
    after = tmp_path / "after"
    _stage_cli_project(after, _SHARED)
    (after / "a_predecessor.py").write_text(_PREDECESSOR, encoding="utf-8")

    monkeypatch.setenv("PYTHONHASHSEED", "1")
    first = _shared_members(alone)
    with_predecessor = _shared_members(after)
    monkeypatch.setenv("PYTHONHASHSEED", "2")
    reseeded = _shared_members(tmp_path / "alone")

    assert first, "the shared file must mint members"
    assert set(with_predecessor) == set(first)
    assert set(reseeded) == set(first)
