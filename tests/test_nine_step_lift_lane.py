"""Teeth for tools/nine_step_lift_lane.py: a corpus's own edges bind at prove.

The lane mints every module alone, then proves each with the same-corpus
proofs that answer its calls staged in ``.sugar/imports/`` (the federation
shape, examples/python-base64-federation/run.sh). These tests pin which
proofs are staged, how a call edge is sorted (corpus, boundary, dispatch),
and how an edge that did not bind is named.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from argparse import Namespace
from pathlib import Path

import repo_root_test_support  # noqa: F401 -- puts tools/ on sys.path

import nine_step_lift_lane as lane

HEX = "0123456789abcdef"


def cid(n: int) -> str:
    return "blake3-512:" + (HEX[n % 16] * 96) + f"{n:032x}"


def key(n: int) -> str:
    return lane.cid_key(cid(n))


def corpus() -> lane.CorpusModules:
    return lane.CorpusModules(
        "pkg",
        {
            "pkg": "__init__.py",
            "pkg.core.frame": "core/frame.py",
            "pkg.core.series": "core/series.py",
            "pkg.core.empty": "core/empty.py",
            "pkg._libs": "_libs/__init__.py",
        },
        {"pkg._libs.lib"},
    )


# -- module names and symbols ------------------------------------------------


def test_module_name_is_the_kits_speller():
    assert lane.module_name("pkg", "core/frame.py") == "pkg.core.frame"
    assert lane.module_name("pkg", "core/__init__.py") == "pkg.core"
    assert lane.module_name("pkg", "__init__.py") == "pkg"


def test_scan_finds_python_and_compiled_modules(tmp_path):
    root = tmp_path / "pkg"
    for rel in ("__init__.py", "core/__init__.py", "core/frame.py", "_libs/__init__.py"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("")
    (root / "_libs/lib.cpython-312-x86_64-linux-gnu.so").write_bytes(b"")
    (root / "_libs/lib.pyi").write_text("")
    (root / "core/frame.pyi").write_text("")  # a stub beside its .py
    files = sorted(p for p in root.rglob("*.py"))
    modules = lane.CorpusModules.scan(root, files)
    assert modules.python["pkg.core.frame"] == "core/frame.py"
    assert modules.python["pkg"] == "__init__.py"
    assert "pkg._libs.lib" in modules.compiled
    assert "pkg.core.frame" not in modules.compiled


def test_longest_prefix_names_the_defining_module():
    modules = corpus()
    assert modules.target("pkg.core.frame.DataFrame.merge") == ("python", "core/frame.py")
    assert modules.target("pkg.DataFrame") == ("python", "__init__.py")
    # A compiled submodule wins over its package's __init__.py.
    assert modules.target("pkg._libs.lib.is_list_like") == ("compiled", "pkg._libs.lib")
    assert modules.target("other.thing") == ("absent", None)


def test_edge_kinds():
    modules = corpus()
    assert lane.edge_kind("python:pkg.core.series.Series", modules) == "corpus"
    assert lane.edge_kind("python:pkg.core.series.Series#0~1", modules) == "corpus"
    assert lane.edge_kind("python:numpy.asarray", modules) == "boundary"
    assert lane.edge_kind("python:builtins.len", modules) == "boundary"
    assert lane.edge_kind("python:pkg._libs.lib.is_list_like", modules) == "boundary"
    assert lane.edge_kind("python:dispatch:append", modules) == "dispatch"
    assert lane.edge_kind("c:strlen", modules) == "boundary"


def test_join_symbol_drops_the_shares_mark_only_on_python_symbols():
    assert lane.join_symbol("python:pkg.core.frame.f#0~1,0~global:G") == "python:pkg.core.frame.f"
    assert lane.join_symbol("python:dispatch:m#0~1") == "python:dispatch:m#0~1"


# -- reading a proof's members -----------------------------------------------


def member(kind: str, **header) -> dict:
    return {"header": {"kind": kind, **header}, "body": {}}


def bridge(symbol: str, target: str) -> dict:
    return {"header": {"kind": "bridge"}, "body": {"sourceSymbol": symbol, "targetContractCid": target}}


def unanswered(symbol: str | None) -> dict:
    return member("undecided", symbol=symbol, reason={"unanswered": {}}, site={"file": "x", "startLine": 1})


def test_classify_members_sorts_edges_and_reads_answers():
    members = {
        cid(1): member("contract", symbol="python:pkg.core.series.Series"),
        cid(2): bridge("python:pkg.core.series.Series", cid(1)),
        # A bridge whose target is not this proof's contract answers nothing here.
        cid(3): bridge("python:pkg.core.frame.DataFrame", cid(99)),
        cid(4): unanswered("python:pkg.core.frame.DataFrame"),
        cid(5): unanswered("python:numpy.asarray"),
        cid(6): unanswered("python:dispatch:append"),
        cid(7): unanswered(None),
        cid(8): member(
            "undecided", symbol="python:pkg.core.series.g",
            reason={"refused": {"owner": "o", "observed": "x"}}, site={"file": "f", "startLine": 2},
        ),
    }
    got = lane.classify_members(members, {"g"}, "pkg/core/series.py", corpus())
    assert got["contracts"] == 1
    assert got["unanswered"] == 4  # the old count, unchanged
    assert got["answers"] == ["python:pkg.core.series.Series"]
    assert got["edges"] == [["python:pkg.core.frame.DataFrame", key(4)]]
    assert got["dispatchEdges"] == [key(6)]
    assert got["boundaryEdges"] == 1
    assert [r["owner"] for r in got["refusals"]] == ["o"]


def test_member_field_reads_every_envelope_layer():
    assert lane.member_field({"metadata": {"sourceSymbol": "s"}}, "sourceSymbol") == "s"
    assert lane.member_field({"envelope": {"header": {"kind": "bridge"}}}, "kind") == "bridge"


# -- staging and binding -----------------------------------------------------


def minted_rows() -> dict[str, dict]:
    def row(rel, answers, edges, stored=True):
        return {
            "file": rel, "minted": stored, "stored": f"{rel}/blake3-512_{abs(hash(rel)):x}.proof" if stored else None,
            "answers": answers, "edges": edges, "dispatchEdges": [], "boundaryEdges": 0,
            "mint": {"rc": 0, "seconds": 1.0}, "refusals": [],
        }

    return {
        "core/frame.py": row(
            "core/frame.py",
            ["python:pkg.core.frame.helper"],
            [
                ["python:pkg.core.series.Series", key(10)],  # cross-module, answered
                ["python:pkg.core.frame.helper", key(11)],  # same module
                ["python:pkg.core.series.attr", key(12)],  # series states no bridge
                ["python:pkg.core.empty.f", key(13)],  # empty.py packaged no proof
                ["python:pkgx.y", key(14)],  # unreachable: not this package
                ["python:pkg.core.series.Series#0~1", key(15)],  # answered, dropped
            ],
        ),
        "core/series.py": row("core/series.py", ["python:pkg.core.series.Series"], []),
        "core/empty.py": row("core/empty.py", [], [], stored=False),
        "__init__.py": row("__init__.py", ["python:pkg.top"], []),
    }


def index() -> lane.BindIndex:
    rows = minted_rows()
    return lane.BindIndex(corpus(), rows, set(rows))


def test_imports_are_exactly_the_other_proofs_that_answer_an_edge():
    idx = index()
    assert idx.imports_for(minted_rows()["core/frame.py"]) == ["core/series.py"]
    assert idx.imports_for(minted_rows()["core/series.py"]) == []


def test_bind_edges_names_every_miss():
    idx = index()
    row = minted_rows()["core/frame.py"]
    report = {
        "rows": [
            {"propertyCid": cid(12), "dischargeMethod": "undecided", "reason": "owed: no contract"},
            {"propertyCid": cid(13), "dischargeMethod": "undecided", "reason": "owed: no contract"},
            {"propertyCid": cid(15), "dischargeMethod": "undecided", "reason": "owed"},
            {
                "propertyCid": cid(50), "dischargeMethod": "solver",
                "reason": "refused: ambiguous-target for python:pkg.core.series.Series",
            },
        ]
    }
    got = lane.bind_edges(row, report, None, idx)
    # key(14) is not a corpus edge at mint time; here it stands only to show a
    # symbol no enrolled module prefixes binds where prove joined it.
    assert got["corpusEdges"] == 6
    assert got["crossModule"] == 5 and got["sameModule"] == 1
    assert got["bound"] == 3  # Series (key 10), helper (11), pkgx (14: not owed)
    reasons = {m["symbol"]: m["reason"] for m in got["misses"]}
    assert reasons == {
        "python:pkg.core.series.attr": "target-not-stated",
        "python:pkg.core.empty.f": "target-module-no-proof",
        "python:pkg.core.series.Series": "not-joined:ambiguous-target",
    }


def test_bind_edges_without_a_report_names_the_prove_failure():
    idx = index()
    got = lane.bind_edges(minted_rows()["core/frame.py"], None, "prove-timeout", idx)
    assert got["bound"] == 0
    assert {m["reason"] for m in got["misses"]} == {"prove-timeout"}


def test_target_in_another_seat_and_not_enrolled():
    rows = minted_rows()
    idx = lane.BindIndex(corpus(), rows, {"core/frame.py"})
    row = {
        "file": "core/frame.py",
        "edges": [["python:pkg.core.empty.f", key(13)], ["python:pkgless", key(16)]],
    }
    report = {"rows": [
        {"propertyCid": cid(13), "dischargeMethod": "undecided"},
        {"propertyCid": cid(16), "dischargeMethod": "undecided"},
    ]}
    reasons = [m["reason"] for m in lane.bind_edges(row, report, None, idx)["misses"]]
    assert reasons == ["target-module-other-seat", "target-module-not-enrolled"]


# -- prove reads the staged imports (a stand-in binary) ----------------------

FAKE_SUGAR = """#!{python}
import json, pathlib, sys
args = sys.argv[1:]
assert args[0] == "prove", args
project = pathlib.Path(args[-2])
own = sorted(p.name for p in project.glob("*.proof"))
imports = sorted(p.name for p in (project / ".sugar" / "imports").glob("*.proof"))
# The member is joined exactly when the answering proof is staged.
rows = [] if "blake3-512_series.proof" in imports else [
    {{"propertyCid": "{owed}", "dischargeMethod": "undecided", "reason": "owed"}}
]
print(json.dumps({{"rows": rows, "verdict": "owed", "own": own, "imports": imports,
                  "loadErrors": []}}))
"""


def test_prove_one_stages_the_answering_proof_and_binds(tmp_path):
    root = tmp_path / "pkg"
    (root / "core").mkdir(parents=True)
    (root / "core/frame.py").write_text("from pkg.core.series import Series\nSeries()\n")
    store = tmp_path / "store"
    for rel, name in (("core/frame.py", "frame"), ("core/series.py", "series"), ("core/other.py", "other")):
        (store / rel).mkdir(parents=True)
        (store / rel / f"blake3-512_{name}.proof").write_bytes(name.encode())
    minted = {
        "core/frame.py": {
            "file": "core/frame.py", "stored": "core/frame.py/blake3-512_frame.proof",
            "answers": [], "edges": [["python:pkg.core.series.Series", key(10)]],
            "dispatchEdges": [], "boundaryEdges": 2, "mint": {"rc": 0, "seconds": 1.0},
            "minted": True, "refusals": [], "seconds": 1.0,
        },
        "core/series.py": {
            "file": "core/series.py", "stored": "core/series.py/blake3-512_series.proof",
            "answers": ["python:pkg.core.series.Series"], "edges": [],
        },
        "core/other.py": {
            "file": "core/other.py", "stored": "core/other.py/blake3-512_other.proof",
            "answers": ["python:pkg.core.other.f"], "edges": [],
        },
    }
    idx = lane.BindIndex(corpus(), minted, set(minted))
    fake = tmp_path / "sugar"
    fake.write_text(FAKE_SUGAR.format(python=sys.executable, owed=cid(10)))
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    work = tmp_path / "work"
    work.mkdir()
    row = lane.prove_one(str(fake), root, minted["core/frame.py"], work, store, 300, idx)
    assert row["prove"]["imports"] == 1
    assert row["prove"]["error"] is None
    assert row["binding"]["corpusEdges"] == 1
    assert row["binding"]["bound"] == 1, row["binding"]
    assert row["binding"]["misses"] == []
    assert row["binding"]["boundaryEdges"] == 2
    assert row["status"] == "lifted"
    assert list(work.iterdir()) == []  # the per-file project is scratch


# -- join --------------------------------------------------------------------


def test_join_counts_edges_and_writes_the_misses(tmp_path):
    seat = tmp_path / "s0"
    seat.mkdir()
    rows = [
        {
            "file": "core/frame.py", "defs": 2, "minted": True, "refusals": [], "refusedDefs": 0,
            "unanswered": 4, "status": "lifted",
            "prove": {"imports": 1, "loadErrors": 0, "error": None},
            "binding": {
                "corpusEdges": 3, "bound": 1, "crossModule": 2, "crossModuleBound": 1,
                "sameModule": 1, "sameModuleBound": 0, "boundaryEdges": 5,
                "dispatchEdges": 2, "dispatchAnswered": 1,
                "misses": [
                    {"symbol": "python:pkg.a", "reason": "target-not-stated", "target": "__init__.py"},
                    {"symbol": "python:pkg.core.frame.h", "reason": "not-joined", "target": "core/frame.py"},
                ],
            },
        },
        {
            "file": "core/empty.py", "defs": 1, "minted": False, "status": "timeout",
            "refusals": [{"owner": "mint-timeout", "symbol": None, "isDef": False,
                          "file": "core/empty.py", "line": None, "observed": "timeout"}],
            "prove": None, "binding": None,
        },
    ]
    (seat / "rows.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    out = tmp_path / "summary.json"
    misses = tmp_path / "edge-misses.json"
    args = Namespace(join=[str(seat)], label="pkg", enrolled=3, out=str(out),
                     refusals=None, edge_misses=str(misses), top=8)
    assert lane.join(args) == 0
    summary = json.loads(out.read_text())
    # The counting definitions are unchanged.
    assert summary["files_lifted"] == 1 and summary["files_missing"] == 1
    assert summary["funcs_lifted"] == 2 and summary["funcs_total"] == 3
    assert summary["refused"] == 1 and summary["unanswered_edges"] == 4
    # The edges.
    assert summary["corpus_edges"] == 3 and summary["corpus_edges_bound"] == 1
    assert summary["cross_module_edges"] == 2 and summary["cross_module_edges_bound"] == 1
    assert summary["corpus_edge_misses"] == 2
    assert summary["corpus_edge_misses_by_reason"] == {"target-not-stated": 1, "not-joined": 1}
    assert summary["boundary_edges"] == 5 and summary["dispatch_edges_answered"] == 1
    assert summary["imports_staged"] == 1
    listing = json.loads(misses.read_text())["misses"]
    assert {entry["reason"] for entry in listing} == {"target-not-stated", "not-joined"}
    assert listing[0]["symbols"][0]["files"] == ["core/frame.py"]


def test_prior_reads_each_phase(tmp_path):
    rows = tmp_path / "rows.jsonl"
    rows.write_text(json.dumps({"file": "a.py", "seconds": 9.0,
                                "mint": {"seconds": 2.0}, "prove": {"seconds": 7.0}}) + "\n")
    assert lane.load_prior([str(rows)], "mint") == {"a.py": 2.0}
    assert lane.load_prior([str(rows)], "prove") == {"a.py": 7.0}
    assert lane.load_prior([str(rows)]) == {"a.py": 9.0}


def test_reserve_is_half_the_budget_without_a_prior(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    assert lane.prove_reserve(tmp_path, ["a.py"], {}, 4, 1000, 300) == 500
    assert lane.prove_reserve(tmp_path, ["a.py"], {"a.py": 40.0}, 4, 1000, 300) == 10 + 300 + 60
    assert lane.prove_reserve(tmp_path, ["a.py"], {"a.py": 1e6}, 1, 1000, 300) == 750


def test_link_or_copy(tmp_path):
    source = tmp_path / "a.proof"
    source.write_bytes(b"x")
    target = tmp_path / "imports" / "a.proof"
    lane.link_or_copy(source, target)
    assert target.read_bytes() == b"x"
    assert os.path.samefile(source, target) or target.read_bytes() == b"x"


# -- the stalled files' kit profiles (instrument only) ------------------------

FAKE_PROFILING_SUGAR = """#!{python}
import json, os, pathlib, sys
args = sys.argv[1:]
assert args[0] == "mint", args
out = pathlib.Path(os.environ["SUGAR_KIT_PROFILE_DIR"])
assert out.is_absolute(), out
deadline = os.environ["SUGAR_LIFT_RESPONSE_TIMEOUT_SECS"]
for pid, samples in ((11, 3), (12, 40)):
    (out / f"kit-profile-{{pid}}.json").write_text(json.dumps({{
        "samples": samples, "elapsedSeconds": 1.5, "deadline": deadline,
        "request": {{"inFlight": "sugar.enumerate:universe", "id": 62}},
        "requests": {{"sugar.enumerate:universe": samples}},
        "self": [{{"frame": f"f{{i}}", "samples": 1}} for i in range(20)],
        "inclusive": [{{"frame": "g", "samples": samples}}],
    }}))
print("lift plugin transport stalled at stage=read_line.enter message_id=62", file=sys.stderr)
sys.exit(1)
"""


def test_mint_stalled_is_the_ceiling_or_the_kit_deadline():
    assert lane.mint_stalled({"mint": {"rc": None, "error": "timeout"}})
    assert lane.mint_stalled({"mint": {"rc": 1, "error": "x: transport stalled at y"}})
    assert not lane.mint_stalled({"mint": {"rc": 1, "error": "LifterRefusal: z"}})
    assert not lane.mint_stalled({"mint": {"rc": 0, "error": None}, "dumpTimeout": True})
    assert not lane.mint_stalled({"file": "a.py"})


def test_profile_one_reads_the_heaviest_kit_profile_and_keeps_no_proof(tmp_path):
    root = tmp_path / "pkg"
    (root / "tests").mkdir(parents=True)
    (root / "tests/test_matmul.py").write_text("def test_a():\n    x = 1\n")
    fake = tmp_path / "sugar"
    fake.write_text(FAKE_PROFILING_SUGAR.format(python=sys.executable))
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    work = tmp_path / "work"
    work.mkdir()
    profiles = tmp_path / "profiles"
    row = lane.profile_one(str(fake), root, "tests/test_matmul.py", work, profiles, 300)
    assert row["file"] == "tests/test_matmul.py"
    assert row["status"] == "profiled"
    assert row["profile"]["rc"] == 1
    assert "transport stalled" in row["profile"]["error"]
    assert row["profile"]["dir"] == "tests__test_matmul.py"
    summary = row["profile"]["summary"]
    assert summary["path"] == "kit-profile-12.json"
    assert summary["samples"] == 40
    assert len(summary["self"]) == lane.PROFILE_TOP_FRAMES
    assert summary["request"]["id"] == 62
    # The CLI's response deadline was raised to the file ceiling.
    kept = json.loads((profiles / "tests__test_matmul.py" / "kit-profile-12.json").read_text())
    assert kept["deadline"] == "300"
    assert list(work.iterdir()) == []  # the project is scratch: no proof kept


def test_run_adds_env_to_the_inherited_environment(tmp_path):
    rc, out, _, _ = lane.run(
        [sys.executable, "-c", "import os; print(os.environ['LANE_T'], 'PATH' in os.environ)"],
        cwd=tmp_path, timeout=30, env={"LANE_T": "on"},
    )
    assert rc == 0 and out.split() == ["on", "True"]
