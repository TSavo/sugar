"""#7838, inventory item 44: no CID depends on what the process lifted before.

Two process-wide counters used to stand for "one evaluation":
``container_mutation._TOKENS`` (the ``token`` leaf of every mutation shadow
node) and ``language_owned_contextvar._TOKEN_IDS`` (a ``ContextVar.set``
token). Both were draws, so the same source got different content in a process
that had drawn more before. Both are now coordinates: the site's source extent
plus the occurrence tags of the copy, and the ``set`` call's occurrence key.
"""

from __future__ import annotations

from types import SimpleNamespace

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor.language_owned_contextvar import (
    LanguageOwnedContextVarToken,
    LanguageOwnedContextVarValue,
)
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_source_tree import nodes
from sugar_source_tree.binding_state import backend_node_shape_cid_v2
from sugar_source_tree.tree import SourceFile

_MUTATION_KINDS = {
    "BuiltinContainerCall",
    "PathContainerCall",
    "PathAfterCall",
    "ReceiverAfterCall",
    "SourceCallActualAfter",
}

_SHARED = (
    "def build(xs, box):\n"
    "    out = []\n"
    "    for x in [1, 2]:\n"
    "        out.append(x)\n"
    "    box.items.append(0)\n"
    "    opaque(out)\n"
    "    return out\n"
)

_PREDECESSOR = (
    "def churn(n, box):\n"
    "    acc = []\n"
    "    acc.append(n)\n"
    "    acc.append(n + 1)\n"
    "    box.items.append(acc)\n"
    "    opaque(acc)\n"
    "    return acc\n"
)


def _mutation_shape_cids(source: str, rel: str) -> list[tuple[str, str]]:
    tree = SourceFile(
        (source, rel, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    (fn,) = [node for node in tree.nodes() if isinstance(node, nodes.FunctionDef)]
    body = fn.substitute({})
    found = {}
    for node in body.walk():
        # One entry per shadow node: a node reached along two paths is one node.
        if node.kind in _MUTATION_KINDS:
            found[id(node.ref)] = (node.kind, backend_node_shape_cid_v2(node.ref))
    return sorted(found.values())


def test_a_mutation_node_has_one_content_whatever_was_lifted_before() -> None:
    first = _mutation_shape_cids(_SHARED, "shared.py")
    assert first, "the program must build mutation shadow nodes"
    assert {kind for kind, _ in first} >= {"BuiltinContainerCall", "ReceiverAfterCall"}
    _mutation_shape_cids(_PREDECESSOR, "predecessor.py")
    _mutation_shape_cids(_PREDECESSOR, "predecessor.py")
    again = _mutation_shape_cids(_SHARED, "shared.py")
    assert again == first


def test_two_iterations_stay_two_evaluations() -> None:
    """Discriminating: the coordinate still tells an unrolled loop's
    evaluations apart (the job the counter did)."""
    cids = [
        cid
        for kind, cid in _mutation_shape_cids(_SHARED, "shared.py")
        if kind == "BuiltinContainerCall"
    ]
    assert len(cids) >= 2
    assert len(set(cids)) == len(cids)


def _set(var, site):
    operation = SimpleNamespace(
        name="set", arguments=(TermValue(1),), keyword_names=(), blame=site
    )
    return var.call_method_with(operation, None).value


def test_a_contextvar_token_is_its_set_occurrence() -> None:
    var = LanguageOwnedContextVarValue(name="probe")
    first = _set(var, "mod.py:3:4")
    for _ in range(3):
        _set(var, "elsewhere.py:1:0")
    again = _set(var, "mod.py:3:4")
    assert isinstance(first, LanguageOwnedContextVarToken)
    assert first == again
    assert first.to_term(owner="test") == again.to_term(owner="test")


def test_two_set_sites_are_two_tokens() -> None:
    var = LanguageOwnedContextVarValue(name="probe")
    left = _set(var, "mod.py:3:4")
    right = _set(var, "mod.py:9:4")
    assert left != right
    assert left.to_term(owner="test") != right.to_term(owner="test")
