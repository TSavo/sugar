"""Teeth for tools/lift_trace_bundle.py: the lift-trace artifact is the
file's refusals whole, the kit's trace filtered to the function, and small."""

from __future__ import annotations

import json

import repo_root_test_support  # noqa: F401 -- puts tools/ on sys.path

import lift_trace_bundle as bundle

SOURCE = '''\
class Frame:
    def merge(self, other):
        if other:
            x = 1
        else:
            x = 2
        return x

    @staticmethod
    def other():
        return 0


def merge():
    return 1
'''


def corpus(tmp_path):
    root = tmp_path / "pkg"
    (root / "core").mkdir(parents=True)
    (root / "core" / "frame.py").write_text(SOURCE, encoding="utf-8")
    return root


def test_the_path_is_read_with_or_without_the_package(tmp_path):
    root = corpus(tmp_path)
    assert bundle.corpus_rel(root, "pkg/core/frame.py") == "core/frame.py"
    assert bundle.corpus_rel(root, "core/frame.py") == "core/frame.py"


def test_a_function_is_its_qualname_else_every_def_of_its_name(tmp_path):
    defs = bundle.function_ranges(corpus(tmp_path) / "core" / "frame.py")
    assert bundle.wanted_ranges(defs, "Frame.merge") == [(2, 7)]
    # A qualname is matched exactly first: the module's own ``merge``.
    assert bundle.wanted_ranges(defs, "merge") == [(14, 15)]
    # No def has the qualname ``other``: every def of that bare name. A
    # decorated def starts at its decorator.
    assert bundle.wanted_ranges(defs, "other") == [(9, 11)]
    assert bundle.wanted_ranges(defs, "Frame.other") == [(9, 11)]


def test_the_blame_line_is_read_in_this_file_only():
    assert bundle.blame_line("pkg/core/frame.py:4:12", "pkg/core/frame.py") == 4
    assert bundle.blame_line("/tmp/x/project/pkg/core/frame.py:4:12", "pkg/core/frame.py") == 4
    assert bundle.blame_line("pkg/core/series.py:4:12", "pkg/core/frame.py") is None
    assert bundle.blame_line("Name(x)", "pkg/core/frame.py") is None


def test_the_bundle_keeps_the_refusals_and_filters_the_trace(tmp_path):
    root = corpus(tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    long = "read of `x` with its evaluation evaluation:" + "k" * 900 + " unbound"
    row = {
        "file": "core/frame.py",
        "minted": True,
        "stored": None,
        "refusals": [
            {"owner": "EvaluationRefSugar", "symbol": "python:pkg.core.frame.Frame.merge",
             "isDef": True, "file": "pkg/core/frame.py", "line": 2, "observed": long},
        ],
    }
    (state / "rows.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    trace = tmp_path / "kit-trace"
    trace.mkdir()
    records = [
        {"owner": "EvaluationRefSugar", "blame": "pkg/core/frame.py:7:15", "bindings": [{"key": "k"}],
         "trace": [{"qualname": "q"}]},
        {"owner": "Other", "blame": "pkg/core/frame.py:15:4", "bindings": [], "trace": []},
    ]
    (trace / "refusals-1.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8"
    )
    out = tmp_path / "out"
    assert bundle.main([
        "--corpus-root", str(root), "--path", "pkg/core/frame.py", "--function", "Frame.merge",
        "--state", str(state), "--kit-trace", str(trace), "--out", str(out),
    ]) == 0
    listing = json.loads((out / "refusals.json").read_text(encoding="utf-8"))
    (refusal,) = listing["refusals"]
    assert refusal["observed"] == long and refusal["inFunction"] is True
    kept = [json.loads(line) for line in (out / "kit-trace.jsonl").read_text().splitlines()]
    assert [r["owner"] for r in kept] == ["EvaluationRefSugar"]
    assert kept[0]["bindings"] == [{"key": "k"}] and kept[0]["blameLine"] == 7
    summary = json.loads((out / "kit-trace-summary.json").read_text(encoding="utf-8"))
    assert "bindings" not in summary[0] and "trace" not in summary[0]
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["functionLines"] == [[2, 7]]
    assert manifest["kitTraceRecords"] == 1
    assert manifest["proofDump"].startswith("no proof")


def test_the_cap_drops_whole_records_and_counts_them(tmp_path):
    root = corpus(tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    trace = tmp_path / "kit-trace"
    trace.mkdir()
    record = {"owner": "o", "blame": "pkg/core/frame.py:4:1", "bindings": [{"key": "k" * 5000}]}
    (trace / "refusals-1.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    out = tmp_path / "out"
    bundle.main([
        "--corpus-root", str(root), "--path", "core/frame.py",
        "--state", str(state), "--kit-trace", str(trace), "--out", str(out), "--cap-bytes", "3000",
    ])
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["kitTraceKept"] == 0
    assert manifest["droppedForCap"] == {"kit-trace record": 1}
    assert (out / "kit-trace.jsonl").read_text() == ""
