#!/usr/bin/env python3

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import examples_gate  # noqa: E402


class ExamplesGateComparisonTest(unittest.TestCase):
    def test_smoke_discovery_cannot_include_extended_prove_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "examples" / "demo").mkdir(parents=True)
            (root / "examples" / "demo" / "run.sh").write_text(
                "#!/usr/bin/env bash\n", encoding="utf-8"
            )
            (root / "examples" / "signup-service").mkdir(parents=True)
            (root / "examples" / "signup-service" / "prove.sh").write_text(
                "#!/usr/bin/env bash\n", encoding="utf-8"
            )

            smoke = examples_gate.discover_scripts(root, suite="smoke")
            extended = examples_gate.discover_scripts(root, suite="extended")

        self.assertEqual(smoke, ["examples/demo/run.sh"])
        self.assertEqual(extended, ["examples/signup-service/prove.sh"])

    def test_green_expectation_turning_red_is_named(self) -> None:
        expectations = {
            "version": 1,
            "examples": [
                {
                    "name": "examples/demo/run.sh",
                    "expected": "GREEN",
                    "first_seen": "test-fixture",
                    "notes": "planted green row",
                }
            ],
        }
        observed = {
            "version": 1,
            "examples": [
                {
                    "name": "examples/demo/run.sh",
                    "rc": 1,
                    "seconds": 0.01,
                    "verdict": "NAMED_RED",
                    "failure_shape": "planted-failure",
                    "failure_excerpt": "planted red output",
                    "log_path": "/tmp/planted.log",
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            expectation_path = tmp_path / "expectations.json"
            observed_path = tmp_path / "observed.json"
            expectation_path.write_text(json.dumps(expectations), encoding="utf-8")
            observed_path.write_text(json.dumps(observed), encoding="utf-8")

            rc = examples_gate.check_expectations(
                expectation_path=expectation_path,
                summary_path=observed_path,
                output=sys.stdout,
            )

        self.assertEqual(rc, 1)
        self.assertIn(
            "NEW_RED examples/demo/run.sh expected GREEN observed planted-failure",
            examples_gate.LAST_DIFF_TEXT,
        )

    def test_named_red_turning_green_requires_fixture_move(self) -> None:
        expectations = {
            "version": 1,
            "examples": [
                {
                    "name": "examples/demo/run.sh",
                    "expected": "NAMED_RED",
                    "failure_shape": "known-shape",
                    "first_seen": "test-fixture",
                    "grounds": "known failure",
                }
            ],
        }
        observed = {
            "version": 1,
            "examples": [
                {
                    "name": "examples/demo/run.sh",
                    "rc": 0,
                    "seconds": 0.01,
                    "verdict": "GREEN",
                    "failure_shape": None,
                    "failure_excerpt": "",
                    "log_path": "/tmp/planted.log",
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            expectation_path = tmp_path / "expectations.json"
            observed_path = tmp_path / "observed.json"
            expectation_path.write_text(json.dumps(expectations), encoding="utf-8")
            observed_path.write_text(json.dumps(observed), encoding="utf-8")

            rc = examples_gate.check_expectations(
                expectation_path=expectation_path,
                summary_path=observed_path,
                output=sys.stdout,
            )

        self.assertEqual(rc, 1)
        self.assertIn(
            "PROMOTED_RED examples/demo/run.sh expected known-shape observed GREEN",
            examples_gate.LAST_DIFF_TEXT,
        )


class RunnerEnvClassificationTest(unittest.TestCase):
    def test_venv_permission_denied_classifies_as_runner_env(self) -> None:
        log = "bash: /tmp/numpy-witness-venv/bin/python: Permission denied\n"
        self.assertEqual(
            examples_gate.classify_failure(log),
            "runner-env/venv-permission-denied",
        )

    def test_native_extension_mmap_failure_classifies_as_runner_env(self) -> None:
        log = (
            "ImportError: numpy.core.multiarray failed to import\n"
            "OSError: [Errno 12] cannot mmap\n"
        )
        self.assertEqual(
            examples_gate.classify_failure(log),
            "runner-env/native-extension-load-failure",
        )

    def test_missing_module_in_temp_venv_classifies_as_runner_env(self) -> None:
        log = (
            "/tmp/sklearn-witness-venv/bin/python3: "
            "ModuleNotFoundError: No module named 'sklearn'\n"
        )
        self.assertEqual(
            examples_gate.classify_failure(log),
            "runner-env/missing-module-in-temp-venv",
        )

    def test_runner_env_shadows_ambiguous_product_pattern_text(self) -> None:
        # A run.sh permission-denied failure can legitimately contain product
        # shape text (e.g. from a prior successful phase's saved output) but
        # must still classify as runner-env, never as product drift.
        log = (
            "expected PROVEN\n"
            "bash: /tmp/pandas-witness-venv/run.sh: Permission denied\n"
        )
        self.assertEqual(
            examples_gate.classify_failure(log),
            "runner-env/venv-permission-denied",
        )

    def test_product_shape_still_classifies_when_no_runner_env_signal(self) -> None:
        log = "self-check: expected PROVEN\n"
        self.assertEqual(
            examples_gate.classify_failure(log),
            "verdict-drift/expected-proven-label",
        )

    def test_is_runner_env_shape(self) -> None:
        self.assertTrue(
            examples_gate.is_runner_env_shape("runner-env/venv-permission-denied")
        )
        self.assertFalse(examples_gate.is_runner_env_shape("verdict-drift/expected-proven-label"))
        self.assertFalse(examples_gate.is_runner_env_shape(None))


class WriteExpectationsTest(unittest.TestCase):
    def test_refuses_to_write_when_a_row_is_runner_env(self) -> None:
        summary = {
            "version": 1,
            "suite": "smoke",
            "examples": [
                {
                    "name": "examples/numpy-showcase/run.sh",
                    "rc": 1,
                    "verdict": "NAMED_RED",
                    "failure_shape": "runner-env/missing-module-in-temp-venv",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            expectation_path = pathlib.Path(tmp) / "expectations.json"
            rc = examples_gate.write_expectations_from_summary(
                summary=summary,
                expectation_path=expectation_path,
                output=sys.stdout,
            )
            self.assertEqual(rc, 1)
            self.assertFalse(expectation_path.exists())

    def test_writes_expectations_when_no_runner_env_rows(self) -> None:
        summary = {
            "version": 1,
            "suite": "smoke",
            "examples": [
                {
                    "name": "examples/demo/run.sh",
                    "rc": 0,
                    "verdict": "GREEN",
                    "failure_shape": None,
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            expectation_path = pathlib.Path(tmp) / "expectations.json"
            rc = examples_gate.write_expectations_from_summary(
                summary=summary,
                expectation_path=expectation_path,
                output=sys.stdout,
            )
            self.assertEqual(rc, 0)
            written = json.loads(expectation_path.read_text(encoding="utf-8"))
            self.assertEqual(written["examples"][0]["expected"], "GREEN")


if __name__ == "__main__":
    unittest.main()
