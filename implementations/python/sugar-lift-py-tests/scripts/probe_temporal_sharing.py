"""WHERE does the u^N go? A cProfile of one synthetic arm.

#7411 named the mechanism as "term duplication with no sharing" in
``Node._substitute_body_tracked``. Reading ``Name.substitute`` says something
narrower: it returns the BOUND NODE ITSELF (``return bound``), an existing
object. So the substituted term is already a DAG by object identity -- the
duplication, if any, is not in the term's storage but in some consumer that
walks that DAG as a TREE.

This probe does not assume either reading. It profiles the same synthetic the
#7411 curve was measured on, through the same census entrance, and prints the
cumulative-time leaders. Whatever is exponential shows up as a call count that
tracks u^N.
"""

from __future__ import annotations

import argparse
import cProfile
import io
import os
import pstats
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from probe_temporal_blowup_shape import (  # noqa: E402
    _chain_source,
    _distribution,
)

from sugar_lift_py_tests.measurement_ceiling import CEILING_ENV_VAR  # noqa: E402


def _construct(module_source: str, bound_s: float):
    import tempfile

    os.environ[CEILING_ENV_VAR] = str(bound_s)
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        _distribution(root, module_source)
        import recensus_enumerate_consumer as consumer

        started = time.monotonic()
        row = consumer.measure_file_via_enumerate(
            workspace_root=root,
            file_rel="synth/subject.py",
            contract_refs=None,
            distribution="synth-dist",
        )
        return row.get("terminalKind"), time.monotonic() - started


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uses", type=int, default=3)
    parser.add_argument("--length", type=int, default=10)
    parser.add_argument("--nested", action="store_true")
    parser.add_argument("--bound", type=float, default=300.0)
    parser.add_argument("--top", type=int, default=40)
    parser.add_argument("--counts-only", action="store_true")
    args = parser.parse_args(argv)

    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus

    handle = authenticated_pandas_corpus()
    print(f"ENV OK ({handle.distribution} {handle.version})", flush=True)

    source = _chain_source(length=args.length, uses=args.uses, nested=args.nested)
    print(f"PROFILE_ARM uses={args.uses} length={args.length} "
          f"nested={args.nested}", flush=True)

    profiler = cProfile.Profile()
    profiler.enable()
    try:
        kind, seconds = _construct(source, args.bound)
    finally:
        profiler.disable()
    print(f"PROFILE_RESULT outcome={kind} seconds={seconds:.3f}", flush=True)

    stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stream)
    stats.sort_stats("cumulative").print_stats(args.top)
    print(stream.getvalue(), flush=True)

    stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stream)
    stats.sort_stats("tottime").print_stats(args.top)
    print(stream.getvalue(), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
