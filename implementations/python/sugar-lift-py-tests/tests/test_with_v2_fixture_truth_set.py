from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "with_v2_laws"

AUTHORITY_EXPECTED = {
    "authority_doorb.py": True, "authority_alias.py": True,
    "authority_nested.py": True, "authority_rpc.py": True,
    "authority_cross_file.py": True, "authority_helper.py": True,
    "authority_opaque.py": True, "authority_legitimate.py": False,
    "authority_data.py": False, "authority_zero.py": False,
}
ENROLLMENT_EXPECTED = {
    "enrollment_direct.py": True, "enrollment_alias.py": True,
    "enrollment_nested.py": True, "enrollment_renamed.py": True,
    "enrollment_cross_file.py": True, "enrollment_helper.py": True,
    "enrollment_rpc.py": True, "enrollment_ordinary_dict.py": False,
    "enrollment_ordinary_get.py": False, "enrollment_string_dict.py": False,
}

def test_truth_set_is_complete_and_isolated():
    assert set(AUTHORITY_EXPECTED) | set(ENROLLMENT_EXPECTED) == {p.name for p in FIXTURES.glob("*.py") if p.name != "__init__.py"}
    assert sum(AUTHORITY_EXPECTED.values()) == 7
    assert sum(ENROLLMENT_EXPECTED.values()) == 7
    assert sum(not v for v in AUTHORITY_EXPECTED.values()) == 3
    assert sum(not v for v in ENROLLMENT_EXPECTED.values()) == 3

def run_truth_set(detector):
    """Run a future detector and report FN/FP without implementing it here."""
    results = {}
    for name, expected in {**AUTHORITY_EXPECTED, **ENROLLMENT_EXPECTED}.items():
        results[name] = bool(detector(FIXTURES / name))
    positives = {**AUTHORITY_EXPECTED, **ENROLLMENT_EXPECTED}
    false_negatives = sum(expected and not results[name] for name, expected in positives.items())
    false_positives = sum((not expected) and results[name] for name, expected in positives.items())
    return {"false_negatives": false_negatives, "false_positives": false_positives, "results": results}
