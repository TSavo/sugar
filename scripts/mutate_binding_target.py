"""Apply exactly ONE coherent mutation to the #7394 repair, and PRINT that it landed.

Same doctrine as ``scripts/mutate_one.py``, separate mutation set so the two
campaigns do not share anchors:

    * a helper whose ``assert anchor in source`` fails silently makes an
      unapplied mutation run as a clean green, so this prints the file, the
      anchor and the replacement, and exits non-zero with a named reason
      when it could not make one;
    * ``git checkout`` is NOT a revert when the thing being mutated is
      uncommitted work -- revert from ``--snapshot``, taken BEFORE the first
      mutation;
    * ONE at a time, never batched.

usage:
  python scripts/mutate_binding_target.py --snapshot
  python scripts/mutate_binding_target.py <name>
  python scripts/mutate_binding_target.py --revert
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NODES = ROOT / "implementations/python/sugar-source-tree/src/sugar_source_tree/nodes.py"
BINDING = (
    ROOT
    / "implementations/python/sugar-source-tree/src/sugar_source_tree/binding_state.py"
)
FILES = (NODES, BINDING)
SNAPSHOT = Path("/tmp/bindtarget_mutation_snapshot")

MUTATIONS = {
    # THE DEFECT ITSELF, restored: an attribute/subscript target binds its base
    # name again. This is the state of main.
    "attribute-target-binds-base": (
        NODES,
        "        if isinstance(target, (Attribute, Subscript)):\n"
        "            # Mutates an existing object; binds no module-scope name.\n"
        "            return set()\n",
        "        if isinstance(target, (Attribute, Subscript)):\n"
        "            return {\n"
        "                node.id for node in target.walk() if isinstance(node, Name)\n"
        "            }\n",
    ),
    # The closed set stops being closed: an unrecognised target quietly binds
    # nothing, which is indistinguishable from a legitimately non-binding one.
    "unassignable-target-silently-binds-nothing": (
        NODES,
        "        raise BackendDefect(\n"
        '            blame=getattr(target, "fragment", None) or statement.fragment,\n'
        '            owner="SourceUnit._assignment_target_bound_names",\n',
        "        return set()\n"
        "        raise BackendDefect(\n"
        '            blame=getattr(target, "fragment", None) or statement.fragment,\n'
        '            owner="SourceUnit._assignment_target_bound_names",\n',
    ),
    # The repair over-narrows: a starred target stops binding its name, so a
    # real destructuring binding is LOST. A filter that loses rows is the other
    # half of the same defect.
    "starred-target-binds-nothing": (
        NODES,
        "        if isinstance(target, Starred):\n"
        "            return SourceUnit._assignment_target_bound_names("
        "target.value, statement)\n",
        "        if isinstance(target, Starred):\n"
        "            return set()\n",
    ),
    # THE FORBIDDEN RELAXATION, made explicit so a tooth stands against it:
    # the by-name authority takes the first binding instead of refusing an
    # ambiguous name. With the table corrected this coincidentally gives the
    # right answer at the pandas seat -- which is exactly why it needs a twin.
    "take-the-first-binding": (
        BINDING,
        "    if len(bindings) != 1:\n        return None\n",
        "    if not bindings:\n        return None\n",
    ),
}


def main() -> int:
    if len(sys.argv) != 2:
        print("MUTATION REFUSED: exactly one argument required", flush=True)
        return 2
    name = sys.argv[1]
    if name == "--snapshot":
        SNAPSHOT.mkdir(parents=True, exist_ok=True)
        for path in FILES:
            (SNAPSHOT / path.name).write_text(path.read_text())
        print(f"SNAPSHOT TAKEN: {[p.name for p in FILES]}", flush=True)
        return 0
    if name == "--revert":
        missing = [p.name for p in FILES if not (SNAPSHOT / p.name).is_file()]
        if missing:
            print(
                f"REVERT REFUSED: no snapshot for {missing}. Take one with "
                "`--snapshot` BEFORE mutating. NOTHING WAS RESTORED.",
                flush=True,
            )
            return 4
        for path in FILES:
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
        f"  removed: {anchor.strip()[:160]!r}\n"
        f"  wrote:   {replacement.strip()[:160]!r}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
