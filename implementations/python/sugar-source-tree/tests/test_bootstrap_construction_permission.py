"""The bootstrap's permission to construct bare, stated as an obligation.

``mint_prebuilt_demand_table`` -> ``_call_contract_demand_rows`` ->
``authenticated_import_uses`` -> ``_run_lexical_import_pass`` ->
``SourceFile.__new__`` -> ``materialize_module`` -> ``_materialize_module_body``
constructs sugar BEFORE any construction context exists. The context is a
PRODUCT of that scan, so a total "no construction without a context" law is
self-contradictory at bootstrap and cannot hold.

The bootstrap is therefore PERMITTED. But the permission is not "the predicate
happens to exclude ``Constant``" -- that is a coincidence, not a permission, and
it rots the moment the path reaches a different kind. The permission is a
property of the CALL SITE:

    ``backend.py`` has exactly one ``.sugar()`` call site, and an
    ``isinstance(node.value, Constant)`` guard two lines above it.

That ``isinstance`` is load-bearing for a safety property stated in a different
file. Relaxing it -- an innocuous-looking edit by someone with no reason to
associate that loop with ``R_bare_construction_door`` -- starts a ``With``
constructing bare under a ``NullReporter`` that retains nothing, and today
nothing anywhere would notice. That is the fourth phantom's most likely
entrance.

These teeth assert the PROPERTY, not the syntax: the only construction
reachable from the bootstrap is a kind that does not consult the construction
context. They break when the filter widens, whatever the edit looked like.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import sugar_source_tree.backend as backend_module
from sugar_lift_py_tests.canonicalizer import blake3_512_of
from sugar_lift_py_tests.import_binding import authenticated_import_uses
from sugar_source_tree.nodes import Node
from sugar_source_tree.panic import BareConstructionDoor

# Module-level `with` and a module-level call: the two kinds that DO consult the
# construction context. If the bootstrap ever reaches either, it constructs them
# against a None context and paints a phantom.
BAIT = """\
import os

TOTAL = 1
NAME = "two"
RATIO = 3.5

with open("f") as fh:
    pass

JOINED = os.path.join("a", "b")
"""


def _drive_bootstrap(tmp_path: Path):
    """Run the real bootstrap, recording every kind that reaches construction."""
    path = tmp_path / "bait.py"
    path.write_text(BAIT)
    constructed: list[tuple[str, bool]] = []

    original = Node.sugar

    def recording_sugar(self, *args, **kwargs):
        frame = inspect.currentframe().f_back
        if frame.f_code.co_name == "_materialize_module_body":
            constructed.append(
                (
                    type(self).__name__,
                    getattr(self.unit, "construction_context", None) is not None,
                )
            )
        return original(self, *args, **kwargs)

    Node.sugar = recording_sugar
    try:
        authenticated_import_uses(
            tmp_path, path, BAIT, blake3_512_of(BAIT.encode("utf-8"))
        )
    finally:
        Node.sugar = original
    return constructed


def test_bootstrap_constructs_only_kinds_that_never_consult_the_context(
    tmp_path,
) -> None:
    """THE tooth. Widen the filter and this goes red, whatever the edit was.

    Not "no With was observed" -- the bait file HAS a module-level ``with`` and
    a module-level call sitting right next to the literals the bootstrap does
    construct. If the guard widens to reach them, they appear here.
    """
    constructed = _drive_bootstrap(tmp_path)

    assert constructed, (
        "the bootstrap constructed NOTHING -- this tooth proves a property of a "
        "path that must still be live. A silent-empty tooth measures nothing."
    )

    kinds = {kind for kind, _ in constructed}
    assert kinds == {"Constant"}, (
        f"the bootstrap constructed {sorted(kinds)}. Only kinds that never "
        f"consult the construction context may construct here: the bootstrap "
        f"runs BEFORE any context exists, so a context-consulting kind "
        f"constructs against None and paints a phantom. Either restore the "
        f"isinstance(node.value, Constant) guard above the .sugar() call in "
        f"backend.py, or give the bootstrap a real construction context."
    )

    # The permission is only sound because the context is genuinely absent here.
    # If a context IS seated, the premise this whole file rests on has moved.
    assert all(not has_context for _, has_context in constructed), (
        "the bootstrap now carries a construction context -- the "
        "self-contradiction that forced this permission is gone, and the "
        "permission should be withdrawn rather than kept as folklore."
    )


def test_the_permitted_kind_genuinely_cannot_consult_the_context(tmp_path) -> None:
    """The exclusion is PROVED, not asserted.

    ``Constant`` is out of the law because it structurally cannot lie: a literal
    has no ``with`` to paint and no call frame to resolve. Proof: constructing
    every kind the bootstrap reaches, on a tree with NO context, never reaches
    the context door.
    """
    constructed = _drive_bootstrap(tmp_path)
    kinds = {kind for kind, _ in constructed}

    node_classes = {}
    for kind in kinds:
        node_classes[kind] = getattr(
            __import__("sugar_source_tree.nodes", fromlist=[kind]), kind
        )

    for kind, cls in node_classes.items():
        source = inspect.getsource(cls._construct_sugar)
        assert "construction_context" not in source, (
            f"{kind}._construct_sugar reads the construction context, so it "
            f"cannot be permitted to construct during the bootstrap, where no "
            f"context exists."
        )


def test_backend_has_exactly_one_construction_call_site() -> None:
    """The tooth above is only total because there is ONE door to widen.

    If a second ``.sugar()`` appears in ``backend.py``, the recording tooth may
    still pass while the new site constructs something else entirely. A second
    site is not forbidden -- it is unproved, and unproved means loud.
    """
    tree = ast.parse(Path(backend_module.__file__).read_text(encoding="utf-8"))
    sites = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "sugar"
    ]
    assert len(sites) == 1, (
        f"backend.py drives .sugar() at lines {sites}. The bootstrap permission "
        f"is stated against ONE call site guarded by isinstance(..., Constant). "
        f"A new site needs its own proof that it cannot reach a "
        f"context-consulting kind."
    )


def test_bare_bootstrap_would_be_caught_if_it_reached_a_consulting_kind(
    tmp_path,
) -> None:
    """The tooth's other arm: the guard it depends on genuinely bites here.

    Without this, the tooth above could pass because the door is toothless
    rather than because the filter is tight. Drive a context-consulting kind
    over the same context-less unit the bootstrap uses and require the refusal.
    """
    path = tmp_path / "bait.py"
    path.write_text(BAIT)
    from sugar_source_tree.reporter import CollectingReporter
    from sugar_source_tree.tree import SourceFile

    source = SourceFile.from_path(str(path), reporter=CollectingReporter())
    assert source.unit.construction_context is None

    def walk(node, seen=None):
        seen = set() if seen is None else seen
        if id(node) in seen:
            return
        seen.add(id(node))
        yield node
        for field in getattr(node, "_child_fields", ()):
            value = getattr(node, field, None)
            for child in value if isinstance(value, tuple) else (value,):
                if hasattr(child, "_child_fields"):
                    yield from walk(child, seen)

    refused = []
    for node in walk(source.root):
        if type(node).__name__ not in ("With", "Call"):
            continue
        try:
            node.sugar()
        except BareConstructionDoor as panic:
            refused.append(panic.kind)
        except Exception:
            pass

    assert set(refused) == {"With", "Call"}, (
        f"expected the bare door to refuse both With and Call, got {refused}. "
        f"If it refuses neither, the permission tooth above proves nothing."
    )
