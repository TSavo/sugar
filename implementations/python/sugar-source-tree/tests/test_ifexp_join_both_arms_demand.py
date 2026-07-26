"""`IfExpSugar._join` x a pending caller-parameter contract demand: the face law.

THE OWNER AND THE VALUE CATEGORY. One owner, `IfExpSugar._join`; one value
category, *a completed floor value carrying a PENDING caller-parameter contract
demand*, addressed by `demand_cid` -- the content address over owner source
identity, formal coordinate, operation site, demanded formula and candidate.
The category is read off the demand's own authenticated testimony, never off a
lexical type name and never off the vendor spelling that happened to produce it.

WHAT THIS OWNER OWES THAT NO OTHER CALLER OF THE CARRIER OWES. `#6352` widened
`ContractConditionalConstructionV1` to hold a demand SET, and the tests that
landed with it drive the *collection* and *call* folds -- `[p[0], q[1]]`,
`g(p[0], q[1])` -- where both operands run on the SAME face. A conditional
expression is the one producer where they do not: `p[0] if c else q[1]` owes

    c -> python:indexable(p)   AND   not c -> python:indexable(q)

and NOTHING else. Two obligations, two DIFFERENT faces, neither owed where its
arm does not run. `merge_demands` cannot state that law -- it unions demands
that have already been weakened -- so the law lives in `_join`, in the order
`demanded_under(formula)` / `demanded_under(not_formula)` is applied to the arms,
and it had no test. That is the gap this file closes.

WHY EVERY POSITIVE HERE HAS A DISCRIMINATING TWIN. Every way this can be wrong
still lifts, still constructs, and still produces a count that looks right:

* drop the else arm's demand           -- 1 demand, "it lifts", `q` unowed
* conjoin the two into one             -- 1 demand naming ONE formal for both
* weaken both under the same face      -- 2 demands, right count, `q` owed under `c`
* swap the faces                       -- 2 demands, right count, both backwards
* weaken neither                       -- 2 demands, both owed unconditionally,
                                          a STRONGER obligation than the source states
* weaken twice                         -- `c -> (c -> ...)`, a different `demand_cid`

Each of those satisfies "the conditional expression lifted" and is a certified
lie about what the caller owes. So each has its own arm below, and the arms
assert the FORMULA, not the count: a count-based suite passes four of the six.

EXACT CARDINALITY EVERYWHERE. Never `>= 1`. A join that leaked a third demand
and a join that dropped one are the same class of defect from opposite sides.
"""

from __future__ import annotations

import tempfile

from sugar_lift_py_tests.caller_parameter_contract import (
    ContractConditionalConstructionV1,
)
from sugar_lift_py_tests.floor.guarded_value import GuardedValue
from sugar_lift_py_tests.floor.universe_value import UniverseValue
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile


def _out(source: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(source)
        path = f.name
    return next(SourceFile(path_source(path)).functions()).sugar().desugar()


def _entries(out) -> tuple[ContractConditionalConstructionV1, ...]:
    """The contract rows the function's block record enrolled.

    Read off the RECORD, never off the in-flight carrier: the record is what
    `link_unit_projection` hands the linker, so a demand that never lands here
    is never discharged. `contribution` has already split the in-flight set into
    one row per demand by the time it reaches this point, which is the wire law
    `test_every_projected_row_states_exactly_one_demand` states; the assertions
    below therefore read the union across rows, and pin the split itself.
    """
    assert isinstance(out, Complete), out
    assert isinstance(out.value, UniverseValue), out.value
    return tuple(
        row
        for row in out.value.record.statements
        if isinstance(row, ContractConditionalConstructionV1)
    )


def _demands(out) -> tuple:
    return tuple(demand for entry in _entries(out) for demand in entry.demands)


# -- reading the demand's own testimony, never a lexical name ---------------


def _obligation(formula):
    """`(antecedent, consequent)` for a weakened demand, `(None, formula)` raw.

    A demand weakened onto a face IS an implication: `demanded_under` builds
    `implies(face, obligation)`. Anything else is an UNWEAKENED demand -- owed
    unconditionally on a face that may never run -- and the arms below say so
    by name rather than by a count that would not move.
    """
    if getattr(formula, "kind", None) == "implies":
        antecedent, consequent = formula.operands
        return antecedent, consequent
    return None, formula


def _face_polarity(antecedent):
    """`True` for the positive face, `False` for the negated one, `None` if neither.

    The guard here is the test's TRUTHINESS (`py.truthy(c)`), so the two faces
    are that atom and its `not`. Reading polarity structurally is what makes the
    swapped-faces arm below able to fire: a test that only checked "there is an
    antecedent" passes on a join that assigned both arms backwards.
    """
    if getattr(antecedent, "kind", None) == "not":
        (inner,) = antecedent.operands
        return False if getattr(inner, "name", None) == "py.truthy" else None
    return True if getattr(antecedent, "name", None) == "py.truthy" else None


def _demanded_formal_name(consequent):
    """The formal the obligation is ABOUT, read off the demanded formula's argument."""
    (arg,) = consequent.args
    return arg.name


def _by_formal(out) -> dict[str, tuple]:
    """`{formal name: (face polarity, antecedent, consequent)}`, one entry per demand.

    Keyed by the formal the demand names -- not by arrival order -- because
    arrival order is not a fact about the source (`merge_demands` orders by
    content address). Keying by position would make a join that swapped the two
    arms pass.
    """
    out_map: dict[str, tuple] = {}
    for demand in _demands(out):
        antecedent, consequent = _obligation(demand.demanded_formula)
        name = _demanded_formal_name(consequent)
        assert name not in out_map, f"two demands name the same formal: {name}"
        out_map[name] = (_face_polarity(antecedent), antecedent, consequent)
    return out_map


BOTH_ARMS = "def f(p, q, c):\n return p[0] if c else q[1]\n"
THEN_ONLY = "def f(p, c):\n return p[0] if c else 1\n"
ELSE_ONLY = "def f(p, c):\n return 1 if c else p[0]\n"
SAME_FORMAL = "def f(p, c):\n return p[0] if c else p[0]\n"


# --------------------------------------------------------------------------
# POSITIVE: the join constructs, and it constructs BOTH obligations
# --------------------------------------------------------------------------


def test_both_arms_pending_constructs_instead_of_panicking():
    """POSITIVE. The 46 `IfExpSugar._join` rows on the pandas board were this.

    Every one of the 46 said the same sentence -- "both conditional-expression
    arms enrolled a parameter contract demand ... widen
    ContractConditionalConstructionV1 to carry a demand SET". One owner, one
    value category, one missing law. It constructs now, and no arm of this file
    is allowed to be satisfied by construction alone.
    """
    out = _out(BOTH_ARMS)

    assert isinstance(out, Complete)
    assert len(_demands(out)) == 2


def test_each_arm_owes_its_own_formal():
    """POSITIVE. Two DISTINCT formals: `p` from the then arm, `q` from the else arm."""
    assert set(_by_formal(_out(BOTH_ARMS))) == {"p", "q"}


# --------------------------------------------------------------------------
# THE FACE LAW: which face each obligation is owed on
# --------------------------------------------------------------------------


def test_the_then_arms_obligation_is_owed_only_where_the_then_arm_runs():
    """THE LAW, then half. `p[0] if c else q[1]` owes `c -> python:indexable(p)`.

    Not `python:indexable(p)`. A caller that always passes a falsy `c` never
    evaluates `p[0]` and owes nothing about `p`.
    """
    polarity, antecedent, consequent = _by_formal(_out(BOTH_ARMS))["p"]

    assert antecedent is not None, (
        "the then arm's demand is UNWEAKENED: `python:indexable(p)` is owed "
        "unconditionally, which is a stronger obligation than the source states"
    )
    assert polarity is True
    assert consequent.name == "python:indexable"


def test_the_else_arms_obligation_is_owed_only_where_the_else_arm_runs():
    """THE LAW, else half. `not c -> python:indexable(q)`."""
    polarity, antecedent, consequent = _by_formal(_out(BOTH_ARMS))["q"]

    assert antecedent is not None, (
        "the else arm's demand is UNWEAKENED: `python:indexable(q)` is owed "
        "unconditionally, which is a stronger obligation than the source states"
    )
    assert polarity is False
    assert consequent.name == "python:indexable"


def test_the_two_faces_are_opposite_and_not_swapped():
    """DISCRIMINATING, and it is the arm the count cannot reach.

    Weakening BOTH arms under `formula`, or assigning the two faces backwards,
    yields two demands, two formals, two implications, and every count in this
    file still right -- while `q` is owed exactly where `q[1]` never runs. The
    polarity pair is the only reading that separates those worlds.
    """
    faces = _by_formal(_out(BOTH_ARMS))

    assert (faces["p"][0], faces["q"][0]) == (True, False), (
        "the arms' faces are not the partition: the then arm must be owed under "
        "the guard and the else arm under its negation (IfExpSugar._join)"
    )


def test_neither_obligation_is_weakened_twice():
    """DISCRIMINATING. `c -> (c -> indexable(p))` is a DIFFERENT `demand_cid`.

    `demanded_under` weakens the demand WITHOUT guarding the value, precisely
    because the join guards the value itself. A caller that also routed the
    entry through `guarded` would weaken a second time: same count, same
    formals, same polarities, and a content address the linker's resolution
    table does not have.
    """
    for name, (_polarity, _antecedent, consequent) in _by_formal(_out(BOTH_ARMS)).items():
        assert getattr(consequent, "kind", None) != "implies", (
            f"the {name} obligation is nested `face -> (face -> ...)`: it was "
            "weakened twice, and its demand_cid is not the one that was minted"
        )


def test_the_two_obligations_are_not_conjoined_into_one():
    """DISCRIMINATING. Two demands must stay TWO, each owning its own formal.

    Fusing the formulas keeps both obligations visible and still lies: the
    surviving demand names ONE `formal_coordinate_cid`, so half the obligation
    is attributed to a formal that does not own it. It is a fabricated fact, and
    a demand count of 1-with-both-formulas would satisfy any test that only
    looked for `indexable(q)` somewhere in the output.
    """
    out = _out(BOTH_ARMS)

    assert len({d.formal_coordinate_cid for d in _demands(out)}) == 2
    assert len({d.demand_cid for d in _demands(out)}) == 2


# --------------------------------------------------------------------------
# EXACT CARDINALITY: one arm dropped and one arm leaked are the same defect
# --------------------------------------------------------------------------


def test_the_join_owes_exactly_two_obligations_not_one_and_not_four():
    """DISCRIMINATING, from both sides.

    ONE means an arm's obligation was dropped -- `q` stands with nothing owed by
    anyone. FOUR means each arm's demand was weakened and unioned on both faces,
    minting rows the linker must discharge twice. Neither is a smaller answer.
    """
    assert len(_demands(_out(BOTH_ARMS))) == 2


def test_every_projected_row_states_exactly_one_demand():
    """THE WIRE LAW, restated for this producer.

    The set exists only in flight. `contribution` splits it before anything is
    projected, so the link unit and the Rust linker still see one demand per
    row. This owner is the one that mints a two-demand entry, so it is the one
    that can break the wire shape.
    """
    for entry in _entries(_out(BOTH_ARMS)):
        assert len(entry.contribution()) == 1


# --------------------------------------------------------------------------
# THE ONE-ARM CASES: the widening must not have changed them
# --------------------------------------------------------------------------


def test_a_then_only_arm_still_owes_exactly_one_obligation_on_the_positive_face():
    """DISCRIMINATING. The single-pending path is a DIFFERENT branch of `_join`.

    `p[0] if c else 1` never reaches the both-pending branch. A widening that
    routed every conditional through the two-arm join would give this source a
    second, empty-or-duplicated obligation and still lift.
    """
    faces = _by_formal(_out(THEN_ONLY))

    assert set(faces) == {"p"}
    assert faces["p"][0] is True


def test_an_else_only_arm_still_owes_exactly_one_obligation_on_the_negated_face():
    """DISCRIMINATING. The mirror branch, and the one a `formula`/`not_formula`
    copy-paste gets backwards without changing any count."""
    faces = _by_formal(_out(ELSE_ONLY))

    assert set(faces) == {"p"}
    assert faces["p"][0] is False


def test_the_same_formal_on_both_arms_owes_two_obligations_on_one_formal():
    """DISCRIMINATING, and it cuts the other way than it first looks.

    `p[0] if c else p[0]` is TWO obligations, not one. `demand_cid` addresses
    `operation_site` and `candidate_cid` too, and the two `p[0]` occupy
    different source coordinates, so the linker resolves them independently --
    the same ruling the collection fold already carries. Collapsing them because
    the formal matches would discharge one site with the other's resolution.
    They are also on OPPOSITE faces, which is the part only this owner has.
    """
    out = _out(SAME_FORMAL)
    demands = _demands(out)

    assert len({d.demand_cid for d in demands}) == 2
    assert len({d.formal_coordinate_cid for d in demands}) == 1
    polarities = {_face_polarity(_obligation(d.demanded_formula)[0]) for d in demands}
    assert polarities == {True, False}


# --------------------------------------------------------------------------
# VALUE CONSERVATION: the demand rode back out, the value was not disturbed
# --------------------------------------------------------------------------


def _subscripted_formal(arm) -> str:
    """The formal a `p[0]`-shaped arm value reads, off the value's own testimony."""
    (receiver, _index) = arm.arg_values
    return receiver.term.name


def test_the_joined_value_fuses_each_arms_own_value_under_the_test():
    """POSITIVE for the value, DISCRIMINATING about WHICH value each face holds.

    The demand machinery runs beside the value, not through it: `demanded_under`
    weakens the obligation and leaves the carried value alone, because the join
    guards the value itself. So the answer is the ordinary fused `GuardedValue`
    -- `when_true` is the THEN arm's value and `when_false` is the ELSE arm's --
    and the arms are told apart by the formal each one reads, not by position.

    This is the arm that fires when the two-arm join collapses onto one arm's
    value while every demand assertion above still passes: two obligations
    correctly weakened onto two faces, and a returned value that answers `p[0]`
    on both. The demands are not evidence for the value; they are a separate
    conservation, and this reads the other one.

    MEASURED SCOPE, stated because a stronger claim was tempting and is false:
    routing the carrier through `guarded` instead of `demanded_under` here --
    the double-guard this join's comment warns about -- produces a
    BYTE-IDENTICAL value for this shape (verified: the only difference between
    the two runs' value reprs was the tempfile path). So no arm in this file
    detects that substitution, and none claims to. What is pinned is that the
    fused value holds each arm's own value under the test's truthiness.
    """
    out = _out(BOTH_ARMS)
    guarded = _entries(out)[0].value.value

    assert isinstance(guarded, GuardedValue)
    assert guarded.guard.name == "py.truthy"
    assert _subscripted_formal(guarded.when_true) == "p"
    assert _subscripted_formal(guarded.when_false) == "q"


def test_both_rows_carry_the_same_joined_value():
    """DISCRIMINATING. The set was split for the wire, not forked into two values.

    `contribution` splits one entry's demand SET into one row per demand. If the
    split forked the VALUE too, the record would enrol the conditional twice and
    the resumed projection would state the return twice. Compared by value, not
    by `id`: two structurally equal values built twice are still one answer, and
    an identity check would call that a defect.
    """
    values = [entry.value for entry in _entries(_out(BOTH_ARMS))]

    assert len(values) == 2
    assert values[0] == values[1]
