"""GUARD: every sugar is accounted for, by name, in one place.

The recurring failure mode was coverage drifting out of sight: a sugar added, or
covered only incidentally, with no single source of truth saying where its
Python->ProofIR behavior is pinned. This registry IS that source of truth. The two
checks below fail CI when:
  * a sugar module exists with no registry entry (a NEW untested sugar), or
  * a registry entry names a coverage file that no longer exists (drift), or
  * a registry entry is stale (its sugar module was removed).

So a new sugar cannot land without being registered against a real test, and the
accounting can never silently rot. Each entry names the test file(s) that pin that
sugar -- a dedicated `test_<module>.py` for the leaf reductions, or the integration
test that exercises it for the composers / builder-path sugars.
"""
from __future__ import annotations

import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUGAR_DIR = HERE.parent / "src" / "sugar_lift_py_tests" / "sugar"

# sugar module (without .py) -> test file(s) that pin its Python->ProofIR behavior.
COVERAGE: dict[str, list[str]] = {
    # block + statement composition (the suite as a composite)
    "assign_sugar": ["test_assign_sugar.py"],
    "call_sugar": ["test_call_sugar.py"],
    "aug_assign_sugar": ["test_aug_assign_sugar.py"],
    "block_sugar": ["test_block_sugar.py"],
    "comment_sugar": ["test_comment_sugar.py"],
    "if_sugar": ["test_if_sugar.py"],
    "raise_sugar": ["test_raise_sugar.py"],
    "return_sugar": ["test_return_sugar.py"],
    "primitive_literal_sugar": ["test_primitive_literal_sugar.py"],
    "string_literal_sugar": ["test_string_literal_sugar.py"],
    "name_sugar": ["test_name_sugar.py"],
    "bitwise_op_sugar": ["test_bitwise_op_sugar.py"],
    "binop_sugar": ["test_binop_sugar.py"],
    "array_literal_sugar": ["test_array_literal_sugar.py"],
    "string_subscript_sugar": ["test_string_subscript_sugar.py"],
    "ord_sugar": ["test_ord_sugar.py"],
    "isinstance_assertion_sugar": ["test_isinstance_assertion_sugar.py"],
    "call_truth_assertion_sugar": ["test_call_truth_assertion_sugar.py"],
    "identity_assertion_sugar": ["test_identity_assertion_sugar.py"],
    "not_sugar": ["test_not_sugar.py"],
    "projected_equality_assertion_sugar": [
        "test_projected_equality_assertion_sugar.py"
    ],
    "encoder_body_sugar": ["test_encoder_body_sugar.py"],
    # array-map path -- leaves + the composer
    "add_sugar": ["test_add_sugar.py"],
    "lambda_sugar": ["test_lambda_sugar.py"],
    "map_sugar": ["test_map_sugar.py"],
    "range_sugar": ["test_range_sugar.py"],
    "function_ref_sugar": ["test_function_ref_sugar.py"],
    "map_builtin_sugar": ["test_map_builtin_sugar.py"],
    "list_sugar": ["test_list_sugar.py"],
    # body / orchestration sugars -- pinned where they actually run
    "control_flow_body_sugar": ["test_control_flow_body.py"],
    # builder / materialize path -- exercised by the fluent-builder tests
    "builder_ctor_sugar": [
        "test_factory_constructs_bodies.py",
        "test_temporal_forward_rewrite.py",
    ],
    "list_literal_sugar": [
        "test_factory_constructs_bodies.py",
        "test_temporal_forward_rewrite.py",
    ],
    "to_list_sugar": [
        "test_factory_constructs_bodies.py",
        "test_temporal_forward_rewrite.py",
    ],
}


def _sugar_modules() -> set[str]:
    return {p.stem for p in SUGAR_DIR.glob("*_sugar.py")}


def _sugar_classes(module: str) -> list[str]:
    text = (SUGAR_DIR / f"{module}.py").read_text(encoding="utf-8")
    return re.findall(r"^class (\w+)", text, re.MULTILINE)


def test_registry_lists_every_sugar_exactly_once() -> None:
    modules = _sugar_modules()
    registered = set(COVERAGE)
    missing = sorted(modules - registered)
    stale = sorted(registered - modules)
    assert not missing, f"new sugar(s) with no coverage registry entry: {missing}"
    assert not stale, f"registry entries for sugars that no longer exist: {stale}"


def test_every_registered_coverage_file_exists_and_touches_the_sugar() -> None:
    for module, files in COVERAGE.items():
        assert files, f"{module}: registered with no coverage file"
        for f in files:
            assert (HERE / f).exists(), f"{module}: coverage file {f} does not exist"
        # A dedicated test file -- `test_<module>.py`, or `test_<module-sans-_sugar>.py`
        # (e.g. test_control_flow_body.py) -- is self-evidently about this sugar: it
        # drives it through the factory. Otherwise the coverage file must NAME the
        # sugar's class, so the entry can't point at an unrelated test.
        dedicated = {f"test_{module}.py"}
        if module.endswith("_sugar"):
            dedicated.add(f"test_{module[: -len('_sugar')]}.py")
        if not dedicated.intersection(files):
            blob = "".join((HERE / f).read_text(encoding="utf-8") for f in files)
            classes = _sugar_classes(module)
            assert any(re.search(rf"\b{c}\b", blob) for c in classes), (
                f"{module}: none of {files} reference its class(es) {classes}"
            )
