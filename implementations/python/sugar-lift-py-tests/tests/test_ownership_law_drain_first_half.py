from sugar_lift_py_tests.idd.sugar_witness_instruments import (
    evaluate_seed_witnesses,
)
from sugar_lift_py_tests.sugar.dict_literal_sugar import DictLiteralSugar
from sugar_lift_py_tests.sugar.getattr_builtin_sugar import GetattrBuiltinSugar
from sugar_lift_py_tests.sugar.witnesses import SugarRedEffectWitnessPair


def _typed_red_witness(owner, name: str) -> SugarRedEffectWitnessPair:
    witnesses = owner.witnesses()
    candidates = witnesses if isinstance(witnesses, tuple) else (witnesses,)
    witness = next(pair for pair in candidates if pair.name == name)
    assert isinstance(witness, SugarRedEffectWitnessPair)
    return witness


def test_first_half_runtime_effects_enroll_refuting_bad_twins(tmp_path) -> None:
    witnesses = (
        _typed_red_witness(DictLiteralSugar, "dict_unpack_runtime_effect"),
        _typed_red_witness(GetattrBuiltinSugar, "getattr_runtime_effect"),
    )

    report = evaluate_seed_witnesses(
        witnesses,
        tmp_path / "ownership-first-half",
    )

    assert report.is_zero
