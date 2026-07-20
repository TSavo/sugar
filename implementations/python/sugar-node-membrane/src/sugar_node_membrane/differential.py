"""Provider differential: the instrument that admits or uninstalls a provider.

The governing invariant (#5940): **the memento CID is a function of SOURCE,
not of the parser.** Two providers parse the same text; every record is
addressed by ``(file, node_path)``; every CID must match. A divergence is
reported as ``file:node_path`` with BOTH spans and BOTH CIDs — the divergent
node path IS the finding. Nothing is normalized away to make the diff clean.

A divergence has exactly two causes, and they are distinguished by hand, not
by the tool:

1. **The span spec is under-specified** — it did not rule on some shape, so
   two providers legitimately differ. The SPEC is the defect.
2. **The adapter is wrong** — the provider can express our spec and the
   mapping is incorrect. The ADAPTER is the defect.

Three outcomes per record, never two-and-a-shrug:
``matched``, ``diverged`` (both sides present, CIDs differ), and
``missing_left`` / ``missing_right`` (a node path one provider materialized
and the other did not — an inventory divergence, which is a divergence, not
an absence to be ignored).

CLI::

    python -m sugar_node_membrane.differential PATH [PATH ...]
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .construct import Membrane
from .corpus import records_for_source
from .panic import MembranePanic

try:  # the refusal type the contract should have declared but does not
    from libcst import ParserSyntaxError as _LibCSTRefusal

    _PROVIDER_REFUSALS: tuple[type[BaseException], ...] = (_LibCSTRefusal,)
except ImportError:  # LibCST not installed: only the CPython provider exists
    _PROVIDER_REFUSALS = ()


@dataclass(frozen=True)
class Divergence:
    """One node path where two providers disagree. The finding itself."""

    file: str
    path: str
    left_kind: Optional[str]
    right_kind: Optional[str]
    left_span: Optional[tuple[int, int]]
    right_span: Optional[tuple[int, int]]
    left_cid: Optional[str]
    right_cid: Optional[str]

    @property
    def category(self) -> str:
        if self.left_cid is None:
            return "missing_left"
        if self.right_cid is None:
            return "missing_right"
        if self.left_kind != self.right_kind:
            return "kind"
        return "span"

    def render(self) -> str:
        return (
            f"{self.file}:{self.path}  [{self.category}]\n"
            f"    left : kind={self.left_kind} span={self.left_span} cid={self.left_cid}\n"
            f"    right: kind={self.right_kind} span={self.right_span} cid={self.right_cid}"
        )


@dataclass
class DiffResult:
    files_compared: int = 0
    records_left: int = 0
    records_right: int = 0
    matched: int = 0
    divergences: list[Divergence] = field(default_factory=list)
    # (file, side, failure_class, message) — a provider refusal or a MISSING.
    failures: list[tuple[str, str, str, str]] = field(default_factory=list)
    seconds_left: float = 0.0
    seconds_right: float = 0.0

    @property
    def R(self) -> int:
        """Remaining work: divergent node paths plus per-file failures.

        A failure counts. A MISSING never becomes success OR silence.
        """
        return len(self.divergences) + len(self.failures)


def _emit(
    membrane: Membrane, source: str, rel: str, side: str, result: DiffResult
) -> Optional[list[dict[str, object]]]:
    try:
        return records_for_source(membrane, source, rel)
    except MembranePanic as err:
        result.failures.append((rel, side, "membrane_panic", str(err)))
        return None
    except SyntaxError as err:
        result.failures.append((rel, side, "provider_syntax_error", str(err)))
        return None
    except _PROVIDER_REFUSALS as err:
        # CONTRACT GAP (#5940): backend.py never declares a refusal type, so
        # the membrane's failure vocabulary is written in CPython's
        # SyntaxError. LibCST's ParserSyntaxError does not subclass it, so
        # this differential has to name it explicitly. corpus.py, which only
        # catches SyntaxError, would let it escape and kill the run.
        result.failures.append((rel, side, "provider_syntax_error", str(err)))
        return None
    except RecursionError as err:
        result.failures.append((rel, side, "recursion_error", str(err)))
        return None
    except Exception as err:  # noqa: BLE001 - recorded, never swallowed
        # An adapter bug (not a MISSING and not a provider refusal). Recorded
        # with its type so a corpus sweep names every one of them, and
        # counted in R: a crash is never silence.
        result.failures.append(
            (rel, side, f"adapter_crash:{type(err).__name__}", str(err))
        )
        return None


def compare_source(
    left: Membrane, right: Membrane, source: str, rel: str, result: DiffResult
) -> None:
    t0 = time.perf_counter()
    left_records = _emit(left, source, rel, "left", result)
    t1 = time.perf_counter()
    right_records = _emit(right, source, rel, "right", result)
    t2 = time.perf_counter()
    result.seconds_left += t1 - t0
    result.seconds_right += t2 - t1

    if left_records is None or right_records is None:
        return

    result.files_compared += 1
    result.records_left += len(left_records)
    result.records_right += len(right_records)

    by_path_left = {r["path"]: r for r in left_records}
    by_path_right = {r["path"]: r for r in right_records}

    for path in sorted(set(by_path_left) | set(by_path_right)):
        a = by_path_left.get(path)
        b = by_path_right.get(path)
        if a is not None and b is not None and a["cid"] == b["cid"] and a["kind"] == b["kind"]:
            result.matched += 1
            continue
        result.divergences.append(
            Divergence(
                file=rel,
                path=str(path),
                left_kind=None if a is None else str(a["kind"]),
                right_kind=None if b is None else str(b["kind"]),
                left_span=None if a is None else (int(a["start"]), int(a["end"])),
                right_span=None if b is None else (int(b["start"]), int(b["end"])),
                left_cid=None if a is None else str(a["cid"]),
                right_cid=None if b is None else str(b["cid"]),
            )
        )


def compare(paths: list[Path], base: Optional[Path] = None, limit: int = 0) -> DiffResult:
    from .cpython_adapter import CPythonAstProvider
    from .libcst_adapter import LibCSTProvider

    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files.extend(sorted(p.rglob("*.py")))
        else:
            files.append(p)
    files.sort()
    if limit:
        files = files[:limit]

    result = DiffResult()
    for path in files:
        rel = str(path.relative_to(base)) if base is not None else str(path)
        try:
            source = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as err:
            result.failures.append((rel, "both", "unreadable", str(err)))
            continue
        # Fresh membranes per file: the pool caches by source CID, and a
        # shared pool across a large corpus would measure memory, not spans.
        compare_source(
            Membrane(CPythonAstProvider()),
            Membrane(LibCSTProvider()),
            source,
            rel,
            result,
        )
    return result


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="CPython vs LibCST memento CID differential")
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--base", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--show", type=int, default=40, help="divergences to print")
    args = parser.parse_args(argv)

    result = compare(args.paths, args.base, args.limit)

    print(f"files compared : {result.files_compared}")
    print(f"records (cpython/libcst): {result.records_left}/{result.records_right}")
    print(f"matched        : {result.matched}")
    print(f"divergences    : {len(result.divergences)}")
    print(f"failures       : {len(result.failures)}")
    print(f"R              : {result.R}")
    print(f"parse+build s  : cpython={result.seconds_left:.2f} libcst={result.seconds_right:.2f}")

    by_category: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    for d in result.divergences:
        by_category[d.category] = by_category.get(d.category, 0) + 1
        key = f"{d.category}:{d.left_kind}->{d.right_kind}"
        by_kind[key] = by_kind.get(key, 0) + 1
    if by_category:
        print("\nby category:")
        for k, v in sorted(by_category.items(), key=lambda kv: -kv[1]):
            print(f"  {k:16} {v}")
        print("\nby shape:")
        for k, v in sorted(by_kind.items(), key=lambda kv: -kv[1])[:30]:
            print(f"  {k:44} {v}")

    for rel, side, cls, msg in result.failures[:40]:
        print(f"FAIL[{side}/{cls}] {rel}: {msg.splitlines()[0]}")

    if result.divergences:
        print(f"\nfirst {args.show} divergent node paths:")
        for d in result.divergences[: args.show]:
            print(d.render())

    return 1 if result.R else 0


if __name__ == "__main__":
    sys.exit(main())
