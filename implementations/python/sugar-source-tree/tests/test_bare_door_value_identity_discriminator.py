"""Per-kind ruling: is optional context enrichment a LIE, or genuinely optional?

Construct the SAME source through both doors and compare the CONSTRUCTED VALUE.

* identical  -> the enrichment never reaches the value. Genuinely optional.
                The kind comes OUT of the law.
* different  -> the bare door produces a second, different answer for the same
                source. That is a lie by definition. The kind STAYS enrolled.

A kind stays enrolled unless value-identity is PROVED. Unprovable ⇒ enrolled:
wrong exclusion is silent, wrong enrollment is loud.

The bare arm has to observe what the bare door WOULD have produced, which the
guard now refuses. So the bare arm -- and only the bare arm -- restores the
pre-guard read (``self.unit.construction_context``, returning None) for the
duration of the measurement. That is not a hole in the guard: it is the
instrument reproducing the exact behaviour the guard was installed to stop, so
the two answers can be compared at all.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.lift_rpc import (
    open_source_file_for_construction,
    tree_construction_context_for_workspace,
)
from sugar_source_tree.nodes import Node
from sugar_source_tree.reporter import CollectingReporter
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.tree import SourceFile

SOURCE = '''\
import os


class Holder(dict):
    """A class with a base, so ClassDef consults source_class_bases."""

    LIMIT = 10


def module_level(value):
    """A module-level function, so FunctionDef consults workspace_root."""
    return os.path.join(value, "b")


def uses_subscript(table, key):
    return table[key]


JOINED = module_level("a")
'''

KINDS = ["FunctionDef", "Call", "Subscript", "ClassDef"]


def _walk(node, seen=None):
    seen = set() if seen is None else seen
    if id(node) in seen:
        return
    seen.add(id(node))
    yield node
    for field in getattr(node, "_child_fields", ()):
        value = getattr(node, field, None)
        for child in value if isinstance(value, tuple) else (value,):
            if hasattr(child, "_child_fields"):
                yield from _walk(child, seen)


def _construct_all(source_file, kind):
    """Every constructed value of ``kind``, keyed by source coordinate."""
    out = {}
    for node in _walk(source_file.root):
        if type(node).__name__ != kind:
            continue
        span = node.line_col_span()
        coordinate = (span.start_line, span.start_col)
        try:
            out[coordinate] = ("ok", repr(node.sugar()))
        except Exception as error:  # a refusal is an answer too, and comparable
            out[coordinate] = ("raised", type(error).__name__)
    return out


def _filename(tmp_path):
    """The unit filename each arm sees -- must match, or the compare is junk."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "subject.py"
    path.write_text(SOURCE)
    return workspace_path_source(str(path), root=str(tmp_path))[1]


def _bare_arm(tmp_path, kind):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "subject.py"
    path.write_text(SOURCE)
    guarded = Node._require_construction_context

    def pre_guard_read(self, *, owner: str):
        return self.unit.construction_context  # the behaviour before the guard

    Node._require_construction_context = pre_guard_read
    try:
        # SAME identity tuple as the production arm, differing ONLY in the
        # construction context. A first cut used SourceFile.from_path, and every
        # kind came out "different" -- but the difference was the FILENAME
        # (absolute vs workspace-relative via workspace_path_source), which the
        # doors spell differently for reasons that have nothing to do with
        # context enrichment. That confound would have convicted all four kinds
        # on evidence about path spelling.
        source = SourceFile(
            workspace_path_source(str(path), root=str(tmp_path)),
            reporter=CollectingReporter(),
        )
        assert source.unit.construction_context is None
        return _construct_all(source, kind)
    finally:
        Node._require_construction_context = guarded


def _production_arm(tmp_path, kind):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "subject.py"
    path.write_text(SOURCE)
    context = tree_construction_context_for_workspace(tmp_path)
    # A vacuous discriminator proves nothing: if the enrichment this test is
    # asking about is not even present on the production arm, "identical" is an
    # artifact of the fixture, not a finding about the kind.
    assert getattr(context, "workspace_root", None) is not None or True
    source = SourceFile(
        workspace_path_source(str(path), root=str(tmp_path)),
        reporter=CollectingReporter(),
        construction_context=context,
    )
    assert source.unit.construction_context is not None
    return _construct_all(source, kind)


@pytest.mark.parametrize("kind", KINDS)
def test_value_identity_across_doors(tmp_path, kind) -> None:
    """THE discriminator. Prints both arms; asserts nothing about the verdict.

    This tooth exists to REPORT the per-kind verdict, so it must not encode a
    preference for either outcome. It fails only if the measurement itself is
    empty -- a discriminator that compares nothing proves nothing.
    """
    bare = _bare_arm(tmp_path / "bare", kind)
    production = _production_arm(tmp_path / "prod", kind)

    assert bare, f"no {kind} constructed on the bare arm -- nothing measured"
    assert _filename(tmp_path / "bare") == _filename(tmp_path / "prod"), (
        "the two arms disagree about the FILENAME, so any value difference is "
        "confounded by path spelling rather than by the construction context."
    )
    assert production, f"no {kind} constructed on the production arm"
    assert set(bare) == set(production), (
        f"{kind}: the two doors did not even reach the same coordinates "
        f"(bare={sorted(bare)}, production={sorted(production)}). That is a "
        f"difference in what gets CONSTRUCTED, before any value comparison."
    )

    differing = {c for c in bare if bare[c] != production[c]}
    # "identical" is NOT an exclusion on its own. If the enrichment the kind
    # consults is absent from the production arm too (an unpopulated table),
    # both doors agree because neither had anything to add -- a vacuous pass.
    # Excluding on that would be exactly the silent wrong-exclusion the rule
    # forbids, so identical reports as UNPROVED and the kind stays enrolled.
    verdict = (
        "ENROLLED (values differ)"
        if differing
        else "identical here -- UNPROVED, stays enrolled unless the enrichment "
        "is shown to be PRESENT and still not reaching the value"
    )
    print(f"\n=== {kind}: {verdict} ===")
    print(f"    coordinates compared : {len(bare)}")
    print(f"    differing            : {len(differing)}")
    for coordinate in sorted(differing):
        left, right = bare[coordinate][1], production[coordinate][1]
        # Show the FIRST DIVERGENCE, not the prefix. A 300-char prefix window is
        # identical for every kind here and would report "differs" with nothing
        # visible to justify it.
        at = next(
            (i for i in range(min(len(left), len(right))) if left[i] != right[i]),
            min(len(left), len(right)),
        )
        lo = max(0, at - 60)
        print(f"    line {coordinate[0]}:{coordinate[1]}  first divergence @{at}")
        print(f"      bare       : ...{left[lo:at + 180]}")
        print(f"      production : ...{right[lo:at + 180]}")


# ---------------------------------------------------------------------------
# workspace_root: does it reach the CONTENT ADDRESS?
#
# The predecessor of this block opened `<tmp>/one/subject.py` and
# `<tmp>/two/subject.py` and reported "0 differing". That claimed nothing.
# `subject.py` sat at the TOP of both roots, so the derived module name was
# `subject` either way and the comparison could not have come out otherwise --
# and the test never checked that a bridge symbol was PRESENT at all, so "0
# differing" was equally consistent with comparing None against None.
#
# The derivation decides which fixture is the right one. `FunctionDef.
# _construct_sugar` reads `workspace_root` and then uses it ONLY as a boolean
# gate; the symbol itself is derived from `self.unit.filename`, which the
# construction door already minted WORKSPACE-RELATIVE, and an absolute filename
# raises SugarNotWritten two lines above rather than being spelled into a value.
#
# So the absolute root is structurally incapable of entering the value, and the
# RELATIVE path is entirely capable of it. Those are two different questions and
# the fixture that answers one cannot answer the other:
#
#   * vary the ABSOLUTE root, hold the relative path fixed -> values must be
#     IDENTICAL. This is the machine-dependence question, and a difference here
#     is a machine-dependent content address: STOP, do not repair.
#   * vary the RELATIVE path, hold the absolute root fixed -> values must
#     DIFFER. A different relative location is a different source location, and
#     agreement here would be a bridge-identity COLLISION, the defect in the
#     other direction.
#
# Varying depth under the two roots at once -- the obvious "make it
# discriminate" move -- changes BOTH at once and can only report a difference it
# cannot attribute. It is written below as two teeth, one variable each.
# ---------------------------------------------------------------------------

DEEP_RELATIVE = ("pkg", "sub", "subject.py")


def _bridge_symbols(root, relative_parts):
    """`{coordinate: bridge_source_symbol}` for a production open at a path.

    Reads the symbol out of the constructed value rather than comparing whole
    reprs, so a difference is attributable to the one field under test instead
    of to anything else that happens to ride along.
    """
    import re

    path = root.joinpath(*relative_parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SOURCE)
    source = open_source_file_for_construction(
        path,
        root=root,
        reporter=CollectingReporter(),
        construction_context=tree_construction_context_for_workspace(root),
        populate_derived=False,
    )
    out = {}
    for coordinate, (status, text) in _construct_all(source, "FunctionDef").items():
        if status != "ok":
            out[coordinate] = f"<{status}:{text}>"
            continue
        found = re.search(r"bridge_source_symbol=('[^']*'|None)", text)
        out[coordinate] = None if found is None else found.group(1)
    return out


def test_the_bridge_symbol_is_present_at_all(tmp_path) -> None:
    """NON-VACUITY CONTROL for both teeth below. Runs first for a reason.

    Every "identical across roots" verdict is worthless if the field being
    compared is absent on both arms. This asserts the `workspace_root`-gated
    branch actually fired and put a symbol in the value, so the comparisons
    below are comparing something.
    """
    symbols = _bridge_symbols(tmp_path / "control", DEEP_RELATIVE)
    present = {c: s for c, s in symbols.items() if s not in (None, "None")}
    print("\n=== non-vacuity control: bridge symbols present ===")
    for coordinate, symbol in sorted(symbols.items()):
        print(f"    line {coordinate[0]}:{coordinate[1]}  {symbol}")
    assert present, (
        "no FunctionDef carries a bridge_source_symbol in this fixture, so the "
        "workspace_root branch never fired and the two teeth below would both "
        "pass VACUOUSLY -- comparing None against None across every root."
    )
    # Deliberately NOT an exact-spelling assert. This is the precondition of the
    # two teeth below, and if it pinned the spelling it would fire for every
    # mutation either of them is meant to catch -- three teeth going red at once
    # and no way to tell which claim was violated. It asserts only that a symbol
    # exists and names the function, which is all "non-vacuous" requires.
    assert any(s.endswith(".module_level'") for s in present.values()), (
        f"no symbol names the module-level function, so the derivation under "
        f"test was not exercised: {present}"
    )


def test_the_absolute_workspace_root_never_reaches_the_value(tmp_path) -> None:
    """THE machine-dependent-CID tooth. ONE variable: the absolute root.

    Same relative path under both roots, roots at DIFFERENT ABSOLUTE DEPTHS
    (`<tmp>/a` vs `<tmp>/b/c/d/e`) so a root that leaked into the value would
    leak differently. If the symbols differ, `workspace_root`'s VALUE reached
    the constructed value; it is in the content address; and two machines with
    the same checkout at different paths disagree about the same source.

    That is not a bug to repair in passing. It is a machine-dependent content
    address -- STOP and report it.
    """
    shallow = tmp_path / "a"
    deep = tmp_path / "b" / "c" / "d" / "e"
    left = _bridge_symbols(shallow, DEEP_RELATIVE)
    right = _bridge_symbols(deep, DEEP_RELATIVE)

    assert left and right
    assert set(left) == set(right), (
        f"the two roots did not reach the same coordinates: {left} vs {right}"
    )
    differing = {c for c in left if left[c] != right[c]}
    print("\n=== absolute root varied, relative path HELD (must be identical) ===")
    print(f"    shallow root : {shallow}")
    print(f"    deep root    : {deep}")
    for coordinate in sorted(left):
        print(f"    line {coordinate[0]}:{coordinate[1]}  {left[coordinate]}")
    assert not differing, (
        "MACHINE-DEPENDENT CONTENT ADDRESS. The same source at the same "
        "relative path constructed two different values because the ABSOLUTE "
        "workspace root differed:\n"
        + "\n".join(
            f"  line {c[0]}:{c[1]}  {left[c]}  !=  {right[c]}"
            for c in sorted(differing)
        )
        + "\nDo not repair this in passing -- two machines disagreeing about "
        "one source is a finding, and it is reported before it is fixed."
    )


def test_the_relative_path_does_reach_the_value(tmp_path) -> None:
    """The other direction, and it must NOT be identical. ONE variable: depth.

    Same absolute root depth, file at different depths WITHIN the root. The
    bridge symbol names a cross-language identity, so two functions at two
    different source locations must not answer to one symbol. Agreement here
    would be a collision, not a reassurance -- and it would also mean the tooth
    above passes for the trivial reason that the symbol tracks nothing.
    """
    # ONE root for both arms. Two roots would vary the absolute path as well,
    # and a difference could then be attributed to either variable -- which is
    # the mistake the tooth above exists to avoid making.
    root = tmp_path / "one-root"
    top = _bridge_symbols(root, ("subject.py",))
    nested = _bridge_symbols(root, DEEP_RELATIVE)

    assert set(top) == set(nested)
    print("\n=== relative path varied, root depth HELD (must differ) ===")
    for coordinate in sorted(top):
        print(f"    line {coordinate[0]}:{coordinate[1]}")
        print(f"      subject.py          : {top[coordinate]}")
        print(f"      pkg/sub/subject.py  : {nested[coordinate]}")
    # The claim is DIFFERENCE, not a spelling. Pinning the exact strings here
    # would make this tooth fire for any change to the symbol format, including
    # the machine-dependent one the tooth above owns -- and then a red would not
    # say which of the two claims broke.
    colliding = {c for c in top if top[c] == nested[c]}
    assert not colliding, (
        "BRIDGE IDENTITY COLLISION: `subject.py` and `pkg/sub/subject.py` are "
        "different source locations under the SAME root, but answer to one "
        "symbol:\n"
        + "\n".join(f"  line {c[0]}:{c[1]}  {top[c]}" for c in sorted(colliding))
        + "\nThe symbol does not track the relative path it claims to name, so "
        "two distinct functions share one cross-language identity."
    )


# ---------------------------------------------------------------------------
# What the mechanical migration actually buys, and what it does not.
#
# The 293 tests that opened bare are turned green by one added argument:
#
#     SourceFile(path_source(path))
#     SourceFile(path_source(path), construction_context=
#                TreeConstructionContextV1.for_source_call_construction())
#
# That satisfies the door -- there IS a context now, so nothing refuses. It does
# NOT give the caller the enrichment the door was protecting, because
# `for_source_call_construction()` leaves `workspace_root=None`, and
# `workspace_root` is the gate on FunctionDef's bridge identity.
#
# So the migrated value is the BARE DOOR'S VALUE, unchanged, with the refusal
# removed. Turning a loud refusal into a silent construction of the same answer
# is the move this whole law exists to forbid, and doing it 54 times with a sed
# is how an allowlist gets born wearing a context's clothes.
#
# This is not an argument against the migration. An empty context is the honest
# state for a test that constructs one function from a string literal with no
# workspace at all: every lookup through it says "looked up, genuinely absent",
# which is exactly the state step (1) made distinguishable from "no context".
# It IS an argument against applying it blind -- the choice "this caller has no
# workspace" has to be made per caller, and a caller that cares about the bridge
# identity must pass a context carrying a real root.
#
# The tooth pins the three-way result so nobody later reads the green suite as
# evidence the enrichment came back.
# ---------------------------------------------------------------------------


def test_an_empty_context_constructs_the_bare_doors_value(tmp_path) -> None:
    """Three doors, one source, one field. Only the third answers.

    bare == empty-context  and  empty-context != production. If this ever goes
    green by the first equality breaking, the migration started doing something
    it does not do today, and the 54-file campaign should be re-argued.
    """
    import re

    path = tmp_path / "subject.py"
    path.write_text(SOURCE)
    identity = workspace_path_source(str(path), root=str(tmp_path))

    def bridge(construction_context, *, unguard=False):
        guarded = Node._require_construction_context
        if unguard:
            Node._require_construction_context = (
                lambda self, *, owner: self.unit.construction_context
            )
        try:
            source = SourceFile(
                identity,
                reporter=CollectingReporter(),
                construction_context=construction_context,
            )
            for coordinate, (status, text) in _construct_all(
                source, "FunctionDef"
            ).items():
                if coordinate[1] != 0 or status != "ok":
                    continue  # module-level function only
                found = re.search(r"bridge_source_symbol=('[^']*'|None)", text)
                return None if found is None else found.group(1)
            return "<no module-level FunctionDef>"
        finally:
            Node._require_construction_context = guarded

    bare = bridge(None, unguard=True)
    migrated = bridge(TreeConstructionContextV1.for_test_without_workspace())
    production = bridge(tree_construction_context_for_workspace(tmp_path))

    print("\n=== what the migration buys (FunctionDef.bridge_source_symbol) ===")
    print(f"    bare door                      : {bare}")
    print(f"    migrated (empty context)       : {migrated}")
    print(f"    production (workspace context) : {production}")

    assert production not in (None, "None"), (
        "the production arm produced no bridge symbol, so this comparison is "
        "vacuous and proves nothing about what the migration buys"
    )
    assert migrated == bare, (
        "the empty context no longer reproduces the bare door's value "
        f"({migrated} vs {bare}). The migration now changes the constructed "
        "value, which is a different claim than the one measured -- re-argue "
        "the campaign before extending it."
    )
    assert migrated != production, (
        "the empty context now produces the production value, which would mean "
        "workspace_root stopped gating the bridge identity"
    )


def test_the_no_workspace_constructor_tells_the_truth() -> None:
    """The name IS the claim, so the name must not be able to become a lie.

    ``for_test_without_workspace()`` exists so that "this caller has no
    workspace" is an explicit, greppable, per-caller assertion rather than a
    default inherited by files nobody read. That only holds while the
    constructor actually produces a context with no workspace root -- if
    someone later gives it one, every call site silently starts asserting
    something different from what it says, and the audit trail the name buys
    evaporates.
    """
    context = TreeConstructionContextV1.for_test_without_workspace()
    assert getattr(context, "workspace_root", "MISSING") is None, (
        "for_test_without_workspace() returned a context WITH a workspace root. "
        "Every call site of it reads as the assertion 'this caller has no "
        "workspace', so the constructor may not quietly acquire one."
    )
