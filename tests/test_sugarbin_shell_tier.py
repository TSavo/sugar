"""Executable teeth for the nine-contract sugarbin shell tier."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from sugar_lift_py_tests.repo_root import resolve_repo_root

ROOT = resolve_repo_root()
TOOL = ROOT / "tools" / "sugarbin_shell_tier.py"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
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
    def run_tool(
        self, *args: str, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(TOOL), *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            env=env,
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
            bodies = sorted(reports.glob("sugarbin_*.json"))
            self.assertEqual(len(bodies), 9)
            payloads = [json.loads(path.read_text(encoding="utf-8")) for path in bodies]
            self.assertEqual({body["contract"] for body in payloads}, set(EXPECTED_ROSTER))
            self.assertEqual({body["status"] for body in payloads}, {"unmeasured"})
            self.assertEqual({body["reason"] for body in payloads}, {"batch-not-started"})
            self.assertEqual({body["measuredCommit"] for body in payloads}, {"abc123"})
            setup = json.loads((reports / "setup.json").read_text(encoding="utf-8"))
            self.assertEqual(setup["status"], "unmeasured")
            self.assertEqual(setup["reason"], "preflight-not-run")

    def test_setup_preflight_refuses_all_missing_tools_as_one_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            reports = temp / "reports"
            initialized = self.run_tool(
                "init", "--reports-dir", str(reports), "--commit", "abc123"
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)

            env = os.environ.copy()
            env["PATH"] = str(temp / "empty-bin")
            refused = self.run_tool(
                "preflight",
                "--reports-dir",
                str(reports),
                "--commit",
                "abc123",
                "--require-tool",
                "b3sum",
                "--require-tool",
                "rsync",
                "--setup-outcome",
                "rust=failure",
                "--setup-outcome",
                "rsync=success",
                env=env,
            )

            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("missing required tools: b3sum, rsync", refused.stderr)
            self.assertIn("failed provisioning steps: rust", refused.stderr)
            setup = json.loads((reports / "setup.json").read_text(encoding="utf-8"))
            self.assertEqual(setup["status"], "refused")
            self.assertEqual(setup["reason"], "setup-refused")
            self.assertEqual(setup["missingTools"], ["b3sum", "rsync"])
            self.assertEqual(setup["failedSteps"], ["rust"])

            bodies = [
                json.loads(path.read_text(encoding="utf-8"))
                for path in reports.glob("sugarbin_*.json")
            ]
            self.assertEqual(len(bodies), 9)
            self.assertEqual({body["status"] for body in bodies}, {"unmeasured"})
            self.assertEqual({body["reason"] for body in bodies}, {"batch-not-started"})

            receipt = temp / "receipt.json"
            audited = self.run_tool(
                "audit",
                "--reports-dir",
                str(reports),
                "--receipt",
                str(receipt),
                "--require-commit",
                "abc123",
            )
            self.assertNotEqual(audited.returncode, 0)
            self.assertIn("setup: `refused`", audited.stdout)
            summary = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(summary["setupStatus"], "refused")
            self.assertEqual(summary["setupMissingTools"], ["b3sum", "rsync"])

    def test_setup_preflight_accepts_tools_after_successful_provisioning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            reports = temp / "reports"
            fake_bin = temp / "bin"
            fake_bin.mkdir()
            for tool in ("b3sum", "rsync"):
                path = fake_bin / tool
                path.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
                path.chmod(0o755)
            initialized = self.run_tool(
                "init", "--reports-dir", str(reports), "--commit", "abc123"
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)

            env = os.environ.copy()
            env["PATH"] = f"{fake_bin}:{env['PATH']}"
            accepted = self.run_tool(
                "preflight",
                "--reports-dir",
                str(reports),
                "--commit",
                "abc123",
                "--require-tool",
                "b3sum",
                "--require-tool",
                "rsync",
                "--setup-outcome",
                "rust=success",
                "--setup-outcome",
                "rsync=success",
                env=env,
            )

            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            self.assertIn("setup ready: b3sum, rsync", accepted.stdout)
            setup = json.loads((reports / "setup.json").read_text(encoding="utf-8"))
            self.assertEqual(setup["status"], "ready")
            self.assertEqual(setup["missingTools"], [])
            self.assertEqual(setup["failedSteps"], [])

    def test_workflow_provisions_once_and_runs_batches_only_after_preflight(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        job = workflow.split("  sugarbin-shell-contracts:\n", 1)[1].split(
            "\n  acid-test:", 1
        )[0]

        rust_setup = job.index("uses: ./.github/actions/setup-rust-cache")
        rsync_setup = job.index("tools/ci-apt-install.sh rsync")
        preflight = job.index("id: shell_contract_preconditions")
        first_batch = job.index("name: Run batch 1/3")
        self.assertLess(rust_setup, preflight)
        self.assertLess(rsync_setup, preflight)
        self.assertLess(preflight, first_batch)
        self.assertNotIn("tools/ci-apt-install.sh b3sum", job)
        self.assertIn("--require-tool b3sum", job)
        self.assertIn("--require-tool rsync", job)
        self.assertEqual(
            job.count("steps.shell_contract_preconditions.outcome == 'success'"),
            3,
        )

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

            fake_bin = Path(directory) / "bin"
            fake_bin.mkdir()
            for tool in ("b3sum", "rsync"):
                path = fake_bin / tool
                path.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
                path.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = f"{fake_bin}:{env['PATH']}"
            preflight = self.run_tool(
                "preflight",
                "--reports-dir",
                str(reports),
                "--commit",
                "abc123",
                "--require-tool",
                "b3sum",
                "--require-tool",
                "rsync",
                "--setup-outcome",
                "rust=success",
                "--setup-outcome",
                "rsync=success",
                env=env,
            )
            self.assertEqual(preflight.returncode, 0, preflight.stderr)

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
