"""Multiple dispatch: accepts narrows the shape, owns interrogates operands."""

import pytest

from sugar_node_membrane import Membrane
from sugar_node_membrane.nodes import Assert, BinOp, Call, Name, Return

from sugar_typed_recognition import Role, TypedCatalog, default_catalog, operand_types
from sugar_typed_recognition.claims import (
    AddOpClaim,
    AnnotationUnionClaim,
    AssertClaim,
    KeywordCallClaim,
    LenCallClaim,
    MethodCallClaim,
    MultiplyOpClaim,
    MultiplyOpClaim as _Mult,
    NameClaim,
    PlainCallClaim,
    ReturnClaim,
)


def parse(source: str):
    return Membrane().parse(source)


def only(root, cls):
    """The single node of that class in the tree. Ambiguity in a fixture is a
    test defect, so this asserts uniqueness rather than taking the first."""
    found = [n for n in root.walk() if type(n) is cls]
    assert len(found) == 1, f"fixture holds {len(found)} {cls.__name__} nodes"
    return found[0]


# -- coordinate 0: accepts, by type -----------------------------------------


def test_accepts_prefilters_by_type_before_owns_is_called():
    """A claim's owns() is never invoked for a shape it does not accept."""
    calls: list[str] = []

    class Watcher(AssertClaim):
        accepts = Assert
        role = Role.STATEMENT

        @classmethod
        def owns(cls, site):
            calls.append(type(site).__name__)
            return True

    catalog = TypedCatalog((Watcher,))
    root = parse("x = 1 + 2\nassert x\n")
    for node in root.walk():
        catalog.candidates_for(Role.STATEMENT, node)

    # Assert is the only shape that ever reached owns(), though the walk
    # offered it Module, Assign, BinOp, Name, Constant, Expr...
    assert calls == ["Assert"]


def test_accepts_is_a_class_not_a_kind_string():
    for claim in default_catalog().claims:
        assert isinstance(claim.accepts, type)
        assert not isinstance(claim.accepts, str)


# -- coordinates 1..n: operand types, inside owns ---------------------------


@pytest.mark.parametrize(
    "source, expected",
    [
        ("y = a + b\n", AddOpClaim),
        ("y = a * b\n", MultiplyOpClaim),
        ("y = a | b\n", AnnotationUnionClaim),
    ],
)
def test_one_accepts_three_claims_dispatched_by_operator_type(source, expected):
    """The whole argument for a registry: same node class, different operand.

    All three claims declare accepts = BinOp. accepts narrows nothing between
    them; the TYPE of site.op decides. This is dispatch on two types at once.
    """
    root = parse(source)
    site = only(root, BinOp)
    assert default_catalog().resolve(Role.TERM, site) is expected


@pytest.mark.parametrize(
    "source, expected",
    [
        ("recv.method(1)\n", MethodCallClaim),
        ("f(1)\n", PlainCallClaim),
        ("len(xs)\n", LenCallClaim),
        ("f(k=1)\n", KeywordCallClaim),
    ],
)
def test_one_accepts_four_claims_dispatched_by_callee_type(source, expected):
    """accepts = Call for all four; the type of site.func discriminates."""
    root = parse(source)
    site = only(root, Call)
    assert default_catalog().resolve(Role.TERM, site) is expected


def test_operand_types_are_the_dispatch_key_tail():
    root = parse("y = a + b\n")
    site = only(root, BinOp)
    # left, right (children, in grammar order), then the operator.
    assert operand_types(site) == (Name, Name, type(site.op))


def test_a_plain_type_switch_could_not_express_this():
    """Receipt for the load-bearing claim in catalog.py's docstring.

    If accepts were the whole dispatch key, a dict from node class to claim
    would suffice. It does not: three claims share BinOp, four share Call.
    """
    by_accepts: dict[type, list[str]] = {}
    for claim in default_catalog().claims:
        by_accepts.setdefault(claim.accepts, []).append(claim.name())
    assert len(by_accepts[BinOp]) == 3
    assert len(by_accepts[Call]) == 4


# -- ordering is forced by the types, not by convention ---------------------


def test_operands_are_already_typed_when_the_parent_is_recognized():
    """Recognition is bottom-up because construction is.

    Every operand of every node in a real tree answers its own type. Nothing
    schedules this; it is a consequence of construct.py building parents FROM
    finished children.
    """
    root = parse(
        "def f(a, b):\n"
        "    assert len(a) + b * 2\n"
        "    return a.join(b)\n"
    )
    seen = 0
    for node in root.walk():
        for t in operand_types(node):
            assert isinstance(t, type)
            seen += 1
    assert seen > 0


def test_nested_dispatch_resolves_at_every_level():
    root = parse("assert len(xs) + n * 2\n")
    catalog = default_catalog()
    resolved = {
        type(n).__name__: catalog.resolve(
            Role.STATEMENT if isinstance(n, (Assert, Return)) else Role.TERM, n
        ).name()
        for n in root.walk()
        if isinstance(n, (Assert, BinOp, Call, Name))
    }
    assert resolved["Assert"] == "AssertClaim"
    assert resolved["Call"] == "LenCallClaim"
    assert resolved["Name"] == "NameClaim"


# -- collapsed claims -------------------------------------------------------


def test_claims_that_collapsed_entirely_to_accepts():
    """AssertClaim and NameClaim ask nothing: owns is True for every accepted
    site, because their old predicate was pure shape re-derivation."""
    root = parse("assert x\n")
    assert AssertClaim.owns(only(root, Assert)) is True
    assert NameClaim.owns(only(root, Name)) is True


def test_return_claim_reads_a_structural_absence_not_a_refusal():
    with_value = parse("def f():\n    return 1\n")
    bare = parse("def f():\n    return\n")
    assert ReturnClaim.owns(only(with_value, Return)) is True
    assert ReturnClaim.owns(only(bare, Return)) is False
    # ...and the bare one is then a GAP at resolve, not a silent skip.
    # (asserted in test_failure_arms.py)
