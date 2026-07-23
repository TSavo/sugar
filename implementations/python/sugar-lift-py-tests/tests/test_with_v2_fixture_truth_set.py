from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "with_v2_laws"

AUTHORITY_EXPECTED = {
    "authority_doorb.py": True, "authority_alias.py": True,
    "authority_nested.py": True, "authority_rpc.py": True,
    "authority_legitimate.py": False, "authority_data.py": False,
}
ENROLLMENT_EXPECTED = {
    "enrollment_direct.py": True, "enrollment_alias.py": True,
    "enrollment_nested.py": True, "enrollment_renamed.py": True,
    "enrollment_rpc.py": True, "enrollment_ordinary_dict.py": False,
    "enrollment_ordinary_get.py": False, "enrollment_string_dict.py": False,
}

def test_truth_set_is_complete_and_isolated():
    assert set(AUTHORITY_EXPECTED) | set(ENROLLMENT_EXPECTED) == {p.name for p in FIXTURES.glob("*.py") if p.name != "__init__.py"}
    assert sum(AUTHORITY_EXPECTED.values()) == 4
    assert sum(ENROLLMENT_EXPECTED.values()) == 5
    assert sum(not v for v in AUTHORITY_EXPECTED.values()) == 2
    assert sum(not v for v in ENROLLMENT_EXPECTED.values()) == 3
