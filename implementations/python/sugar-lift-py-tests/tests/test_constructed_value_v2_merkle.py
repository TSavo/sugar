"""ConstructedValueV2: a value authenticates its children's CIDs, not their content.

NodeShapeV2 (#6253) fixed the NODE layer. The CONSTRUCTED SEMANTIC VALUE layer
one level up still recursively INLINED every child value's canonical form, so
the shared constructed DAG was walked as a TREE and the same descendant content
was encoded once for every ancestor path above it. Measured after #6253:
``cid_of_json`` 2,736s cumulative over only 1,482 calls out of
``present_construction`` -- ~39,100 JSON nodes per call -- on pandas
``core/reshape/pivot.py::__internal_pivot_table``.

V2 is T's child identity law made mechanical: a child constructed semantic value
is referenced by a DOMAIN-SEPARATED CID of that child's immutable semantic
content, and its OCCURRENCE identity remains separate and is never inferred from
the content CID. Two identities, always explicit:

    semantic content CID     answers "what value?"
    construction occurrence  answers "which construction/site produced it?"

These twins pin what the form must NOT lose and must NOT merge:

  * every perturbation BITES -- reordered tuple children, renamed dataclass
    fields, changed mapping pairing, omitted and duplicated children, changed
    leaf values, changed semantic type;
  * every category stays mutually distinguishable -- a leaf carrying a
    CID-shaped string is not a child carrying that CID, an ``IntEnum`` member is
    not the bare integer, an empty tuple is not an empty mapping;
  * equal content SHARES the semantic CID and NEVER shares occurrence -- same
    CID, distinct objects, distinct ``at`` coordinates, distinct rows;
  * a shared DAG child is hashed ONCE per content coordinate;
  * classification is CLOSED -- mutable containers, mutable dataclasses, cycles
    and unnameable categories are typed testimony gaps, never reflection and
    never an opportunistic snapshot;
  * V1 and V2 never share an identity namespace.
"""

from dataclasses import dataclass
from enum import Enum, IntEnum

import pytest

from sugar_lift_python_source.canonical import cid_of_json
from sugar_source_tree import binding_state as BS
from sugar_source_tree import construction_cache as CC
from sugar_source_tree.binding_state import (
    CONSTRUCTED_VALUE_V2_CHILD_CID_ALGORITHM,
    CONSTRUCTED_VALUE_V2_DOMAIN,
    CONSTRUCTED_VALUE_V2_SCHEMA,
    ConstructedValueCategoryGap,
    _constructed_preimage,
    constructed_value_cid_v2,
    constructed_value_slot_v2,
)


@dataclass(frozen=True)
class Pair:
    left: object
    right: object


@dataclass(frozen=True)
class Renamed:
    left: object
    other: object


@dataclass(frozen=True)
class Chain:
    tail: object


@dataclass(frozen=True)
class Holder:
    items: object


@dataclass
class Mutable:
    field: object


class Colour(Enum):
    RED = 1
    BLUE = 1  # noqa: PIE796 -- deliberately EQUAL payload, distinct spelling


class Shade(Enum):
    RED = 1
    BLUE = 2


class Level(IntEnum):
    LOW = 1
    HIGH = 2


class Cyclic:
    """A frozen-looking value that can be knotted after construction."""


@dataclass(frozen=True)
class Knot:
    other: object


class WireOnly:
    """Exposes ``.wire()`` and nothing authenticated. V1 walked it; V2 will not."""

    def wire(self):
        return {"anything": "at all"}


class ClaimsCid:
    """Claims a ``cid`` its ``preimage`` does not hash to."""

    preimage = {"kind": "not-really"}
    cid = "blake3-512:" + "0" * 8


class HonestCid:
    """A genuinely self-authenticating value: ``cid_of_json(preimage) == cid``."""

    preimage = {"kind": "honest", "schemaVersion": "1", "payload": [1, 2, 3]}

    @property
    def cid(self):
        return cid_of_json(self.preimage)


def test_producer_owned_binary_operator_projector_is_a_closed_leaf():
    from sugar_source_tree.operators import Add, Sub

    add = BS._cv2_leaf(Add.instance().project_inplace)
    subtract = BS._cv2_leaf(Sub.instance().project_inplace)

    assert add != subtract
    assert add == {
        "operatorProjector": {"operatorKind": "Add", "inplaceOperator": "iadd"}
    }


def test_arbitrary_bound_method_is_not_a_constructed_value_leaf():
    class Arbitrary:
        def project(self, left, right, site):
            return left, right, site

    with pytest.raises(ConstructedValueCategoryGap, match="builtins.method"):
        _constructed_preimage((Arbitrary().project,))


def test_callsite_definition_authority_is_a_source_node_not_backend_handle(tmp_path):
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_source_tree.nodes import Call
    from sugar_source_tree.tree import SourceFile

    path = tmp_path / "calls.py"
    path.write_text(
        "def helper(value):\n"
        "    return value\n\n"
        "def caller(value):\n"
        "    return helper(value)\n"
    )
    source = SourceFile(path_source(str(path)))
    helper, caller = source.functions()
    (call,) = tuple(node for node in caller.walk() if isinstance(node, Call))
    sugar = call.sugar()

    assert sugar.expected_definition is helper
    _constructed_preimage(sugar)


# ---------------------------------------------------------------------------
# Domain separation and namespace disjointness
# ---------------------------------------------------------------------------


def test_every_preimage_names_its_domain_schema_and_child_cid_algorithm():
    """A child slot's string can never be read as a leaf or a foreign CID."""
    preimage = BS._cv2_preimage("tuple", 0, [], [], {})
    assert preimage["domain"] == CONSTRUCTED_VALUE_V2_DOMAIN
    assert preimage["schema"] == CONSTRUCTED_VALUE_V2_SCHEMA
    assert preimage["childCidAlgorithm"] == CONSTRUCTED_VALUE_V2_CHILD_CID_ALGORITHM
    assert set(preimage) == {
        "domain",
        "schema",
        "childCidAlgorithm",
        "semanticType",
        "arity",
        "localFields",
        "children",
    }


def test_v1_and_v2_envelopes_are_disjoint_identity_namespaces():
    envelope = _constructed_preimage(Pair(1, 2))
    assert envelope["schemaVersion"] == "2"
    assert envelope["valueSchema"] == CONSTRUCTED_VALUE_V2_SCHEMA
    assert envelope["childCidAlgorithm"] == CONSTRUCTED_VALUE_V2_CHILD_CID_ALGORITHM
    # The V1 envelope carried NEITHER key and said "1". Reconstructing it and
    # hashing it can never collide with the V2 envelope for the same value.
    v1_shaped = {
        "kind": "constructed-semantic-value",
        "schemaVersion": "1",
        "value": {"constructedType": "x", "fields": {}},
    }
    assert cid_of_json(v1_shaped) != cid_of_json(envelope)


def test_a_leaf_carrying_a_cid_string_is_not_a_child_carrying_that_cid():
    """Leaves and children live under different keys, so they cannot collide."""
    inner = Pair(1, 2)
    inner_cid = constructed_value_cid_v2(inner)
    as_child = constructed_value_cid_v2(Chain(inner))
    as_leaf_string = constructed_value_cid_v2(Chain(inner_cid))
    assert as_child != as_leaf_string
    assert constructed_value_slot_v2(inner) == {"constructedValueCid": inner_cid}
    assert constructed_value_slot_v2(inner_cid) == {"leaf": {"str": inner_cid}}


# ---------------------------------------------------------------------------
# No embedded child preimages; bottom-up construction
# ---------------------------------------------------------------------------


def test_a_parent_preimage_embeds_child_CIDS_never_child_content():
    left, right = Pair(1, 2), Pair(3, 4)
    parent = Pair(left, right)
    semantic_type, arity, local_fields, children = BS._cv2_classify(parent)
    child_cid = {
        id(left): constructed_value_cid_v2(left),
        id(right): constructed_value_cid_v2(right),
    }
    preimage = BS._cv2_preimage(semantic_type, arity, local_fields, children, child_cid)
    assert preimage["localFields"] == []
    assert preimage["children"] == [
        {"at": "left", "childConstructedValueCid": child_cid[id(left)]},
        {"at": "right", "childConstructedValueCid": child_cid[id(right)]},
    ]
    # A child slot carries a CID and NOTHING else -- no fragment of the child's
    # own preimage (its semanticType, its localFields, its own children) leaks
    # into its parent. That absence IS the linear form.
    for entry in preimage["children"]:
        assert set(entry) == {"at", "childConstructedValueCid"}
    child_preimage = BS._cv2_preimage(*BS._cv2_classify(left), {})
    assert child_preimage["localFields"] == [
        {"at": "left", "leaf": {"int": 1}},
        {"at": "right", "leaf": {"int": 2}},
    ]
    for key in ("semanticType", "localFields", "children", "arity"):
        assert key not in str(preimage["children"])
    # The parent's OWN preimage stays O(its own arity): two entries, two CIDs.
    assert preimage["arity"] == 2 and len(preimage["children"]) == 2


def test_construction_is_bottom_up_and_survives_a_tree_deeper_than_recursion():
    """3,000 deep: a recursive encoder dies here; the iterative one does not."""
    import sys

    assert sys.getrecursionlimit() < 3000
    value = Pair(0, 0)
    for _ in range(3000):
        value = Chain(value)
    assert constructed_value_cid_v2(value).startswith("blake3-512:")


def _encoded_bytes(presented):
    """Total bytes hashed while PRESENTING every value in a construction.

    ``present_construction`` mints a semantic-value CID for EVERY node's
    constructed value, never only the root -- and that is exactly where V1's
    cost lived: each presentation re-encoded its whole subtree, so total work
    was the sum of all subtree sizes. The memo stays warm across presentations,
    as in the census loop.
    """
    from sugar_lift_python_source import canonical as CANON

    CC._CONSTRUCTED_VALUE_CIDS_V2.clear()
    total = [0]
    original = CANON.canonical_json_bytes

    def counting(value):
        out = original(value)
        total[0] += len(out)
        return out

    CANON.canonical_json_bytes = counting
    try:
        for value in presented:
            BS.cid_of_json(_constructed_preimage(value))
    finally:
        CANON.canonical_json_bytes = original
    return total[0]


def _slope(points):
    import math

    xs = [math.log(n) for n, _ in points]
    ys = [math.log(b) for _, b in points]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum(
        (x - mx) ** 2 for x in xs
    )


def test_depth_sweep_total_encoded_work_is_linear():
    """Measured fitted log-log slope: V1 = 1.96 (quadratic), V2 = 0.99."""

    def depth_case(n):
        value = Pair(0, 0)
        presented = [value]
        for _ in range(n):
            value = Chain(value)
            presented.append(value)
        return presented

    points = [(n, _encoded_bytes(depth_case(n))) for n in (50, 100, 200, 400)]
    slope = _slope(points)
    assert 0.85 <= slope <= 1.15, f"depth encoded-work slope {slope:.2f} is not linear"


def test_breadth_sweep_total_encoded_work_is_linear():
    """Breadth was already linear in V1 (slope 1.00); V2 must not lose that."""

    def breadth_case(n):
        kids = tuple(Pair(i, f"k{i}") for i in range(n))
        return [*kids, Holder(kids)]

    points = [(n, _encoded_bytes(breadth_case(n))) for n in (50, 100, 200, 400)]
    slope = _slope(points)
    assert (
        0.85 <= slope <= 1.15
    ), f"breadth encoded-work slope {slope:.2f} is not linear"


def test_a_shared_dag_child_is_hashed_once_per_content_coordinate():
    CC._CONSTRUCTED_VALUE_CIDS_V2.clear()
    shared = Pair(1, 2)
    calls = []
    original = BS.cid_of_json

    def counting(value):
        calls.append(value.get("semanticType"))
        return original(value)

    BS.cid_of_json = counting
    try:
        constructed_value_cid_v2(Pair(Pair(shared, shared), Pair(shared, shared)))
    finally:
        BS.cid_of_json = original
    # 1 shared + 2 middles + 1 root == 4 preimages, not 4 + 4 paths to `shared`.
    assert len(calls) == 4


# ---------------------------------------------------------------------------
# Every perturbation BITES
# ---------------------------------------------------------------------------


def test_reordered_tuple_children_change_the_parent_cid():
    a, b = Pair(1, 2), Pair(3, 4)
    assert constructed_value_cid_v2((a, b)) != constructed_value_cid_v2((b, a))


def test_omitted_and_duplicated_children_change_the_parent_cid():
    a, b = Pair(1, 2), Pair(3, 4)
    both = constructed_value_cid_v2((a, b))
    omitted = constructed_value_cid_v2((a,))
    duplicated = constructed_value_cid_v2((a, b, b))
    assert len({both, omitted, duplicated}) == 3
    assert constructed_value_cid_v2((a, a)) != constructed_value_cid_v2((a,))


def test_renamed_fields_change_the_cid_even_with_identical_field_values():
    assert constructed_value_cid_v2(Pair(1, 2)) != constructed_value_cid_v2(
        Renamed(1, 2)
    )


def test_changed_mapping_pairing_changes_the_cid():
    a, b = Pair(1, 2), Pair(3, 4)
    straight = constructed_value_cid_v2(Holder({"x": a, "y": b}))
    swapped = constructed_value_cid_v2(Holder({"x": b, "y": a}))
    assert straight != swapped
    # The same VALUES under different KEYS also bite.
    renamed = constructed_value_cid_v2(Holder({"p": a, "q": b}))
    assert renamed != straight


def test_changed_leaf_values_and_semantic_types_bite():
    assert constructed_value_cid_v2(Pair(1, 2)) != constructed_value_cid_v2(Pair(1, 3))
    assert constructed_value_cid_v2(Holder(())) != constructed_value_cid_v2(Holder({}))
    assert constructed_value_cid_v2(()) != constructed_value_cid_v2({})


def test_a_bool_is_not_an_int_and_an_intenum_is_not_its_integer():
    assert constructed_value_cid_v2(Holder(True)) != constructed_value_cid_v2(Holder(1))
    # V1 tested ``int`` BEFORE ``Enum``, so an IntEnum member encoded as a bare
    # integer and the member was LOST. V2 keeps the member.
    assert constructed_value_cid_v2(Holder(Level.LOW)) != constructed_value_cid_v2(
        Holder(1)
    )


def test_enum_members_with_equal_payloads_stay_distinguishable():
    """``Colour.RED`` and ``Colour.BLUE`` share the payload 1; V1 encoded the
    payload, so it could not tell two same-payload members apart. V2 encodes the
    member TAG."""
    assert Colour.BLUE is Colour.RED  # Python aliases them: one member, two spellings
    # Two DIFFERENT enum types whose members carry the same payload must differ.
    assert constructed_value_cid_v2(Holder(Colour.RED)) != constructed_value_cid_v2(
        Holder(Shade.RED)
    )
    assert constructed_value_cid_v2(Holder(Shade.RED)) != constructed_value_cid_v2(
        Holder(Shade.BLUE)
    )


def test_a_frozenset_authenticates_membership_not_iteration_order():
    a, b, c = Pair(1, 2), Pair(3, 4), Pair(5, 6)
    one = constructed_value_cid_v2(frozenset({a, b, c}))
    two = constructed_value_cid_v2(frozenset({c, a, b}))
    assert one == two
    assert one != constructed_value_cid_v2(frozenset({a, b}))


# ---------------------------------------------------------------------------
# Content identity WITHOUT occurrence identity
# ---------------------------------------------------------------------------


def test_equal_content_shares_the_semantic_cid_and_never_the_occurrence():
    one, two = Pair(1, 2), Pair(1, 2)
    assert one is not two
    assert constructed_value_cid_v2(one) == constructed_value_cid_v2(two)
    # Two DISTINCT rows in the registry -- one per live object -- carrying the
    # same value. Content-addressing the VALUE must never merge the OCCURRENCES.
    rows = [
        key
        for key in CC._CONSTRUCTED_VALUE_CIDS_V2
        if key[1] is Pair and key[2] in (id(one), id(two))
    ]
    assert len(rows) == 2
    assert CC.constructed_value_cid_v2_for(one) == CC.constructed_value_cid_v2_for(two)
    # And they still occupy DISTINCT ordered coordinates in a parent.
    _, entries = BS._cv2_entries((one, two))
    assert [at for at, _child in entries] == [0, 1]


def test_two_equal_children_do_not_collapse_their_parents_arity():
    one, two = Pair(1, 2), Pair(1, 2)
    assert constructed_value_cid_v2((one, two)) != constructed_value_cid_v2((one,))


def test_a_dead_objects_address_is_never_read_for_a_live_one():
    """The registry row is honored only while its weakref resolves to the SAME
    object, so a recycled address misses instead of reading a dead value's CID."""
    victim = Pair(1, 2)
    coordinate = ("constructed-value-v2", Pair, id(victim))
    constructed_value_cid_v2(victim)
    assert coordinate in CC._CONSTRUCTED_VALUE_CIDS_V2
    del victim
    assert coordinate not in CC._CONSTRUCTED_VALUE_CIDS_V2


def test_only_frozen_values_take_a_registry_row():
    # A mapping is MUTABLE: the same object can encode two ways over its
    # lifetime, so identity is not a content coordinate and it gets no row. A
    # tuple is immutable but its preimage is exactly its children's already
    # memoized CIDs, so a row would buy the walk of one value's own arity.
    assert CC._constructed_value_coordinate({"a": 1}) is None
    assert CC._constructed_value_coordinate((1, 2)) is None
    assert CC._constructed_value_coordinate(Mutable(1)) is None
    assert CC._constructed_value_coordinate(1) is None
    # The frozen ones DO -- held live, so the weakref-bounded table keeps them.
    inner = Pair(9, 9)
    outer = Holder({"a": inner})
    constructed_value_cid_v2(outer)
    assert CC.constructed_value_cid_v2_for(outer) is not None
    assert CC.constructed_value_cid_v2_for(inner) is not None


# ---------------------------------------------------------------------------
# Classification is CLOSED: typed gaps, never reflection
# ---------------------------------------------------------------------------


def test_a_mutable_container_is_a_typed_gap_never_an_opportunistic_snapshot():
    for mutable in ([1, 2], {1, 2}, bytearray(b"ab")):
        with pytest.raises(ConstructedValueCategoryGap) as caught:
            constructed_value_cid_v2(Holder(mutable))
        assert "MUTABLE container" in str(caught.value)


def test_a_mutable_dataclass_is_a_typed_gap():
    with pytest.raises(ConstructedValueCategoryGap) as caught:
        constructed_value_cid_v2(Holder(Mutable(1)))
    assert "MUTABLE dataclass" in str(caught.value)


def test_an_unnameable_category_is_a_typed_gap_never_reflection():
    with pytest.raises(ConstructedValueCategoryGap) as caught:
        constructed_value_cid_v2(Holder(object()))
    assert "will not invent a preimage by reflection" in str(caught.value).replace(
        "\n", " "
    ).replace("  ", " ")


def test_a_bare_wire_method_earns_nothing():
    """V1 called ``.wire()`` generically. V2 never does: an arbitrary method's
    inputs cannot be enumerated, so it cannot authenticate anything."""
    with pytest.raises(ConstructedValueCategoryGap):
        constructed_value_cid_v2(Holder(WireOnly()))


def test_a_cycle_is_a_typed_gap_never_a_truncation():
    knot = Knot(None)
    inner = Knot(knot)
    object.__setattr__(knot, "other", inner)
    with pytest.raises(ConstructedValueCategoryGap) as caught:
        constructed_value_cid_v2(knot)
    assert "CYCLIC" in str(caught.value)


def test_a_non_string_mapping_key_is_a_typed_gap():
    with pytest.raises(ConstructedValueCategoryGap) as caught:
        constructed_value_cid_v2(Holder({1: "x"}))
    assert "string keys" in str(caught.value)


def test_the_gap_travels_the_existing_typed_testimony_door():
    """``present_construction`` catches ``(TypeError, ValueError)`` to mint the
    loud ``ConstructedValueTestimonyNotWritten``; the category gap must reach
    it."""
    assert issubclass(ConstructedValueCategoryGap, TypeError)


# ---------------------------------------------------------------------------
# The native-CID arm is VALIDATED, never trusted
# ---------------------------------------------------------------------------


def test_a_native_cid_is_referenced_only_when_it_authenticates_its_preimage():
    honest = HonestCid()
    assert BS._validated_native_cid(honest) == honest.cid
    assert constructed_value_slot_v2(honest) == {
        "leaf": {
            "authenticatedValueCid": {
                "type": BS._cv2_type_tag(honest),
                "cid": honest.cid,
            }
        }
    }
    # A claimed CID that does not hash its own preimage earns nothing, and the
    # value falls through to the closed classifier -- which refuses it.
    assert BS._validated_native_cid(ClaimsCid()) is None
    with pytest.raises(ConstructedValueCategoryGap):
        constructed_value_cid_v2(Holder(ClaimsCid()))


def test_a_natively_authenticated_child_is_never_walked():
    """Its whole document is replaced by its own CID: that is the linear form."""
    honest = HonestCid()
    semantic_type, arity, local_fields, children = BS._cv2_classify(Holder(honest))
    preimage = BS._cv2_preimage(semantic_type, arity, local_fields, children, {})
    assert preimage["children"] == []
    assert "payload" not in str(preimage)
