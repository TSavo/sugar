"""Manifest identity slots accept only the primary canonical coordinate."""

from __future__ import annotations

import ast
from pathlib import Path
import re

_PRIMARY_MANIFEST_COORDINATE = re.compile(r"blake3-512:[0-9a-f]{128}\Z")
_PYTHON_IMPLEMENTATIONS = Path(__file__).resolve().parents[4] / "implementations/python"


def _manifest_identity_slot_violations(source: str, label: str) -> tuple[str, ...]:
    tree = ast.parse(source, filename=label)
    violations = []
    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            targets = statement.targets
            value = statement.value
        elif isinstance(statement, ast.AnnAssign):
            targets = (statement.target,)
            value = statement.value
        else:
            continue
        for target in targets:
            if not isinstance(target, ast.Name) or not target.id.endswith(
                "MANIFEST_CID"
            ):
                continue
            try:
                presented = ast.literal_eval(value)
            except (TypeError, ValueError):
                presented = None
            if (
                not isinstance(presented, str)
                or _PRIMARY_MANIFEST_COORDINATE.fullmatch(presented) is None
            ):
                violations.append(
                    f"{label}:{statement.lineno}: {target.id} presents {presented!r}; "
                    "manifest identity slots require the canonical BLAKE3-512 coordinate"
                )
    return tuple(violations)


def test_canonical_manifest_identity_is_accepted_by_role() -> None:
    canonical = "blake3-512:" + "6" * 128

    assert (
        _manifest_identity_slot_violations(
            f"MANIFEST_CID = {canonical!r}\n", "truthful.py"
        )
        == ()
    )


def test_path_shape_digest_in_manifest_identity_role_is_refused() -> None:
    historical_shape = "sha256:" + "a" * 64

    assert _manifest_identity_slot_violations(
        f"MANIFEST_CID = {historical_shape!r}\n", "lying.py"
    ) == (
        "lying.py:1: MANIFEST_CID presents "
        f"{historical_shape!r}; manifest identity slots require the canonical "
        "BLAKE3-512 coordinate",
    )


def test_named_historical_and_shape_roles_remain_distinct() -> None:
    historical_shape = "sha256:" + "a" * 64
    source = (
        f"HISTORICAL_PATH_SHAPE_DIGEST = {historical_shape!r}\n"
        f"_PANDAS_3_0_3_MANIFEST_SHAPE_CID = {historical_shape!r}\n"
    )

    assert _manifest_identity_slot_violations(source, "honest-shape.py") == ()


def test_python_modules_never_put_noncanonical_digest_in_manifest_identity_role() -> (
    None
):
    violations = tuple(
        violation
        for path in sorted(_PYTHON_IMPLEMENTATIONS.rglob("*.py"))
        for violation in _manifest_identity_slot_violations(
            path.read_text(encoding="utf-8"),
            str(path.relative_to(_PYTHON_IMPLEMENTATIONS)),
        )
    )

    assert not violations, "\n".join(violations)
