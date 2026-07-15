"""Ratcheted census of stringly node-kind comparisons (the NodeKind campaign).

R = count of string-literal comparisons against ``.observed`` or
``operator_kind()`` in src/. The cure is `NodeKind` / `OperatorKind`
(factory/node_kind.py): StrEnum members whose values ARE the historical wire
strings, so each offender rewrites mechanically to ``== NodeKind.NAME`` /
``in {NodeKind.TUPLE, ...}`` with identical behavior.

AST-based, not grep: grep misses multiline comparisons and matches comments.
An offender is an `ast.Compare` whose one side is an attribute access
``<expr>.observed`` or a call ``<expr>.operator_kind()`` and whose other side
is a string literal or a set/tuple/list of string literals, under
Eq/NotEq/In/NotIn.

Ratchet convention (see tools/check-lift-refusal-vocabulary.py): the current
offender multiset is pinned in stringly_kind_census.json. NEW stringly
comparisons go red immediately; draining the declared debt requires
re-pinning (--write-current) with a shrinking count. The instrument is red
until R=0, at which point pyright-typed signatures (`observed -> NodeKind`,
`operator_kind() -> OperatorKind`) retire it into a regression tripwire.
"""

from __future__ import annotations

import argparse
import ast
import collections
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from sugar_lift_py_tests.factory.node_kind import NodeKind, OperatorKind

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_DISPLAY_ROOT = PACKAGE_ROOT.parents[1]
DEFAULT_CENSUS = Path(__file__).resolve().parent / "stringly_kind_census.json"

_COMPARE_OPS = (ast.Eq, ast.NotEq, ast.In, ast.NotIn)


@dataclass(frozen=True)
class Occurrence:
    key: str
    path: str
    line: int
    text: str
    subject: str  # "observed" | "operator_kind"
    literals: tuple[str, ...]
    replacement: str

    def to_json(self) -> dict[str, object]:
        return {
            "key": self.key,
            "path": self.path,
            "line": self.line,
            "text": self.text,
            "subject": self.subject,
            "literals": list(self.literals),
            "replacement": self.replacement,
        }


def _subject_of(node: ast.expr) -> Optional[str]:
    if isinstance(node, ast.Attribute) and node.attr == "observed":
        return "observed"
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "operator_kind"
    ):
        return "operator_kind"
    return None


def _string_literals(node: ast.expr) -> Optional[tuple[str, ...]]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return (node.value,)
    if isinstance(node, (ast.Set, ast.Tuple, ast.List)):
        values: list[str] = []
        for element in node.elts:
            if not (
                isinstance(element, ast.Constant) and isinstance(element.value, str)
            ):
                return None
            values.append(element.value)
        return tuple(values) if values else None
    return None


def _member_replacement(subject: str, literal: str) -> str:
    enum_cls = NodeKind if subject == "observed" else OperatorKind
    try:
        member = enum_cls(literal)
    except ValueError:
        return f"no {enum_cls.__name__} member for {literal!r} (investigate)"
    return f"{enum_cls.__name__}.{member.name}"


def _replacement_for(subject: str, literals: tuple[str, ...]) -> str:
    return ", ".join(_member_replacement(subject, literal) for literal in literals)


def _normalize(segment: str) -> str:
    return " ".join(segment.strip().split())


def _stable_digest(path: str, text: str) -> str:
    return hashlib.sha256(f"{path}\0{text}".encode("utf-8")).hexdigest()[:16]


def _offenders_in_tree(
    tree: ast.AST, source: str
) -> list[tuple[int, str, str, tuple[str, ...]]]:
    rows: list[tuple[int, str, str, tuple[str, ...]]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left, *node.comparators]
        for index, op in enumerate(node.ops):
            if not isinstance(op, _COMPARE_OPS):
                continue
            lhs, rhs = operands[index], operands[index + 1]
            for subject_side, literal_side in ((lhs, rhs), (rhs, lhs)):
                subject = _subject_of(subject_side)
                if subject is None:
                    continue
                literals = _string_literals(literal_side)
                if literals is None:
                    continue
                segment = ast.get_source_segment(source, node) or ast.dump(node)
                rows.append((node.lineno, _normalize(segment), subject, literals))
                break
    return rows


def source_files() -> list[Path]:
    return sorted(
        path
        for path in PACKAGE_ROOT.rglob("*.py")
        if path.resolve() != Path(__file__).resolve()
    )


def collect() -> list[Occurrence]:
    raw: list[tuple[str, int, str, str, tuple[str, ...]]] = []
    for file_path in source_files():
        source = file_path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        display = str(file_path.relative_to(REPO_DISPLAY_ROOT))
        for line, text, subject, literals in _offenders_in_tree(tree, source):
            raw.append((display, line, text, subject, literals))

    ordinals: collections.Counter[str] = collections.Counter()
    occurrences: list[Occurrence] = []
    for path, line, text, subject, literals in sorted(raw):
        base = f"{path}:{_stable_digest(path, text)}"
        ordinals[base] += 1
        occurrences.append(
            Occurrence(
                key=f"{base}:{ordinals[base]}",
                path=path,
                line=line,
                text=text,
                subject=subject,
                literals=literals,
                replacement=_replacement_for(subject, literals),
            )
        )
    return sorted(occurrences, key=lambda item: item.key)


def load_expected(path: Path) -> list[Occurrence]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        Occurrence(
            key=str(row["key"]),
            path=str(row["path"]),
            line=int(row["line"]),
            text=str(row["text"]),
            subject=str(row["subject"]),
            literals=tuple(str(value) for value in row["literals"]),
            replacement=str(row["replacement"]),
        )
        for row in payload["occurrences"]
    ]


def census_payload(occurrences: list[Occurrence]) -> dict[str, object]:
    subject_counts = collections.Counter(item.subject for item in occurrences)
    return {
        "schema": 1,
        "campaign": "NodeKind promotion",
        "law": (
            "node kinds are NodeKind/OperatorKind members, not string literals; "
            "R = stringly comparisons against .observed / operator_kind()"
        ),
        "identity": "path + normalized text digest + duplicate ordinal; line is display only",
        "R": len(occurrences),
        "subject_counts": dict(sorted(subject_counts.items())),
        "occurrences": [item.to_json() for item in occurrences],
    }


def print_summary(occurrences: Iterable[Occurrence]) -> None:
    items = list(occurrences)
    subject_counts = collections.Counter(item.subject for item in items)
    file_count = len({item.path for item in items})
    print(f"R(stringly-node-kind-comparisons)={len(items)} across {file_count} files")
    for subject, count in sorted(subject_counts.items()):
        print(f"  {subject}: {count}")


def write_current(path: Path) -> None:
    occurrences = collect()
    path.write_text(
        json.dumps(census_payload(occurrences), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print_summary(occurrences)
    print(f"WROTE: {path}")


def compare(expected: list[Occurrence], observed: list[Occurrence]) -> int:
    expected_keys = {item.key for item in expected}
    observed_by_key = {item.key: item for item in observed}
    stale = [item for item in expected if item.key not in observed_by_key]
    new = [item for item in observed if item.key not in expected_keys]

    print_summary(observed)

    if not stale and not new:
        print("PASS: stringly node-kind census matches the pinned multiset")
        return 0

    if new:
        print(
            "\nFAIL: NEW stringly node-kind comparisons (write the member):",
            file=sys.stderr,
        )
        for item in new[:50]:
            print(f"{item.path}:{item.line}: {item.text}", file=sys.stderr)
            print(f"  replacement: {item.replacement}", file=sys.stderr)
        if len(new) > 50:
            print(f"  ... {len(new) - 50} more new rows", file=sys.stderr)

    if stale:
        print(
            "\nFAIL: pinned stringly comparisons vanished; ratchet the census "
            "(rerun with --write-current so R shrinks on the record):",
            file=sys.stderr,
        )
        for item in stale[:50]:
            print(f"{item.path}: pinned-line={item.line}: {item.text}", file=sys.stderr)
        if len(stale) > 50:
            print(f"  ... {len(stale) - 50} more stale rows", file=sys.stderr)
    return 1


_SELF_TEST_SOURCE = """
def probe(site, other):
    if site.observed == "Name":
        pass
    if site.observed != "Call":
        pass
    if site.observed in {"Tuple", "List"}:
        pass
    if site.operator_kind() == "Add":
        pass
    if "Mod" == site.operator_kind():
        pass
    if other == "Name":  # not an offender: no .observed / operator_kind()
        pass
    if site.observed == other:  # not an offender: no string literal
        pass
"""


def self_test() -> int:
    tree = ast.parse(_SELF_TEST_SOURCE)
    rows = _offenders_in_tree(tree, _SELF_TEST_SOURCE)
    if len(rows) != 5:
        print(
            f"FAIL: self-test expected 5 planted offenders, found {len(rows)}",
            file=sys.stderr,
        )
        for row in rows:
            print(f"  {row}", file=sys.stderr)
        return 1
    subjects = collections.Counter(subject for _, _, subject, _ in rows)
    if subjects != collections.Counter({"observed": 3, "operator_kind": 2}):
        print(f"FAIL: self-test subject mix wrong: {subjects}", file=sys.stderr)
        return 1
    replacements = {
        _replacement_for(subject, literals) for _, _, subject, literals in rows
    }
    expected_replacements = {
        "NodeKind.NAME",
        "NodeKind.CALL",
        "NodeKind.TUPLE, NodeKind.LIST",
        "OperatorKind.ADD",
        "OperatorKind.MOD",
    }
    if replacements != expected_replacements:
        print(f"FAIL: self-test replacements wrong: {replacements}", file=sys.stderr)
        return 1
    print("PASS: planted stringly comparisons trip the census with the right members")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--census", type=Path, default=DEFAULT_CENSUS)
    parser.add_argument("--write-current", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()
    if args.write_current:
        write_current(args.census)
        return 0
    if not args.census.exists():
        print(f"FAIL: missing census file: {args.census}", file=sys.stderr)
        return 2
    return compare(load_expected(args.census), collect())


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
