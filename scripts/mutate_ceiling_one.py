"""Apply exactly ONE coherent mutation to the measurement-ceiling work, and
PRINT that it landed.

Same law as scripts/mutate_one.py, restated because it is the law that makes
any of this evidence:

  - ONE mutation at a time. A non-isolating mutation is NON-EVIDENCE even when
    it is red, because the red cannot be attributed to the tooth under test.
  - PRINT that it landed. A helper whose anchor silently fails to match makes
    an UNAPPLIED mutation run as a clean green.
  - GIT CHECKOUT IS NOT A REVERT WHEN THE WORK IS UNCOMMITTED. Revert from a
    snapshot taken before the first mutation, never from the index.

usage:
  python scripts/mutate_ceiling_one.py --snapshot     # BEFORE the first one
  python scripts/mutate_ceiling_one.py <name>
  python scripts/mutate_ceiling_one.py --revert
  python scripts/mutate_ceiling_one.py --list
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / "implementations/python/sugar-lift-py-tests"
CEILING = PY / "src/sugar_lift_py_tests/measurement_ceiling.py"
ENGINE = PY / "src/sugar_lift_py_tests/engine_log.py"
CONSUMER = PY / "scripts/recensus_enumerate_consumer.py"
COMPOSE = PY / "scripts/compose_control_effect_board.py"
SNAPSHOT = Path("/tmp/ceiling_mutation_snapshot")

FILES = {
    "ceiling": CEILING,
    "engine": ENGINE,
    "consumer": CONSUMER,
    "compose": COMPOSE,
}

MUTATIONS: dict[str, tuple[str, str, str]] = {
    # (file key, anchor, replacement)
    #
    # M1 -- the bound never actually arms. This is the decorative-ceiling
    # shape: everything still imports, every row still looks normal, and the
    # run is unbounded while claiming a bound.
    "never_arms": (
        "ceiling",
        "    previous_timer = signal.setitimer(signal.ITIMER_REAL, bound)",
        "    previous_timer = signal.setitimer(signal.ITIMER_REAL, 0)",
    ),
    # M2 -- exhaustion becomes an ordinary Exception, so any `except
    # Exception` on the construction path can catch it and report a
    # construction outcome caused by the clock.
    "catchable_as_exception": (
        "ceiling",
        "class MeasurementCeilingExceeded(BaseException):",
        "class MeasurementCeilingExceeded(Exception):",
    ),
    # M3 -- the stack is read after unwinding instead of at the alarm, so the
    # row carries no coordinate: a bare "it timed out".
    "no_coordinate_captured": (
        "engine",
        "        return [item.fingerprint for item in _ACTIVE.get(thread_id, [])]",
        "        return []",
    ),
    # M4 -- exhaustion folded into the panic arm: the board publishes a
    # refusal the product never made.
    "exhaustion_folded_into_panics": (
        "compose",
        '            elif row.get("terminalKind") == "measurement-exhausted":\n'
        "                exhausted.append(dict(key))",
        '            elif row.get("terminalKind") == "measurement-exhausted":\n'
        "                panicked.append(dict(key))",
    ),
    # M5 -- exhausted seats never reach the output side of the final union:
    # the denominator quietly shrinks by the files we could not measure.
    "exhausted_dropped_from_union": (
        "compose",
        "        output_keys=[*constructed, *panicked, *exhausted],",
        "        output_keys=[*constructed, *panicked],",
    ),
    # M6 -- the aggregate loses its third arm and falls back to "anything not
    # completed is a panic".
    "aggregate_loses_third_arm": (
        "compose",
        '        elif category == "measurement-exhausted":',
        '        elif category == "measurement-exhausted-DISABLED":',
    ),
    # M7 -- the timer is never disarmed, so it leaks into the next seat and
    # fires on an innocent file.
    "timer_leaks_to_next_seat": (
        "ceiling",
        "    finally:\n"
        "        signal.setitimer(signal.ITIMER_REAL, 0)\n"
        "        signal.signal(signal.SIGALRM, previous_handler)\n",
        "    finally:\n        pass\n",
    ),
    # M8 -- the exhausted row claims an EMPTY function manifest, i.e. states
    # that the file has no functions, rather than declining to testify.
    "claims_empty_attendance": (
        "consumer",
        '        input_key = {"sourceCid": source_cid, "file": file_rel}',
        '        input_key = {\n'
        '            "sourceCid": source_cid,\n'
        '            "file": file_rel,\n'
        '            "functionKeyManifest": [],\n'
        '        }',
    ),
    # M9 -- the driver stops counting exhaustion in its verdict, so a run with
    # an unmeasurable file reports green.
    # M10 -- a completed terminal is discarded when only the membership tail
    # exhausted the bound: mass-erase wearing the new timer as a costume.
    "banked_terminal_discarded": (
        "consumer",
        "        banked = progress.get(\"terminalRow\")",
        "        banked = None",
    ),
    "partition_sum_unchecked": (
        "compose",
        "    if accounted != files_terminal:",
        "    if accounted != files_terminal and False:",
    ),
}


def _snapshot() -> None:
    SNAPSHOT.mkdir(parents=True, exist_ok=True)
    for name, path in FILES.items():
        shutil.copy2(path, SNAPSHOT / f"{name}.py")
    print(f"SNAPSHOT taken -> {SNAPSHOT} ({', '.join(sorted(FILES))})")


def _revert() -> None:
    if not SNAPSHOT.is_dir():
        sys.exit("REFUSED: no snapshot; --revert would restore HEAD, not the work")
    for name, path in FILES.items():
        shutil.copy2(SNAPSHOT / f"{name}.py", path)
    print("REVERTED from snapshot (not from the index)")


def main(argv: list[str]) -> int:
    if not argv:
        sys.exit(__doc__)
    if argv[0] == "--snapshot":
        _snapshot()
        return 0
    if argv[0] == "--revert":
        _revert()
        return 0
    if argv[0] == "--list":
        for name in MUTATIONS:
            print(name)
        return 0
    name = argv[0]
    if name not in MUTATIONS:
        sys.exit(f"REFUSED: unknown mutation {name!r}; --list to see them")
    if not SNAPSHOT.is_dir():
        sys.exit("REFUSED: take --snapshot before the first mutation")
    file_key, anchor, replacement = MUTATIONS[name]
    path = FILES[file_key]
    source = path.read_text()
    occurrences = source.count(anchor)
    if occurrences != 1:
        sys.exit(
            f"REFUSED: anchor for {name!r} occurs {occurrences} times in "
            f"{path} (must be exactly 1). An unapplied mutation runs as a "
            "clean green -- this is the refusal that stops that."
        )
    path.write_text(source.replace(anchor, replacement, 1))
    print(f"MUTATION LANDED name={name} file={path}")
    print(f"  anchor:      {anchor!r}")
    print(f"  replacement: {replacement!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
