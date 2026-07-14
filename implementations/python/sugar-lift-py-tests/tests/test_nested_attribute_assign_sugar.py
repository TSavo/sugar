"""A three-part dotted assignment binds its full source-stated address."""

from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys

from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import ReturnValue, SymbolicValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.lift_rpc import audit_lift_file
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar


def _statement(source: str) -> SourceFragment:
    return SourceFragment.from_node(ast.parse(source).body[0], "vendor.py")


def test_nested_attribute_assignment_rebinds_full_dotted_path() -> None:
    block = compose_block(
        "    result.flags.writeable = False\n" "    return result.flags.writeable\n",
        binds={"result": SymbolicValue(make_var("result"))},
    )

    returned = next(
        entry for entry in block.statements if isinstance(entry, ReturnValue)
    )
    assert isinstance(returned.value, FalseBoolLiteralSugar)


def test_deep_attribute_assignment_rebinds_full_dotted_path() -> None:
    block = compose_block(
        "    result.options.mode.writeable = False\n"
        "    return result.options.mode.writeable\n",
        binds={"result": SymbolicValue(make_var("result"))},
    )

    returned = next(
        entry for entry in block.statements if isinstance(entry, ReturnValue)
    )
    assert isinstance(returned.value, FalseBoolLiteralSugar)


def test_call_and_subscript_receiver_targets_have_selected_owner() -> None:
    for source in (
        "factory().field = 1",
        "items[0].field = 1",
    ):
        built = build_node(
            ast.parse(source).body[0],
            filename="vendor.py",
            role=SugarRole.STATEMENT,
        )
        assert type(built.sugar).__name__ == "SelectedAttributeAssignSugar"


def test_owner_is_name_rooted_dotted_attribute_target() -> None:
    catalog = default_catalog()
    assert [
        candidate.name
        for candidate in catalog.candidates_for(
            SugarRole.STATEMENT,
            _statement("result.flags.writeable = False"),
        )
    ] == ["NestedAttributeAssignSugar"]
    assert [
        candidate.name
        for candidate in catalog.candidates_for(
            SugarRole.STATEMENT,
            _statement("result.options.mode.writeable = False"),
        )
    ] == ["NestedAttributeAssignSugar"]
    assert "NestedAttributeAssignSugar" not in [
        candidate.name
        for candidate in catalog.candidates_for(
            SugarRole.STATEMENT,
            _statement("result.writeable = False"),
        )
    ]


def test_deep_attribute_assignment_discriminator_runs_both_process_arms() -> None:
    tests_dir = Path(__file__).resolve().parent
    src_dir = tests_dir.parent / "src"
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(tests_dir), str(src_dir))),
    }

    def run(expected: bool) -> subprocess.CompletedProcess[str]:
        script = f"""\
from factory_reduce import compose_block
from sugar_lift_py_tests.floor import ReturnValue, SymbolicValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

block = compose_block(
    "    result.options.mode.writeable = False\\n"
    "    return result.options.mode.writeable\\n",
    binds={{"result": SymbolicValue(make_var("result"))}},
)
returned = next(x for x in block.statements if isinstance(x, ReturnValue))
assert isinstance(returned.value, {"FalseBoolLiteralSugar" if expected is False else "TrueBoolLiteralSugar"})
"""
        return subprocess.run(
            [sys.executable, "-c", script],
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )

    truthful = run(False)
    lying = run(True)
    assert truthful.returncode == 0, truthful.stderr
    assert lying.returncode == 1, lying.stderr


def test_real_array_file_shape_has_no_assign_factory_panic() -> None:
    source = """
def lock_result(result):
    result.flags.writeable = False
    return result.flags.writeable
"""
    recovered = audit_lift_file(source, "core/arrays/base.py", recover_panics=True)
    assert all(panic.gap["observed"] != "Assign" for panic in recovered.panics)
