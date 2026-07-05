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


if __name__ == "__main__":
    unittest.main()
