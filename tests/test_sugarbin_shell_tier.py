"""Executable teeth for the nine-contract sugarbin shell tier."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "sugarbin_shell_tier.py"
EXPECTED_BATCHES = {
    "execution": [
        "tests/sugarbin_local_exec.sh",
        "tests/sugarbin_bx_exec.sh",
        "tests/sugarbin_docker_exec.sh",
    ],
    "guards": [
        "tests/sugarbin_mount_proof_guard.sh",
        "tests/sugarbin_docker_daemon_guard.sh",
        "tests/sugarbin_wrapper_compat.sh",
    ],
    "artifacts": [
        "tests/sugarbin_artifact_manifest.sh",
        "tests/sugarbin_build_identity_target.sh",
        "tests/sugarbin_build_root_identity.sh",
    ],
}
EXPECTED_ROSTER = [
    contract for batch in EXPECTED_BATCHES.values() for contract in batch
]


class SugarbinShellTierTest(unittest.TestCase):
    def run_tool(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(TOOL), *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_roster_is_exactly_three_batches_of_three(self) -> None:
        result = self.run_tool("list", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), EXPECTED_BATCHES)

    def test_init_names_every_absence_before_any_batch_runs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            reports = Path(directory)
            result = self.run_tool(
                "init", "--reports-dir", str(reports), "--commit", "abc123"
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            bodies = sorted(reports.glob("*.json"))
            self.assertEqual(len(bodies), 9)
            payloads = [json.loads(path.read_text(encoding="utf-8")) for path in bodies]
            self.assertEqual({body["contract"] for body in payloads}, set(EXPECTED_ROSTER))
            self.assertEqual({body["status"] for body in payloads}, {"unmeasured"})
            self.assertEqual({body["reason"] for body in payloads}, {"batch-not-started"})
            self.assertEqual({body["measuredCommit"] for body in payloads}, {"abc123"})

    def test_batch_records_pass_failure_and_missing_script_without_stopping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            repo = temp / "repo"
            reports = temp / "reports"
            tests = repo / "tests"
            tests.mkdir(parents=True)
            (tests / "sugarbin_local_exec.sh").write_text(
                "#!/usr/bin/env bash\nexit 0\n", encoding="utf-8"
            )
            (tests / "sugarbin_bx_exec.sh").write_text(
                "#!/usr/bin/env bash\nexit 7\n", encoding="utf-8"
            )
            initialized = self.run_tool(
                "init", "--reports-dir", str(reports), "--commit", "abc123"
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)

            result = self.run_tool(
                "run-batch",
                "execution",
                "--repo",
                str(repo),
                "--reports-dir",
                str(reports),
                "--commit",
                "abc123",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout.count("ATTEND phase=start"), 3)

            local = json.loads(
                (reports / "sugarbin_local_exec.json").read_text(encoding="utf-8")
            )
            bx = json.loads(
                (reports / "sugarbin_bx_exec.json").read_text(encoding="utf-8")
            )
            docker = json.loads(
                (reports / "sugarbin_docker_exec.json").read_text(encoding="utf-8")
            )
            self.assertEqual((local["status"], local["exitCode"]), ("completed", 0))
            self.assertEqual((bx["status"], bx["exitCode"]), ("completed", 7))
            self.assertEqual(
                (docker["status"], docker["reason"]),
                ("unmeasured", "script-missing"),
            )

    def test_audit_refuses_absence_and_accepts_exact_nine_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            reports = Path(directory) / "reports"
            receipt = Path(directory) / "receipt.json"
            initialized = self.run_tool(
                "init", "--reports-dir", str(reports), "--commit", "abc123"
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)

            absent = self.run_tool(
                "audit",
                "--reports-dir",
                str(reports),
                "--receipt",
                str(receipt),
                "--require-commit",
                "abc123",
            )
            self.assertNotEqual(absent.returncode, 0)
            self.assertIn("R_sugarbin_shell_attendance = 9", absent.stdout)
            self.assertEqual(json.loads(receipt.read_text())["passed"], 0)

            for contract in EXPECTED_ROSTER:
                path = reports / f"{Path(contract).stem}.json"
                path.write_text(
                    json.dumps(
                        {
                            "schemaVersion": 1,
                            "measurementClass": "sugarbin-shell-contract",
                            "contract": contract,
                            "measuredCommit": "abc123",
                            "status": "completed",
                            "exitCode": 0,
                            "reason": "exit-0",
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )

            complete = self.run_tool(
                "audit",
                "--reports-dir",
                str(reports),
                "--receipt",
                str(receipt),
                "--require-commit",
                "abc123",
            )
            self.assertEqual(complete.returncode, 0, complete.stderr)
            self.assertIn("R_sugarbin_shell_attendance = 0", complete.stdout)
            summary = json.loads(receipt.read_text())
            self.assertEqual(
                (summary["roster"], summary["attended"], summary["passed"]),
                (9, 9, 9),
            )
            self.assertEqual(summary.get("testElapsedSeconds"), 0.0)


if __name__ == "__main__":
    unittest.main()
