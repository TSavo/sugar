"""Apply exactly ONE coherent mutation, and PRINT that it landed.

A helper whose `assert anchor in source` fails silently makes an unapplied
mutation run as a clean green -- that is the ninth wrong figure retired from
this work. So this prints the file, the anchor, and the replacement it made,
and exits non-zero with a named reason if it could not make it. Check that
line before believing any red or green.

GIT CHECKOUT IS NOT A REVERT WHEN THE THING YOU ARE MUTATING IS UNCOMMITTED
WORK. This script's first version reverted with `git checkout -- <files>`,
which restored HEAD and so DELETED the working change the mutations existed
to test. Mutation 2 then ran against a tree without it and its red was
meaningless; mutations 3-5 REFUSED, because their anchors no longer existed.
Those refusals are the only reason it was caught, and the whole series was
discarded as non-evidence. Revert from a snapshot taken before the first
mutation -- `--snapshot` -- and never from the index.

usage:
  python scripts/mutate_one.py --snapshot     # BEFORE the first mutation
  python scripts/mutate_one.py <name>
  python scripts/mutate_one.py --revert
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BINDING = (
    ROOT
    / "implementations/python/sugar-source-tree/src/sugar_source_tree/binding_state.py"
)
NODES = ROOT / "implementations/python/sugar-source-tree/src/sugar_source_tree/nodes.py"
SNAPSHOT = Path("/tmp/citecls_mutation_snapshot")

MUTATIONS = {
    # The third authority re-derives from its own input: the check proves
    # nothing about an allocation callee. The lying twin is what distinguishes
    # a real re-derivation from this.
    "allocation-tautology": (
        BINDING,
        "    resolved = bindings[0]\n",
        "    if isinstance(definition, ClassDef):\n"
        "        return definition\n"
        "    resolved = bindings[0]\n",
    ),
    # The kind disagreement falls through to the seal term, which names the
    # wrong repair.
    "drop-kind-term": (
        BINDING,
        "        if isinstance(definition, ClassDef) is not isinstance(\n"
        "            resolved_definition, ClassDef\n"
        "        ):\n"
        '            return "resolved-definition-kind-mismatch"\n',
        "",
    ),
    # The admission is broadened past a readable definition: an unmaterialized
    # handle would stop being refused.
    "admit-any-object": (
        BINDING,
        "        if not isinstance(definition, (FunctionDef, AsyncFunctionDef, ClassDef)):\n"
        '            return "definition-not-a-functiondef"\n',
        "        if definition is None:\n"
        '            return "definition-not-a-functiondef"\n',
    ),
    # The allocation callee is not projected to its typed occurrence, so the
    # guard holds a raw handle again.
    "drop-classdef-projection": (
        NODES,
        "        if not isinstance(definition, (FunctionDef, AsyncFunctionDef, ClassDef)):\n"
        "            return value\n"
        "        source_call_frame = value.source_call_frame\n",
        "        if not isinstance(definition, (FunctionDef, AsyncFunctionDef)):\n"
        "            return value\n"
        "        source_call_frame = value.source_call_frame\n",
    ),
    # The class definition goes back off the roll.
    "classdef-off-the-roll": (
        NODES,
        "        super().__post_init__()\n"
        "        if (\n"
        "            not isinstance(self.binding_target, Name)\n",
        "        if (\n"
        "            not isinstance(self.binding_target, Name)\n",
    ),
}


def main() -> int:
    if len(sys.argv) != 2:
        print("MUTATION REFUSED: exactly one argument required", flush=True)
        return 2
    name = sys.argv[1]
    # A SNAPSHOT, never `git checkout`. Reverting to HEAD destroyed the very
    # working change the mutations were testing -- the second mutation then ran
    # against a tree without it, and the three after that refused because their
    # anchors no longer existed. The refusals were correct and are the only
    # reason this was caught; the revert was the defect.
    if name == "--snapshot":
        SNAPSHOT.mkdir(parents=True, exist_ok=True)
        for path in (BINDING, NODES):
            (SNAPSHOT / path.name).write_text(path.read_text())
        print(f"SNAPSHOT TAKEN: {[p.name for p in (BINDING, NODES)]}", flush=True)
        return 0
    if name == "--revert":
        missing = [p.name for p in (BINDING, NODES) if not (SNAPSHOT / p.name).is_file()]
        if missing:
            print(
                f"REVERT REFUSED: no snapshot for {missing}. Take one with "
                "`--snapshot` BEFORE mutating. NOTHING WAS RESTORED.",
                flush=True,
            )
            return 4
        for path in (BINDING, NODES):
            path.write_text((SNAPSHOT / path.name).read_text())
        print("MUTATION REVERTED: restored from snapshot", flush=True)
        return 0
    if name not in MUTATIONS:
        print(
            f"MUTATION REFUSED: unknown name {name!r}; known: {sorted(MUTATIONS)}",
            flush=True,
        )
        return 2
    path, anchor, replacement = MUTATIONS[name]
    source = path.read_text()
    occurrences = source.count(anchor)
    if occurrences != 1:
        print(
            f"MUTATION REFUSED: anchor for {name!r} occurs {occurrences} times in "
            f"{path.name}; expected exactly 1. NOTHING WAS APPLIED.",
            flush=True,
        )
        return 3
    path.write_text(source.replace(anchor, replacement))
    print(
        f"MUTATION LANDED: {name} in {path.name}\n"
        f"  removed: {anchor.strip()[:120]!r}\n"
        f"  wrote:   {replacement.strip()[:120]!r}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
