"""Both arms of producer-owned verification-property attendance."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from repo_root_test_support import resolve_repo_root

ROOT = resolve_repo_root()
sys.path.insert(0, str(ROOT / "tools"))

import showcase_terminal_identity  # noqa: E402


class VerificationPropertyAttendanceTests(unittest.TestCase):
    def constructor(self):
        constructor = getattr(
            showcase_terminal_identity,
            "construct_verification_property_attendance",
            None,
        )
        self.assertTrue(
            callable(constructor),
            "verification-property attendance constructor is missing",
        )
        return constructor

    def publisher(self):
        publisher = getattr(
            showcase_terminal_identity,
            "publish_verification_property_attendance",
            None,
        )
        self.assertTrue(
            callable(publisher),
            "verification-property attendance publisher is missing",
        )
        return publisher

    def test_full_attendance_constructs_complete_without_a_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            witness = Path(directory) / "terminal.json"
            with patch.dict(
                os.environ,
                {"SHOWCASE_TERMINAL_WITNESS": str(witness)},
            ):
                result = self.publisher()(
                    required=("claim:a", "claim:b"),
                    observed=("claim:b", "claim:a", "claim:extra"),
                    entrance="sugar.verify",
                )

            self.assertEqual(result.required_identities, ("claim:a", "claim:b"))
            self.assertFalse(witness.exists())

    def test_gap_carries_and_publishes_every_exact_missing_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            witness = Path(directory) / "terminal.json"
            with patch.dict(
                os.environ,
                {"SHOWCASE_TERMINAL_WITNESS": str(witness)},
            ):
                result = self.publisher()(
                    required=("claim:a", "claim:b", "claim:c", "claim:d"),
                    observed=("claim:c", "claim:a", "claim:extra"),
                    entrance="sugar.verify",
                )

            self.assertEqual(result.first_missing, "claim:b")
            self.assertEqual(result.remaining_missing, ("claim:d",))
            self.assertEqual(result.missing_identities, ("claim:b", "claim:d"))
            self.assertEqual(
                json.loads(witness.read_text(encoding="utf-8")),
                {
                    "schemaVersion": 1,
                    "state": "witnessed",
                    "terminalIdentity": {
                        "schemaVersion": 1,
                        "kind": "verification-property-attendance-gap",
                        "owner": "VerificationPropertyAttendanceGap",
                        "coordinate": "claim:b",
                        "entrance": "sugar.verify",
                        "missingIdentities": ["claim:b", "claim:d"],
                    },
                },
            )

    def test_gap_type_cannot_be_constructed_without_a_first_identity(self) -> None:
        gap_type = getattr(
            showcase_terminal_identity,
            "VerificationPropertyAttendanceGap",
            None,
        )
        self.assertTrue(callable(gap_type), "attendance gap type is missing")

        with self.assertRaises(TypeError):
            gap_type()


if __name__ == "__main__":
    unittest.main()
