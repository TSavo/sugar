"""What is not terminating in temporal substitution at generic.py:1323?

DIAGNOSIS ONLY. No repair, no ruling. This probe exists to turn a corpus
anecdote into a measured shape, and if possible into a SYNTHETIC reproduction
that can be mutated.

The captured stack (from the measurement ceiling, taken in the signal handler
before unwinding, so the construct was still live):

    FunctionDef.sugar    generic.py:1323:12
    FunctionUniverse     generic.py:1323 build_codes
    Substitute           generic.py:1323 build_codes   role=temporal
    SubstituteStatement  generic.py:1324 Return        role=temporal

A nested ``FunctionDef`` defined inside an ``If`` branch inside
``value_counts``, entering temporal substitution. depth 15, oscillating 7-10,
peaking at 40, 3014 heartbeats during the CI stall -- the engine is WORKING,
not deadlocked, so the signature is combinatorial, not an infinite loop.

``ExitSet.sequence`` Cartesian growth (m^k) is a CANDIDATE mechanism, not an
established one. This probe measures whether it is this one rather than
assuming it because it fits.

Modes:
  --dump            print the corpus source around the coordinate
  --synthetic       measure a family of synthetic files, one axis at a time
"""

from __future__ import annotations

import argparse
import csv
import importlib.metadata
import os
import sys
import time
from pathlib import Path

from sugar_lift_py_tests.measurement_ceiling import CEILING_ENV_VAR

_CORPUS_FILE = "core/groupby/generic.py"


def _dump(corpus: Path, start: int, end: int) -> None:
    text = (corpus / _CORPUS_FILE).read_text(encoding="utf-8").splitlines()
    for number in range(start, min(end, len(text)) + 1):
        print(f"{number:5d}  {text[number - 1]}")


def _distribution(root: Path, module_source: str) -> None:
    """A minimal authenticated distribution holding one synthetic module."""
    package = root / "synth"
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "subject.py").write_text(module_source, encoding="utf-8")
    metadata = root / "synth_dist-1.0.dist-info"
    metadata.mkdir(exist_ok=True)
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: synth-dist\nVersion: 1.0\n", encoding="utf-8"
    )
    files = (
        "synth/__init__.py",
        "synth/subject.py",
        "synth_dist-1.0.dist-info/METADATA",
        "synth_dist-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for file in files:
            writer.writerow((file, "", ""))
    importlib.metadata.Distribution.at(metadata)


_CHAIN_TEMPLATE = """\
import numpy as np


def subject(seed, flag):
    base = np.zeros(seed)
{chain}
    if flag:
{nest}
    return {tail}
"""


def _chain_source(*, length: int, uses: int, nested: bool) -> str:
    """A synthetic prefix: `length` dependent assignments, each USED `uses` times.

    `uses` is the axis under test. Substitution threads each binding by
    inlining its substituted TERM at every use site. With uses=1 a chain of
    length N produces a term of size O(N). With uses=2, if there is no sharing,
    each link duplicates the whole term beneath it -- O(2^N). Same statement
    count, same nesting, same names: ONLY the number of use sites differs, so a
    difference between the two arms cannot be anything else.
    """
    lines = []
    for index in range(length):
        source = "base" if index == 0 else f"v{index - 1}"
        operands = ", ".join([source] * uses)
        lines.append(f"    v{index} = np.add({operands})")
    last = f"v{length - 1}" if length else "base"
    if nested:
        # The corpus shape: a nested FunctionDef inside an If branch whose body
        # references a name bound by the chain.
        nest = (
            "        def build_codes(lev):\n"
            f"            return np.repeat(lev, {last})\n"
            "        out = [build_codes(c) for c in base]\n"
        )
        tail = "out"
    else:
        nest = f"        out = np.repeat(base, {last})\n"
        tail = "out"
    return _CHAIN_TEMPLATE.format(chain="\n".join(lines), nest=nest, tail=tail)


_VALUE_COUNTS_START = 1090          # `def value_counts(` in the pinned 3.0.3 file
_BINS_BLOCK_STMT_INDEX = 30         # the `if bins is not None:` at 1293
_SUBJECT_HEAD = "import numpy as np\n\n\nclass G:\n"


def _bins_block(corpus: Path):
    """Locate value_counts and its `if bins is not None:` block in REAL source.

    Returns (lines, method_lineno, block, inner_statements). Everything the
    bisect emits is a verbatim LINE SLICE of the corpus file -- not
    ``ast.unparse`` -- so each arm is the real source, not a re-rendering of it.
    """
    import ast

    text = (corpus / _CORPUS_FILE).read_text(encoding="utf-8")
    lines = text.splitlines()
    tree = ast.parse(text)
    method = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "SeriesGroupBy":
            for child in node.body:
                if (
                    isinstance(child, ast.FunctionDef)
                    and child.name == "value_counts"
                    and child.lineno == _VALUE_COUNTS_START
                ):
                    method = child
    if method is None:
        raise SystemExit("value_counts not found at the pinned coordinate")
    block = method.body[_BINS_BLOCK_STMT_INDEX]
    if not isinstance(block, ast.If) or block.lineno != 1293:
        raise SystemExit(f"block moved: {type(block).__name__} at {block.lineno}")
    return lines, method, block


def _bisect_source(lines, method, block, keep: int) -> str:
    """value_counts with the `bins` block truncated after `keep` statements.

    ONE AXIS: `keep`. Everything before the block -- the ~200 preceding lines of
    value_counts, every name, the class nesting -- is byte-identical across all
    arms. `keep=0` drops the block entirely.
    """
    prefix_end = method.body[_BINS_BLOCK_STMT_INDEX - 1].end_lineno
    body = lines[_VALUE_COUNTS_START - 1 : prefix_end]
    if keep > 0:
        last = block.body[keep - 1].end_lineno
        body += lines[block.lineno - 1 : last]
    body.append("        return out")
    return _SUBJECT_HEAD + "\n".join(body) + "\n"


_SPLICE_TEMPLATE = """\
import numpy as np


def subject(seed, flag):
    diff = np.zeros(seed)
    for level in {iterable}:
        diff = np.add({operands})
{chain}
    if flag:
        out = np.repeat(seed, {last})
    return out
"""


def _splice_source(*, iterations: int, uses: int, tail: int) -> str:
    """A name MUTATED inside a CONCRETE `for`, which dissolves and SPLICES.

    This is the axis #7411 left inferred. ``For.substitute`` unrolls only a
    concrete iterable (``List``/``Tuple`` literal or ``range`` of int literals,
    capped at ``_UNROLL_FUEL``); the unrolled statements are spliced into the
    block and threaded there. So the question is whether threading a name that
    reads its own previous term, once per spliced iteration, can make that term
    re-enter itself. ONE AXIS: ``iterations``.
    """
    operands = ", ".join(["diff"] * (uses - 1) + ["level"])
    lines = []
    for index in range(tail):
        source = "diff" if index == 0 else f"v{index - 1}"
        lines.append(f"    v{index} = np.add({source}, {source})")
    last = f"v{tail - 1}" if tail else "diff"
    return _SPLICE_TEMPLATE.format(
        iterable=repr(list(range(iterations))),
        operands=operands,
        chain="\n".join(lines),
        last=last,
    )


def _timed_construct(module_source: str, bound_s: float) -> tuple[str, float]:
    """Construct one synthetic module under a wall-clock bound.

    Returns (outcome, seconds). ``outcome`` is one of ``constructed``,
    ``panicked:<type>`` or ``bound-exceeded`` -- three different facts, never
    collapsed into a single number.
    """
    import tempfile

    # The census entrance arms its OWN ceiling, and arming a second interval
    # timer around it is refused by design (it would disarm one of the two
    # bounds silently). So the bound here IS the census ceiling: set it, and
    # `terminalKind == measurement-exhausted` is the bound-exceeded signal --
    # the same instrument the corpus run used, not a second one.
    os.environ[CEILING_ENV_VAR] = str(bound_s)

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        _distribution(root, module_source)
        started = time.monotonic()
        try:
            # THE CENSUS ENTRANCE, not a cheaper neighbour. Measuring through a
            # private walk would measure a different thing than the run that
            # exhausted the bound.
            import recensus_enumerate_consumer as consumer

            row = consumer.measure_file_via_enumerate(
                workspace_root=root,
                file_rel="synth/subject.py",
                contract_refs=None,
                distribution="synth-dist",
            )
            kind = row.get("terminalKind")
            if kind is None:
                # An instrument-failure row has NO terminalKind. Reporting
                # that as "no-terminal-kind" and moving on is how a probe
                # measures nothing and reports a tidy number.
                failure = row.get("instrumentFailure") or {}
                outcome = (
                    "instrument-failure:"
                    f"{failure.get('phase')}:{str(failure.get('message'))[:200]}"
                )
            else:
                outcome = str(kind)
        except BaseException as error:  # noqa: BLE001 -- diagnosis, named
            # The MESSAGE, not just the type. A probe whose every arm returns
            # the same type name in 0.000s is a non-measurement that reads
            # exactly like a clean measurement.
            outcome = f"panicked:{type(error).__name__}:{str(error)[:300]}"
        return outcome, time.monotonic() - started


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dump", action="store_true")
    parser.add_argument("--start", type=int, default=1080)
    parser.add_argument("--end", type=int, default=1340)
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--bisect", action="store_true")
    parser.add_argument("--splice", action="store_true")
    parser.add_argument("--iterations", type=int, nargs="+", default=[1,2,3,4,6,8,12,16])
    parser.add_argument("--tail", type=int, default=0)
    parser.add_argument("--keep", type=int, nargs="+", default=None)
    parser.add_argument("--emit", type=int, default=None)
    parser.add_argument("--max-length", type=int, default=12)
    parser.add_argument("--bound", type=float, default=60.0)
    # The DISCRIMINATING axis. If the mechanism is term duplication at each
    # use site, the growth base must track this number -- base ~= uses. A
    # curve that grows the same for 2 and 3 is a different mechanism.
    parser.add_argument(
        "--uses", type=int, nargs="+", default=[1, 2]
    )
    parser.add_argument(
        "--nested", type=lambda v: v == "true", nargs="+", default=[False, True]
    )
    args = parser.parse_args(argv)

    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus

    handle = authenticated_pandas_corpus()
    print(f"ENV OK ({handle.distribution} {handle.version}) root={handle.root}")

    if args.dump:
        _dump(handle.root, args.start, args.end)

    if args.emit is not None:
        lines, method, block = _bins_block(handle.root)
        print(_bisect_source(lines, method, block, args.emit))

    if args.splice:
        # A cycle would show as non-termination at a size the finite reading
        # says is trivial. A clean curve across `iterations` shows the spliced
        # mutation threads FORWARD only.
        print("SPLICE_HEADER iterations uses tail outcome seconds", flush=True)
        for uses in args.uses:
            for iterations in args.iterations:
                source = _splice_source(
                    iterations=iterations, uses=uses, tail=args.tail
                )
                outcome, seconds = _timed_construct(source, args.bound)
                print(
                    f"SPLICE_ROW iterations={iterations} uses={uses} "
                    f"tail={args.tail} outcome={outcome} seconds={seconds:.3f}",
                    flush=True,
                )
                if outcome == "measurement-exhausted":
                    print(f"SPLICE_WALL iterations={iterations} uses={uses}",
                          flush=True)
                    break

    if args.bisect:
        # The bisection: REAL source, one axis (how many statements of the
        # `bins` block survive). A prefix that completes gives a point on the
        # curve; a prefix that exhausts the bound gives the wall's location.
        # `measurement-exhausted` is NOT `non-terminating` -- it is the bound.
        lines, method, block = _bins_block(handle.root)
        total = len(block.body)
        keeps = args.keep if args.keep else list(range(0, total + 1))
        print(f"BISECT_PLAN block_statements={total} keeps={keeps}", flush=True)
        for keep in keeps:
            source = _bisect_source(lines, method, block, keep)
            outcome, seconds = _timed_construct(source, args.bound)
            print(
                f"BISECT_ROW keep={keep} lines={source.count(chr(10))} "
                f"outcome={outcome} seconds={seconds:.3f}",
                flush=True,
            )
            if outcome == "measurement-exhausted":
                print(f"BISECT_WALL keep={keep} -- bound {args.bound}s exceeded",
                      flush=True)
                break

    if args.synthetic:
        # ONE AXIS AT A TIME. uses=1 and uses=2 differ in nothing but the
        # number of use sites per binding; nested/flat differ in nothing but
        # the nested FunctionDef. A curve that bends on one axis and not the
        # others names the mechanism.
        print(
            "SYNTH_HEADER uses nested length outcome seconds",
            flush=True,
        )
        for nested in args.nested:
            for uses in args.uses:
                for length in range(1, args.max_length + 1):
                    source = _chain_source(
                        length=length, uses=uses, nested=nested
                    )
                    outcome, seconds = _timed_construct(source, args.bound)
                    print(
                        f"SYNTH_ROW uses={uses} nested={nested} "
                        f"length={length} outcome={outcome} "
                        f"seconds={seconds:.3f}",
                        flush=True,
                    )
                    if outcome == "measurement-exhausted":
                        print(
                            f"SYNTH_WALL uses={uses} nested={nested} "
                            f"length={length} -- stopping this arm",
                            flush=True,
                        )
                        break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
