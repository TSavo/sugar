"""A guarded occurrence does not settle a no-warning contract, in either direction.

``675c5de7b`` (#6476) routed ``assert_produces_warning(None)`` on completed faces
and decided the contract with a bare ``any(isinstance(entry,
WarningObservationValue) ...)``.  That reads a CONDITIONAL occurrence as a
definite assertion failure: the producer says the warning happens WHEN a branch
guard holds, and the boundary restates it as "the warning happens".  It is the
mirror of the arm the matching-category router already refuses by name
(``warning occurrence is reached only under a branch guard``) -- same defect,
opposite direction, same file.

The reproducer is real and its whole point is that the guard does NOT hold.
``pandas/core/methods/to_dict.py:148-153`` in the pinned 3.0.3 corpus::

    if orient != "tight" and not df.columns.is_unique:
        warnings.warn(
            "DataFrame columns are not unique, some columns will be omitted.",
            UserWarning,
            stacklevel=find_stack_level(),
        )

and ``pandas/tests/frame/methods/test_to_dict.py:518-523`` (GH#58281)::

    def test_to_dict_tight_no_warning_with_duplicate_column(self):
        df = DataFrame([[1, 2], [3, 4], [5, 6]], columns=["A", "A"])
        with tm.assert_produces_warning(None):
            result = df.to_dict(orient="tight")

The columns really are duplicated, so the second conjunct holds; the assertion
passes only because ``orient == "tight"`` makes the first one false.  Nothing
lexical decides that, so the honest static answer is undecided -- not a met
assertion, and emphatically not a failed one.

Corpus authenticated before these sites were selected:
``corpus_manifest_cid`` over ``SourceTree(pandas_root).paths()`` reproduces
``sha256:a223a4499d0909f22190748b4aca9144e35a58fec31e84cb924e2c25fd3c03d0``
over 1421 files.  ``assert_produces_warning(None)`` is 101 with-sites across 61
files by grep and by an independent AST walk.  15 of those 101 blocks call a
function that warns under a guard.

No tooth here reads a wall clock, and no expected value is supplied by the test
that then asserts it: each arm is lifted from source text and the discriminating
value is the guard the source itself writes.
"""

from __future__ import annotations

import pathlib
import tempfile
from types import SimpleNamespace

import pytest

from sugar_lift_py_tests.context_manager_contract import (
    CallParameterV1,
    EffectBoundarySemanticsV1,
    ExpectsModeV1,
    FormalArgumentProjectionV1,
    ImportSignatureV2,
    NoDefaultV1,
    NoMessagePatternV1,
    PositionalOrKeywordV1,
    WarningEffectKindV1,
    WarningObservationBindingV1,
)
from sugar_lift_py_tests.effect import ExpectationNotMetEffect
from sugar_lift_py_tests.floor import BlockValue, CallSiteValue, NoneValue
from sugar_lift_py_tests.floor.warning_observation_value import WarningObservationValue
from sugar_lift_py_tests.ir import PrimitiveSort, ctor
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.outcome.exit_set import Completed, Halted
from sugar_lift_py_tests.sugar.function_universe_sugar import reduce_block_to_exitset
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import WithEffectBoundarySugar
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile

# The `to_dict` occurrence, transcribed in shape: a two-conjunct guard around an
# explicit-category warn. The category is spelled here so the producer can
# authenticate it -- that is what makes this an occurrence rather than an
# unresolved call, and it is what puts the entry in front of the boundary at all.
GUARDED_TO_DICT_SHAPE = """import warnings


def to_dict(df, orient):
    if orient != "tight" and not df.columns.is_unique:
        warnings.warn(
            "DataFrame columns are not unique, some columns will be omitted.",
            UserWarning,
            stacklevel=2,
        )
    return df
"""

# The same occurrence with the guard removed: the source now states the warning
# unconditionally, so the no-warning contract really is violated.
UNCONDITIONAL_SHAPE = """import warnings


def to_dict(df, orient):
    warnings.warn(
        "DataFrame columns are not unique, some columns will be omitted.",
        UserWarning,
        stacklevel=2,
    )
    return df
"""

# A body that warns nowhere: the contract is met, and it must still be met after
# the guard arm exists, or the fix would have bought the refusal by breaking the
# truthful case.
NO_OCCURRENCE_SHAPE = """def to_dict(df, orient):
    result = df
    return result
"""


def _entries(source: str, stem: str):
    """Every record entry of every completed face, from real lifted source."""
    directory = pathlib.Path(tempfile.mkdtemp())
    path = directory / f"{stem}.py"
    path.write_text(source, encoding="utf-8")
    function = next(SourceFile(path_source(str(path))).functions())
    exits = reduce_block_to_exitset(function.sugar().statements, None)
    return tuple(
        entry for face in exits.exits for entry in getattr(face.value, "entries", ())
    )


class _Fixed(Sugar):
    def __init__(self, outcome):
        self.outcome = outcome

    def desugar(self, ctx=None):
        del ctx
        return self.outcome

    @classmethod
    def witnesses(cls):
        return ()


class _Record(Sugar):
    """A completed face carrying exactly the entries the producer built."""

    def __init__(self, entries):
        self.entries = entries

    def desugar(self, ctx=None):
        del ctx
        return Complete(BlockValue(self.entries))

    @classmethod
    def witnesses(cls):
        return ()


SEMANTICS = EffectBoundarySemanticsV1(
    ExpectsModeV1(),
    WarningEffectKindV1(),
    FormalArgumentProjectionV1(0),
    NoMessagePatternV1(),
    WarningObservationBindingV1(),
)


def _no_warning_boundary(entries):
    """`assert_produces_warning(None)`: the expected operand is exactly None."""
    manager_value = CallSiteValue(
        target_name="scope",
        arg_values=(NoneValue(),),
        parameters=("expected",),
        term=ctor("call", []),
        body=None,
    )
    signature = ImportSignatureV2(
        (
            CallParameterV1(
                "expected",
                PrimitiveSort("Value"),
                PositionalOrKeywordV1(),
                True,
                NoDefaultV1(),
            ),
        )
    )
    return WithEffectBoundarySugar(
        manager=_Fixed(Complete(manager_value)),
        body=(_Record(entries),),
        semantics=SEMANTICS,
        contract_ref=SimpleNamespace(import_signature=signature),
        context_manager_edge=None,
        site=None,
    )


def test_the_guarded_to_dict_occurrence_carries_its_guard():
    """Precondition, asserted rather than assumed.

    If the producer stopped recording guards this file would still be green
    without testing anything -- the boundary would simply never see a guarded
    entry. Pin the shape the rest of the module depends on.
    """
    observations = [
        entry
        for entry in _entries(GUARDED_TO_DICT_SHAPE, "guarded")
        if isinstance(entry, WarningObservationValue)
    ]
    assert len(observations) == 1
    assert observations[0].guards != ()


def test_a_guarded_occurrence_leaves_a_no_warning_contract_undecided():
    """The reproducer arm. Not met, and NOT failed."""
    entries = _entries(GUARDED_TO_DICT_SHAPE, "guarded")
    with pytest.raises(SugarNotWritten) as raised:
        _no_warning_boundary(entries).desugar()
    assert raised.value.owner == "WithEffectBoundarySugar.warning_observation"
    assert raised.value.observed == (
        "warning occurrence is reached only under a branch guard"
    )


def test_an_unconditional_occurrence_still_fails_the_contract():
    """The lying twin: drop the guard and the violation becomes real.

    This is what stops the fix from being "refuse whenever a warning appears".
    The two sources differ only by the `if`, and they must route differently.
    """
    entries = _entries(UNCONDITIONAL_SHAPE, "unconditional")
    routed = _no_warning_boundary(entries).desugar()
    assert len(routed.exits) == 1
    face = routed.exits[0]
    assert isinstance(face, Halted)
    assert isinstance(face.effect, ExpectationNotMetEffect)


def test_a_body_that_never_warns_still_meets_the_contract():
    """The truthful twin, unchanged by the guard arm."""
    entries = _entries(NO_OCCURRENCE_SHAPE, "clean")
    routed = _no_warning_boundary(entries).desugar()
    assert len(routed.exits) == 1
    assert isinstance(routed.exits[0], Completed)


def test_the_guard_is_what_moves_the_outcome():
    """The three arms together, stated as one discrimination.

    Guarded, unguarded and absent are three distinct outcomes from sources that
    differ only in whether -- and how -- the occurrence is reached. A mechanism
    that collapsed any two of them would pass some arm above on its own.
    """
    outcomes = {}
    for label, source in (
        ("guarded", GUARDED_TO_DICT_SHAPE),
        ("unconditional", UNCONDITIONAL_SHAPE),
        ("absent", NO_OCCURRENCE_SHAPE),
    ):
        entries = _entries(source, label)
        try:
            routed = _no_warning_boundary(entries).desugar()
        except SugarNotWritten as refusal:
            outcomes[label] = f"refused:{refusal.observed}"
        else:
            outcomes[label] = type(routed.exits[0]).__name__

    assert outcomes == {
        "guarded": "refused:warning occurrence is reached only under a branch guard",
        "unconditional": "Halted",
        "absent": "Completed",
    }


def test_the_unresolved_bucket_enumerates_its_members_here_too():
    """A bare `warnings.warn(msg)` has no authenticated category, so it stays an
    unresolved producer -- and the no-warning router must NAME it rather than
    read the empty observation set as absence. Presence, never absence: a
    producer that was never wired leaves the same empty set."""
    source = 'import warnings\n\n\ndef f():\n    warnings.warn("m", stacklevel=2)\n'
    entries = _entries(source, "bare")
    assert not any(isinstance(entry, WarningObservationValue) for entry in entries)
    with pytest.raises(SugarNotWritten) as raised:
        _no_warning_boundary(entries).desugar()
    assert raised.value.observed == "completed face has unresolved warning producers"
    members = raised.value.unresolved_warning_producers
    assert any(member.endswith(":5") for member in members), members
