"""Bound lexical-call stranding on a path-selected pandas 3.0.3 slice.

Selection is independent of rewrite outcome: order the authenticated corpus
manifest by SHA-256 of the repo-relative path, exclude Hockney's original five
files, and take the first ten files with a static nested-function call site.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call
from sugar_source_tree.tree import SourceFile


PIN_PATH = Path("docs/ledgers/pins/pandas-3.0.3.pin.json")
ORIGINAL_FILES = frozenset(
    {
        "core/array_algos/replace.py",
        "core/window/common.py",
        "tests/arithmetic/test_array_ops.py",
        "tests/io/formats/test_printing.py",
        "tests/tseries/offsets/test_custom_business_day.py",
    }
)
SAMPLE_SIZE = 10


def _has_static_nested_call(source: str, filename: str) -> bool:
    tree = ast.parse(source, filename=filename)
    function_kinds = (ast.FunctionDef, ast.AsyncFunctionDef)
    for owner in ast.walk(tree):
        if not isinstance(owner, function_kinds):
            continue
        nested_names = {
            node.name
            for node in ast.walk(owner)
            if isinstance(node, function_kinds) and node is not owner
        }
        if any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in nested_names
            for node in ast.walk(owner)
        ):
            return True
    return False


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True), flush=True)


def main() -> None:
    pin = json.loads(PIN_PATH.read_text(encoding="utf-8"))
    assert pin["kind"] == "sugar-corpus-pin/v1"
    assert pin["distribution"] == "pandas"
    assert pin["version"] == "3.0.3"
    assert pin["fileCount"] == 1421

    root = Path(os.environ.get("PANDAS_CORPUS_ROOT", pin["root"]))
    entries = {
        entry["path"]: entry
        for entry in pin["files"]
        if entry["path"].endswith(".py")
        and entry["path"] not in ORIGINAL_FILES
    }
    ordered_paths = sorted(
        entries,
        key=lambda path: (hashlib.sha256(path.encode("utf-8")).hexdigest(), path),
    )

    selected: list[tuple[str, str]] = []
    inspected = 0
    for relative in ordered_paths:
        path = root / relative
        source_bytes = path.read_bytes()
        observed_sha256 = hashlib.sha256(source_bytes).hexdigest()
        expected_sha256 = entries[relative]["sha256"]
        if observed_sha256 != expected_sha256:
            raise RuntimeError(
                f"corpus content mismatch path={relative} "
                f"expected={expected_sha256} observed={observed_sha256}"
            )
        inspected += 1
        source = source_bytes.decode("utf-8")
        if _has_static_nested_call(source, relative):
            selected.append((relative, source))
            if len(selected) == SAMPLE_SIZE:
                break

    if len(selected) != SAMPLE_SIZE:
        raise RuntimeError(
            f"selection exhausted: selected={len(selected)} requested={SAMPLE_SIZE}"
        )

    _emit(
        {
            "kind": "selection",
            "rule": "sha256(path)-ascending; exclude original five; first ten static nested-function-call files",
            "corpus": "pandas==3.0.3",
            "corpusAggregateHash": pin["aggregateHash"],
            "pathsInspected": inspected,
            "selectedFiles": [relative for relative, _ in selected],
        }
    )

    original = Call.substitute
    results: list[dict[str, object]] = []
    for relative, source in selected:
        path = root / relative
        source_file = SourceFile(
            (
                source,
                str(path),
                blake3_512_of(source.encode("utf-8")),
            )
        )
        parsed_calls = sum(
            1 for node in source_file.nodes() if isinstance(node, Call)
        )
        lexical_rows = len(source_file.constructed_module.lexical_call_rows)
        invoked: set[int] = set()
        rewritten: set[int] = set()
        row_invoked: set[int] = set()
        row_rewritten: set[int] = set()
        stranded_row_ids: set[int] = set()

        def active(self: Call, scope: dict[str, object]) -> object:
            before = tuple(self.unit.lexical_call_rows_for(self))
            result = original(self, scope)
            occurrence = id(self)
            invoked.add(occurrence)
            if before:
                row_invoked.add(occurrence)
            if result is not self and isinstance(result, Call):
                rewritten.add(occurrence)
                if before:
                    row_rewritten.add(occurrence)
                    if not tuple(self.unit.lexical_call_rows_for(result)):
                        stranded_row_ids.update(id(row) for row in before)
            return result

        Call.substitute = active
        try:
            source_file.root.substitute({})
        finally:
            Call.substitute = original

        row: dict[str, object] = {
            "kind": "file",
            "path": relative,
            "parsedCalls": parsed_calls,
            "lexicalRows": lexical_rows,
            "substituteReached": len(invoked),
            "rewrote": len(rewritten),
            "rowBearingReached": len(row_invoked),
            "rowBearingRewrote": len(row_rewritten),
            "strandedRows": len(stranded_row_ids),
        }
        results.append(row)
        _emit(row)

    numeric_fields = (
        "parsedCalls",
        "lexicalRows",
        "substituteReached",
        "rewrote",
        "rowBearingReached",
        "rowBearingRewrote",
        "strandedRows",
    )
    summary: dict[str, object] = {
        "kind": "summary",
        "files": len(results),
        "filesWithEnrolledLexicalCalls": sum(
            int(row["rowBearingReached"] > 0) for row in results
        ),
        "filesWithNonrewrittenEnrolledCalls": sum(
            int(row["rowBearingReached"] > row["rowBearingRewrote"])
            for row in results
        ),
    }
    summary.update(
        {
            field: sum(int(row[field]) for row in results)
            for field in numeric_fields
        }
    )
    _emit(summary)


if __name__ == "__main__":
    main()
