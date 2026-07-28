"""NodeShapeV2: a node authenticates its OWN structure plus its children's CIDs.

V1 embedded each child's FULL subtree preimage inside its parent, so the same
descendant content was authenticated once for every ancestor path above it.
Total encoding work was the sum of all subtree sizes -- quadratic in depth.
Measured on pandas ``core/reshape/pivot.py::__internal_pivot_table``: 624s
cumulative in ``canonical_json_bytes`` over only 1,318 CID calls, each hashing
a JSON tree of ~12,800 nodes.

V2 is the Merkle form the content-addressed graph always wanted. A parent
authenticates its immediate structure and the authenticated IDENTITIES of its
children. Each node encodes a preimage of its OWN arity; the whole tree is
O(n). Measured on a left-nested BinOp chain, log-log slope of total encoded
preimage bytes against node count: V1 = 1.92, V2 = 1.00.

This migration DOES change every shape CID, deliberately. Shape CIDs are
REPRESENTATION identity, never meaning -- constructed formulas, bindings,
effects, gaps and ExitSets are unchanged, and those are what the equivalence
proof measures. A fingerprint built from shape CIDs would be circular here.

These twins pin what the preimage must NOT lose and must NOT merge:

  * every perturbation BITES -- reordered, duplicated, omitted children,
    changed slot names, changed leaf values, changed kind, changed operators;
  * every slot KIND stays mutually distinguishable -- ``MaybeChild(None)`` is
    not an absent slot, ``Children([x])`` is not ``Child(x)``, ``Children([])``
    is not ``MaybeChild(None)``, and a ``Leaf`` carrying a CID string is not a
    ``Child`` carrying that CID;
  * structurally identical children SHARE content identity WITHOUT sharing
    occurrence identity -- same CID, two live refs, two ordered positions;
  * V1 and V2 never share an identity namespace: the V2 preimage carries a
    domain, a schema tag, and a NAMED child-CID algorithm that no V1 preimage
    ever carried.
"""

from sugar_source_tree import construction_cache as CC
from sugar_source_tree.backend import (
    BackendNode,
    Child,
    Children,
    Description,
    Leaf,
    MaybeChild,
    OpLeaf,
    OpsLeaf,
)
from sugar_source_tree.binding_state import (
    NODE_SHAPE_V2_CHILD_CID_ALGORITHM,
    NODE_SHAPE_V2_DOMAIN,
    NODE_SHAPE_V2_SCHEMA,
    _node_shape_v2_preimage,
    backend_node_shape_cid_v2,
)
from sugar_source_tree.operators import operator_for


class _H(BackendNode):
    """A synthetic backend node carrying exactly the slots it is handed."""

    def __init__(self, kind, slots):
        self._kind = kind
        self._slots = tuple(slots)

    def describe(self):
        return Description(
            kind=self._kind, raw_span=None, anchors=(), slots=self._slots
        )


def _name(n):
    return _H("Name", (("id", Leaf(n)),))


def _cid(ref):
    return backend_node_shape_cid_v2(ref)


def test_reordered_children_change_the_parent_cid():
    a = _H("Tuple", (("elts", Children((_name("x"), _name("y")))),))
    b = _H("Tuple", (("elts", Children((_name("y"), _name("x")))),))
    assert _cid(a) != _cid(b)


def test_changed_slot_name_changes_the_parent_cid():
    a = _H("Attr", (("value", Child(_name("x"))),))
    b = _H("Attr", (("target", Child(_name("x"))),))
    assert _cid(a) != _cid(b)


def test_changed_leaf_value_changes_the_cid():
    assert _cid(_name("x")) != _cid(_name("y"))


def test_duplicated_child_changes_the_parent_cid():
    one = _H("Tuple", (("elts", Children((_name("x"),))),))
    two = _H("Tuple", (("elts", Children((_name("x"), _name("x")))),))
    assert _cid(one) != _cid(two)


def test_omitted_child_changes_the_parent_cid():
    both = _H("Tuple", (("elts", Children((_name("x"), _name("y")))),))
    one = _H("Tuple", (("elts", Children((_name("x"),))),))
    assert _cid(both) != _cid(one)


def test_changed_kind_changes_the_cid():
    a = _H("Tuple", (("elts", Children((_name("x"),))),))
    b = _H("List", (("elts", Children((_name("x"),))),))
    assert _cid(a) != _cid(b)


def test_present_but_empty_is_not_absent():
    # MaybeChild(None) is a structural absence WITHIN a present slot. A slot
    # the backend never emitted is a different shape, and must stay one.
    empty = _H("Ret", (("value", MaybeChild(None)),))
    missing = _H("Ret", ())
    assert _cid(empty) != _cid(missing)


def test_repeated_slot_is_not_a_single_slot():
    repeated = _H("N", (("s", Children((_name("x"),))),))
    single = _H("N", (("s", Child(_name("x"))),))
    assert _cid(repeated) != _cid(single)


def test_two_different_empties_stay_different():
    no_children = _H("N", (("s", Children(())),))
    no_child = _H("N", (("s", MaybeChild(None)),))
    assert _cid(no_children) != _cid(no_child)


def test_a_leaf_carrying_a_cid_is_not_a_child():
    # The child slot carries a CID STRING. A leaf slot must never be readable
    # as a child slot carrying the same string -- the wrapper key separates
    # them, and ``childCidAlgorithm`` names what minted the child's string.
    child_cid = _cid(_name("x"))
    leafy = _H("N", (("s", Leaf(child_cid)),))
    childy = _H("N", (("s", Child(_name("x"))),))
    assert _cid(leafy) != _cid(childy)


def test_operator_leaves_are_authenticated():
    blame = "test_node_shape_v2_merkle.py:operator"
    add = _H("BinOp", (("op", OpLeaf(operator_for("Add", blame=blame))),))
    sub = _H("BinOp", (("op", OpLeaf(operator_for("Sub", blame=blame))),))
    assert _cid(add) != _cid(sub)

    lt_gt = _H(
        "Cmp",
        (
            (
                "ops",
                OpsLeaf(
                    (operator_for("Lt", blame=blame), operator_for("Gt", blame=blame))
                ),
            ),
        ),
    )
    gt_lt = _H(
        "Cmp",
        (
            (
                "ops",
                OpsLeaf(
                    (operator_for("Gt", blame=blame), operator_for("Lt", blame=blame))
                ),
            ),
        ),
    )
    assert _cid(lt_gt) != _cid(gt_lt)

    ops_one = _H("Cmp", (("ops", OpsLeaf((operator_for("Lt", blame=blame),))),))
    op_one = _H("Cmp", (("ops", OpLeaf(operator_for("Lt", blame=blame))),))
    assert _cid(ops_one) != _cid(op_one)


def test_identical_children_share_content_identity_not_occurrence_identity():
    # BOTH arms are required. Identical structure MUST address identically --
    # that is what content-addressing means, and it is what makes the Merkle
    # form linear. It must NOT thereby collapse two occurrences into one: two
    # identical `o[i]` reads at different sites stay two sites.
    left = _H("Sub", (("v", Child(_name("o"))), ("k", Child(_name("i")))))
    right = _H("Sub", (("v", Child(_name("o"))), ("k", Child(_name("i")))))
    assert left is not right
    assert _cid(left) == _cid(right)  # content identity: SHARED

    parent = _H("Tuple", (("elts", Children((left, right))),))
    backend_node_shape_cid_v2(parent)

    # The ref-keyed memo holds TWO rows carrying ONE value: two live refs.
    assert CC.shape_cid_v2_for(left) is not None
    assert CC.shape_cid_v2_for(right) is not None
    assert CC.shape_cid_v2_for(left) == CC.shape_cid_v2_for(right)

    # And the parent carries TWO ordered positions, not a deduped one.
    pre = _node_shape_v2_preimage(
        parent,
        {id(left): CC.shape_cid_v2_for(left), id(right): CC.shape_cid_v2_for(right)},
    )
    positions = pre["slots"][0]["value"]["children"]
    assert len(positions) == 2
    assert positions[0] == positions[1]

    # Dropping one of the two identical occurrences is a DIFFERENT parent.
    assert _cid(parent) != _cid(_H("Tuple", (("elts", Children((left,))),)))


def test_v2_preimage_is_explicitly_domain_separated():
    pre = _node_shape_v2_preimage(_name("x"), {})
    assert pre["domain"] == NODE_SHAPE_V2_DOMAIN
    assert pre["schema"] == NODE_SHAPE_V2_SCHEMA
    # The child-CID ALGORITHM is named in every preimage, so a child slot's
    # string can never be mistaken for a CID minted by some other schema.
    assert pre["childCidAlgorithm"] == NODE_SHAPE_V2_CHILD_CID_ALGORITHM
    # No V1 preimage ever carried these keys, so no V1 CID is reinterpretable
    # as V2: the two live in different identity namespaces.
    assert set(pre) == {"domain", "schema", "childCidAlgorithm", "kind", "slots"}


def test_construction_is_bottom_up_and_never_embeds_a_subtree():
    # A deep left-nested chain. Recursive subtree embedding cannot even ENCODE
    # this (RecursionError, and quadratic bytes before that); bottom-up
    # iteration encodes each node once, at its own arity.
    node = _name("a")
    for _ in range(2000):
        node = _H(
            "BinOp",
            (
                ("left", Child(node)),
                (
                    "op",
                    OpLeaf(
                        operator_for("Add", blame="test_node_shape_v2_merkle.py:deep")
                    ),
                ),
            ),
        )
    cid = backend_node_shape_cid_v2(node)
    assert cid.startswith("blake3-512:")
    # Every descendant is memoized -- each encoded exactly once, ever.
    assert CC.shape_cid_v2_for(node) == cid
    assert CC.shape_cid_v2_for(node._slots[0][1].handle) is not None
