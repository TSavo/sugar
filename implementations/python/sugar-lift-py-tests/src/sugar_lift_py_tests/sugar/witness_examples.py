from __future__ import annotations

from sugar_lift_py_tests.sugar.witnesses import (
    EffectWitnessSource,
    SugarRedEffectWitnessPair,
    SugarWitnessPair,
    TypedRedEffectExpectation,
    WitnessSource,
)


def boolop_assertion_witness() -> SugarWitnessPair:
    return _boolop_wrapped_pair(
        name="boolop_assertion_literal",
        owner_sugar="BoolOpAssertionSugar",
        truthful="(1 == 1) and True",
        lying="(1 == 2) and True",
    )


def comparison_assertion_witness() -> SugarWitnessPair:
    return _boolop_wrapped_pair(
        name="comparison_assertion_boolop",
        owner_sugar="ComparisonAssertionSugar",
        truthful="(1 == 1) and True",
        lying="(1 == 2) and True",
    )


def truthy_assertion_witness() -> SugarWitnessPair:
    return _boolop_wrapped_pair(
        name="truthy_assertion_boolop",
        owner_sugar="TruthyAssertionSugar",
        truthful="True and True",
        lying="False and True",
    )


def not_assertion_witness() -> SugarWitnessPair:
    return _boolop_wrapped_pair(
        name="not_assertion_boolop",
        owner_sugar="NotSugar",
        truthful="(not False) and True",
        lying="(not True) and True",
    )


def membership_assertion_witness() -> SugarWitnessPair:
    return _boolop_wrapped_pair(
        name="membership_assertion_boolop",
        owner_sugar="MembershipAssertionSugar",
        truthful="(2 in [1, 2, 3]) and True",
        lying="(4 in [1, 2, 3]) and True",
    )


def identity_assertion_witness() -> SugarWitnessPair:
    return _boolop_wrapped_pair(
        name="identity_assertion_boolop",
        owner_sugar="IdentityAssertionSugar",
        truthful="(None is None) and True",
        lying="(1 is None) and True",
    )


def isinstance_assertion_witness() -> SugarWitnessPair:
    return _boolop_wrapped_pair(
        name="isinstance_assertion_boolop",
        owner_sugar="IsInstanceAssertionSugar",
        truthful="isinstance(1, int) and True",
        lying="isinstance(1, str) and True",
    )


def call_truth_assertion_witness() -> SugarWitnessPair:
    prefix = "def A(x):\n    return x == 1\n\n"
    return _boolop_wrapped_pair(
        name="call_truth_assertion_boolop",
        owner_sugar="CallTruthAssertionSugar",
        truthful="A(1) and True",
        lying="A(2) and True",
        prefix=prefix,
    )


def projected_equality_assertion_witness() -> SugarWitnessPair:
    prefix = "class C:\n" "    def __init__(self, x):\n" "        self.x = x\n" "\n"
    return _boolop_wrapped_pair(
        name="projected_equality_assertion_boolop",
        owner_sugar="ProjectedEqualityAssertionSugar",
        truthful="(C(1).x == 1) and True",
        lying="(C(1).x == 2) and True",
        prefix=prefix,
    )


def true_bool_literal_return_witness() -> SugarWitnessPair:
    return _call_return_pair(
        name="true_bool_literal_return",
        owner_sugar="TrueBoolLiteralSugar",
        body="True",
        truthful="True",
        lying="False",
    )


def false_bool_literal_return_witness() -> SugarWitnessPair:
    return _call_return_pair(
        name="false_bool_literal_return",
        owner_sugar="FalseBoolLiteralSugar",
        body="False",
        truthful="False",
        lying="True",
    )


def int_literal_return_witness() -> SugarWitnessPair:
    return _call_return_pair(
        name="int_literal_return",
        owner_sugar="IntLiteralSugar",
        body="5",
        truthful="5",
        lying="6",
    )


def name_return_witness() -> SugarWitnessPair:
    return _call_return_pair(
        name="name_return",
        owner_sugar="NameSugar",
        body="z",
        truthful="5",
        lying="6",
    )


def binop_return_witness() -> SugarWitnessPair:
    return _call_return_pair(
        name="binop_return",
        owner_sugar="BinOpSugar",
        body="z + 1",
        truthful="6",
        lying="7",
    )


def add_method_return_witness() -> SugarWitnessPair:
    return _call_return_pair(
        name="add_method_return",
        owner_sugar="AddSugar",
        body="z.add(1)",
        truthful="6",
        lying="7",
    )


def unary_op_return_witness() -> SugarWitnessPair:
    return _call_return_pair(
        name="unary_op_return",
        owner_sugar="UnaryOpSugar",
        body="+z",
        truthful="5",
        lying="6",
    )


def slice_string_return_witness() -> SugarWitnessPair:
    return _call_return_pair(
        name="slice_string_return",
        owner_sugar="SliceSugar",
        body='"abcdef"[1:3]',
        truthful="'bc'",
        lying="'bd'",
    )


def string_subscript_return_witness() -> SugarWitnessPair:
    return _call_return_pair(
        name="string_subscript_return",
        owner_sugar="StringSubscriptSugar",
        body='"ABC"[1]',
        truthful="'B'",
        lying="'A'",
    )


def attribute_return_witness() -> SugarWitnessPair:
    prefix = "class C:\n" "    def __init__(self, x):\n" "        self.x = x\n" "\n"
    return _call_return_pair(
        name="attribute_return",
        owner_sugar="AttributeSugar",
        body="C(z).x",
        truthful="5",
        lying="6",
        prefix=prefix,
    )


def builtin_len_return_witness() -> SugarWitnessPair:
    return _call_return_pair(
        name="builtin_len_return",
        owner_sugar="BuiltinCallSugar",
        body="len([1, 2, 3])",
        truthful="3",
        lying="2",
    )


def builder_ctor_len_return_witness() -> SugarWitnessPair:
    return _call_return_pair(
        name="builder_ctor_len_return",
        owner_sugar="BuilderCtorSugar",
        body="len(Builder([z]))",
        truthful="1",
        lying="2",
    )


def constant_bytes_return_witness() -> SugarWitnessPair:
    return _call_return_pair(
        name="constant_bytes_return",
        owner_sugar="ConstantSugar",
        body='b"x"',
        truthful='b"x"',
        lying='b"y"',
    )


def divmod_subscript_return_witness() -> SugarWitnessPair:
    return _call_return_pair(
        name="divmod_subscript_return",
        owner_sugar="DivmodBuiltinSugar",
        body="divmod(z, 2)[0]",
        truthful="2",
        lying="3",
    )


def format_int_return_witness() -> SugarWitnessPair:
    return _call_return_pair(
        name="format_int_return",
        owner_sugar="FormatBuiltinSugar",
        body='int(format(z, ""))',
        truthful="5",
        lying="6",
    )


def object_equality_return_witness() -> tuple[SugarWitnessPair, SugarWitnessPair]:
    prefix = "class C:\n" "    def __init__(self, x):\n" "        self.x = x\n" "\n"
    explicit_eq_prefix = (
        "class C:\n"
        "    def __init__(self, x):\n"
        "        self.x = x\n"
        "    def __eq__(self, other):\n"
        "        return self.x == other.x\n"
        "\n"
    )
    return (
        _call_return_pair(
            name="object_equality_identity_return",
            owner_sugar="ObjectEqualityTermSugar",
            body="C(z) == C(z)",
            truthful="False",
            lying="True",
            prefix=prefix,
        ),
        _call_return_pair(
            name="object_equality_return",
            owner_sugar="ObjectEqualityTermSugar",
            body="C(z) == C(z)",
            truthful="True",
            lying="False",
            prefix=explicit_eq_prefix,
        ),
    )


def object_rich_compare_return_witness() -> SugarWitnessPair:
    prefix = (
        "class C:\n"
        "    def __init__(self, x):\n"
        "        self.x = x\n"
        "    def __lt__(self, other):\n"
        "        return self.x < other.x\n"
        "\n"
    )
    return _call_return_pair(
        name="object_rich_compare_return",
        owner_sugar="ObjectRichComparisonTermSugar",
        body="C(z) < C(z + 1)",
        truthful="True",
        lying="False",
        prefix=prefix,
    )


def to_list_len_return_witness() -> SugarWitnessPair:
    return _call_return_pair(
        name="to_list_len_return",
        owner_sugar="ToListSugar",
        body="len((z, 2).to_list())",
        truthful="2",
        lying="3",
    )


def tuple_literal_subscript_return_witness() -> SugarWitnessPair:
    return _call_return_pair(
        name="tuple_literal_subscript_return",
        owner_sugar="TupleLiteralSugar",
        body="(z, 2)[1]",
        truthful="2",
        lying="3",
    )


def assign_return_witness() -> SugarWitnessPair:
    prefix = "def A(z):\n    x = z\n    return x\n\n"
    return _call_pair(
        name="assign_return",
        owner_sugar="AssignSugar",
        truthful=prefix + "def test_a():\n    assert A(1) == 1\n",
        lying=prefix + "def test_a():\n    assert A(1) == 2\n",
    )


def aug_assign_return_witness() -> SugarWitnessPair:
    prefix = "def A(z):\n    x = z\n    x += 2\n    return x\n\n"
    return _call_pair(
        name="aug_assign_return",
        owner_sugar="AugAssignSugar",
        truthful=prefix + "def test_a():\n    assert A(1) == 3\n",
        lying=prefix + "def test_a():\n    assert A(1) == 4\n",
    )


def block_return_witness() -> SugarWitnessPair:
    prefix = "def A(z):\n    x = z\n    y = x\n    return y\n\n"
    return _call_pair(
        name="block_return",
        owner_sugar="BlockSugar",
        truthful=prefix + "def test_a():\n    assert A(2) == 2\n",
        lying=prefix + "def test_a():\n    assert A(2) == 3\n",
    )


def less_than_return_witness() -> SugarWitnessPair:
    # `<` folds concrete operands to the True/False literal, and the literal picks
    # the if-face: the truthful twin rides the face `<` picked, the lying twin
    # asserts the other -- the pair proves the lift discriminates on order.
    prefix = (
        "def A(z):\n" "    if 1 < 2:\n" "        return z\n" "    return 0\n" "\n"
    )
    return _call_pair(
        name="less_than_return",
        owner_sugar="LessThanOpSugar",
        truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
        lying=prefix + "def test_a():\n    assert A(5) == 0\n",
    )


def greater_than_return_witness() -> SugarWitnessPair:
    # `>` is `b < a` with the operands swapped: folds concrete operands to the
    # True/False literal, and the literal picks the if-face. The truthful twin
    # rides the face `>` picked, the lying twin asserts the other -- the pair
    # proves the lift discriminates on order.
    prefix = (
        "def A(z):\n" "    if 2 > 1:\n" "        return z\n" "    return 0\n" "\n"
    )
    return _call_pair(
        name="greater_than_return",
        owner_sugar="GreaterThanOpSugar",
        truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
        lying=prefix + "def test_a():\n    assert A(5) == 0\n",
    )


def if_return_witness() -> SugarWitnessPair:
    prefix = "def A(z):\n" "    if z == 1:\n" "        return 7\n" "    return 0\n" "\n"
    return _call_pair(
        name="if_return",
        owner_sugar="IfSugar",
        truthful=prefix + "def test_a():\n    assert A(1) == 7\n",
        lying=prefix + "def test_a():\n    assert A(1) == 0\n",
    )


def raise_try_return_witness() -> SugarWitnessPair:
    prefix = (
        "def A(z):\n"
        "    try:\n"
        "        raise ValueError()\n"
        "    except ValueError:\n"
        "        return z\n"
        "\n"
    )
    return _call_pair(
        name="raise_try_return",
        owner_sugar="RaiseSugar",
        truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
        lying=prefix + "def test_a():\n    assert A(5) == 6\n",
    )


def tuple_assign_return_witness() -> SugarWitnessPair:
    prefix = "def A(z):\n    a, b = (z, 2)\n    return b\n\n"
    return _call_pair(
        name="tuple_assign_return",
        owner_sugar="TupleAssignSugar",
        truthful=prefix + "def test_a():\n    assert A(1) == 2\n",
        lying=prefix + "def test_a():\n    assert A(1) == 1\n",
    )


def multi_target_assign_return_witness() -> SugarWitnessPair:
    """Chained multi-target: `a, b = pair = (z, 2)` — residual sibling of os.uname()."""
    prefix = "def A(z):\n    a, b = pair = (z, 2)\n    return a\n\n"
    return _call_pair(
        name="multi_target_assign_return",
        owner_sugar="MultiTargetAssignSugar",
        truthful=prefix + "def test_a():\n    assert A(1) == 1\n",
        lying=prefix + "def test_a():\n    assert A(1) == 2\n",
    )


def tuple_unpack_assign_return_witness() -> SugarWitnessPair:
    prefix = (
        "def A(z):\n" "    pair = [z, 2]\n" "    a, b = pair\n" "    return b\n" "\n"
    )
    return _call_pair(
        name="tuple_unpack_assign_return",
        owner_sugar="TupleUnpackAssignSugar",
        truthful=prefix + "def test_a():\n    assert A(1) == 2\n",
        lying=prefix + "def test_a():\n    assert A(1) == 1\n",
    )


def with_return_witness() -> SugarWitnessPair:
    prefix = (
        "class C:\n"
        "    def __enter__(self):\n"
        "        return 1\n"
        "    def __exit__(self, a, b, c):\n"
        "        return False\n"
        "\n"
        "def A(z):\n"
        "    with C() as x:\n"
        "        return z\n"
        "\n"
    )
    return _call_pair(
        name="with_return",
        owner_sugar="WithSugar",
        truthful=prefix + "def test_a():\n    assert A(1) == 1\n",
        lying=prefix + "def test_a():\n    assert A(1) == 2\n",
    )


def inert_statement_return_witness(
    *,
    name: str,
    owner_sugar: str,
    statement: str,
    prefix: str = "",
) -> SugarWitnessPair:
    body = "".join(f"    {line}\n" for line in statement.splitlines())
    source = prefix + f"def A(z):\n{body}    return z\n\n"
    return _call_pair(
        name=name,
        owner_sugar=owner_sugar,
        truthful=source + "def test_a():\n    assert A(1) == 1\n",
        lying=source + "def test_a():\n    assert A(1) == 2\n",
    )


def ord_byte_return_witness(*, owner_sugar: str) -> SugarWitnessPair:
    source = "def A(s):\n" "    return ord(s[0])\n" "\n"
    return _call_pair(
        name="ord_byte_return",
        owner_sugar=owner_sugar,
        truthful=source + "def test_a():\n    assert A('x') == 120\n",
        lying=source + "def test_a():\n    assert A('x') == 121\n",
    )


def typed_red_effect_witness(
    *,
    name: str,
    owner_sugar: str,
    source: str,
    effect_class: str,
    reason_needle: str,
    blame_needle: str,
    wrong_reason_needle: str,
) -> SugarRedEffectWitnessPair:
    return SugarRedEffectWitnessPair(
        name=name,
        owner_sugar=owner_sugar,
        family="typed-red-effect",
        truthful=EffectWitnessSource(
            source=source,
            expectation=TypedRedEffectExpectation(
                effect_class=effect_class,
                reason_needle=reason_needle,
                blame_needle=blame_needle,
            ),
            expected_match=True,
        ),
        lying=EffectWitnessSource(
            source=source,
            expectation=TypedRedEffectExpectation(
                effect_class=effect_class,
                reason_needle=wrong_reason_needle,
                blame_needle=blame_needle,
            ),
            expected_match=False,
        ),
    )


def collection_len_return_witness(
    *,
    name: str,
    owner_sugar: str,
    expression: str,
    truthful: int,
    lying: int,
) -> SugarWitnessPair:
    source = f"def A():\n    return len({expression})\n\n"
    return _call_pair(
        name=name,
        owner_sugar=owner_sugar,
        truthful=source + f"def test_a():\n    assert A() == {truthful}\n",
        lying=source + f"def test_a():\n    assert A() == {lying}\n",
    )


def _boolop_wrapped_pair(
    *,
    name: str,
    owner_sugar: str,
    truthful: str,
    lying: str,
    prefix: str = "",
) -> SugarWitnessPair:
    return _call_pair(
        name=name,
        owner_sugar=owner_sugar,
        truthful=prefix + f"def test_a():\n    assert {truthful}\n",
        lying=prefix + f"def test_a():\n    assert {lying}\n",
        family="assertion",
    )


def _call_return_pair(
    *,
    name: str,
    owner_sugar: str,
    body: str,
    truthful: str,
    lying: str,
    prefix: str = "",
) -> SugarWitnessPair:
    base = prefix + f"def A(z):\n    return {body}\n\n"
    return _call_pair(
        name=name,
        owner_sugar=owner_sugar,
        truthful=base + f"def test_a():\n    assert A(5) == {truthful}\n",
        lying=base + f"def test_a():\n    assert A(5) == {lying}\n",
        family="literal-call",
    )


def _call_pair(
    *,
    name: str,
    owner_sugar: str,
    truthful: str,
    lying: str,
    family: str = "literal-call",
) -> SugarWitnessPair:
    return SugarWitnessPair(
        name=name,
        owner_sugar=owner_sugar,
        family=family,
        truthful=WitnessSource(source=truthful, expected="sat"),
        lying=WitnessSource(source=lying, expected="unsat"),
    )
