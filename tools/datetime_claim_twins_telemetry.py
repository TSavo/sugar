from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path

AXES = (
    "truthful_pipeline_error",
    "truthful_not_sat",
    "lying_not_unsat",
    "missing_claim",
    "missing_citation",
    "silently_unaccounted",
    "unclassified_failure",
    "unevaluated_twins",
)
TWIN_TEST = "test_datetime_claim_twins_reach_real_sat_unsat_verdicts"


def summarize(junit: Path, *, pytest_exit: int, run_url: str) -> dict:
    root = ET.parse(junit).getroot()
    cases = [
        case for case in root.iter("testcase") if TWIN_TEST in case.get("name", "")
    ]
    axes = {axis: 0 for axis in AXES}
    offenders: list[dict[str, str]] = []
    truthful_failure_seen = False
    passed = 0

    for case in cases:
        outcome = case.find("failure")
        if outcome is None:
            outcome = case.find("error")
        if outcome is None:
            passed += 1
            continue
        text = " ".join((outcome.get("message", ""), outcome.text or ""))
        cid = _claim_cid(case.get("name", ""))
        axis = _axis_for(text)
        if axis.startswith("truthful_"):
            if not truthful_failure_seen:
                axes[axis] += 1
                offenders.append(
                    {
                        "axis": axis,
                        "claimCid": "truthful-corpus",
                        "detail": _one_line(text),
                    }
                )
                truthful_failure_seen = True
            continue
        axes[axis] += 1
        offenders.append({"axis": axis, "claimCid": cid, "detail": _one_line(text)})

    if truthful_failure_seen:
        axes["unevaluated_twins"] = len(cases)

    return {
        "kind": "datetime-claim-twins-vector",
        "pytestExit": pytest_exit,
        "runUrl": run_url,
        "totalTwins": len(cases),
        "passedTwins": passed,
        "R": axes,
        "offenders": offenders,
    }


def _axis_for(text: str) -> str:
    lowered = text.lower()
    if "datetime truthful twin" in lowered:
        return "truthful_not_sat"
    if "factorypanic" in lowered or "witnesspipelineerror" in lowered:
        return "truthful_pipeline_error"
    if "evaded the referee" in lowered:
        return "missing_claim"
    if "citation" in lowered:
        return "missing_citation"
    if "silently_unaccounted" in lowered:
        return "silently_unaccounted"
    if "datetime lying twin" in lowered or "verdict=" in lowered:
        return "lying_not_unsat"
    return "unclassified_failure"


def _claim_cid(name: str) -> str:
    if "[" not in name or not name.endswith("]"):
        return "unknown"
    return name.rsplit("[", 1)[1][:-1]


def _one_line(text: str) -> str:
    return " ".join(text.split())[:1000]


def render_markdown(vector: dict) -> str:
    rows = [
        "# Datetime claim twins",
        "",
        f"Run: {vector['runUrl']}",
        "",
        "| Axis | R |",
        "| --- | ---: |",
    ]
    rows.extend(f"| `{axis}` | {count} |" for axis, count in vector["R"].items())
    rows.extend(("", f"Passed twins: {vector['passedTwins']} / {vector['totalTwins']}"))
    if vector["offenders"]:
        rows.extend(("", "## Offenders", ""))
        rows.extend(
            f"- `{row['axis']}` `{row['claimCid']}` — {row['detail']}"
            for row in vector["offenders"]
        )
    return "\n".join(rows) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--pytest-exit", type=int, required=True)
    parser.add_argument("--run-url", default="local")
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    args = parser.parse_args()
    vector = summarize(args.junit, pytest_exit=args.pytest_exit, run_url=args.run_url)
    args.json_output.write_text(json.dumps(vector, indent=2) + "\n", encoding="utf-8")
    markdown = render_markdown(vector)
    args.markdown_output.write_text(markdown, encoding="utf-8")
    print(markdown, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
