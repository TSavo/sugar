from pathlib import Path

from with_v2_law_detector import ModuleGraph, analyze_consumer_enrollment, analyze_single_authority


FIXTURES = Path(__file__).parent / "fixtures" / "with_v2_laws"

AUTHORITY_CASES = {
    "authority_doorb": ("authority_doorb.py",),
    "authority_alias": ("authority_alias.py", "provider_authority.py"),
    "authority_nested": ("authority_nested.py",),
    "authority_rpc": ("authority_rpc.py",),
    "authority_cross_file": ("authority_cross_file.py", "authority_helper.py"),
    "authority_opaque": ("authority_opaque.py",),
    "authority_registered": ("authority_registered.py",),
    "authority_legitimate": ("authority_legitimate.py",),
    "authority_data": ("authority_data.py",),
    "authority_zero": ("authority_zero.py", "authority_helper.py"),
    "authority_gap": ("authority_gap.py",),
    "authority_rpc_data": ("authority_rpc_data.py",),
}

ENROLLMENT_CASES = {
    "enrollment_direct": ("enrollment_direct.py",),
    "enrollment_alias": ("enrollment_alias.py", "provider_catalog.py"),
    "enrollment_nested": ("enrollment_nested.py",),
    "enrollment_renamed": ("enrollment_renamed.py",),
    "enrollment_cross_file": ("enrollment_cross_file.py", "enrollment_helper.py"),
    "enrollment_rpc": ("enrollment_rpc.py",),
    "enrollment_rpc_semantics": ("enrollment_rpc_semantics.py",),
    "enrollment_opaque": ("enrollment_opaque.py",),
    "enrollment_generic_rename": ("enrollment_generic_rename.py",),
    "enrollment_boundary_b": ("enrollment_boundary_b.py",),
    "enrollment_ordinary_dict": ("enrollment_ordinary_dict.py",),
    "enrollment_ordinary_get": ("enrollment_ordinary_get.py",),
    "enrollment_string_dict": ("enrollment_string_dict.py",),
    "enrollment_semantics_unreachable": ("enrollment_semantics_unreachable.py",),
}


def graph(names: tuple[str, ...]) -> ModuleGraph:
    return ModuleGraph.from_paths([FIXTURES / name for name in names])


def test_single_authority_planted_detector_cases():
    expected = {
        "authority_doorb": "secondary-admission-authority",
        "authority_alias": "secondary-admission-authority",
        "authority_nested": "secondary-admission-authority",
        "authority_rpc": "secondary-admission-authority",
        "authority_cross_file": "secondary-admission-authority",
        "authority_opaque": "opaque-admission-flow",
        "authority_registered": "secondary-admission-authority",
    }
    for case, reason in expected.items():
        rows = analyze_single_authority(graph(AUTHORITY_CASES[case]))
        assert len(rows) == 1, (case, rows)
        assert rows[0].reason == reason
    for case in ("authority_legitimate", "authority_data", "authority_zero", "authority_gap", "authority_rpc_data"):
        assert analyze_single_authority(graph(AUTHORITY_CASES[case])) == (), case


def test_no_consumer_enrollment_planted_detector_cases():
    for case in (
        "enrollment_direct",
        "enrollment_alias",
        "enrollment_nested",
        "enrollment_renamed",
        "enrollment_cross_file",
        "enrollment_rpc",
        "enrollment_rpc_semantics",
        "enrollment_opaque",
        "enrollment_generic_rename",
        "enrollment_boundary_b",
    ):
        rows = analyze_consumer_enrollment(graph(ENROLLMENT_CASES[case]))
        assert len(rows) == 1, (case, rows)
        assert rows[0].reason in {
            "consumer-spelling-enrollment",
            "consumer-enrollment-rpc-lane",
            "opaque-consumer-enrollment-flow",
        }
    for case in (
        "enrollment_ordinary_dict",
        "enrollment_ordinary_get",
        "enrollment_string_dict",
        "enrollment_semantics_unreachable",
    ):
        assert analyze_consumer_enrollment(graph(ENROLLMENT_CASES[case])) == (), case


def test_truth_set_reports_zero_false_negatives_and_false_positives():
    verdicts = {}
    for case, names in AUTHORITY_CASES.items():
        verdicts[case] = bool(analyze_single_authority(graph(names)))
    for case, names in ENROLLMENT_CASES.items():
        verdicts[case] = bool(analyze_consumer_enrollment(graph(names)))
    expected = {
        **{name: name not in {"authority_legitimate", "authority_data", "authority_zero", "authority_gap", "authority_rpc_data"} for name in AUTHORITY_CASES},
        **{name: name not in {"enrollment_ordinary_dict", "enrollment_ordinary_get", "enrollment_string_dict", "enrollment_semantics_unreachable"} for name in ENROLLMENT_CASES},
    }
    false_negatives = sum(expected[name] and not verdicts[name] for name in expected)
    false_positives = sum(not expected[name] and verdicts[name] for name in expected)
    assert false_negatives == 0
    assert false_positives == 0
