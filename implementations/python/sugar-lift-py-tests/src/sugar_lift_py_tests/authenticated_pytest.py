"""Authenticate the managed pandas corpus before pytest can collect work."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import sysconfig
import tomllib
from dataclasses import dataclass
from importlib import import_module, metadata
from pathlib import Path
from types import ModuleType
from typing import Sequence


class ExecutionEnvironmentMismatch(RuntimeError):
    """The interpreter cannot truthfully name the corpus it would measure."""


@dataclass(frozen=True)
class ImportIdentity:
    name: str
    version: str
    loaded_from: Path


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def authenticate_distribution(
    *,
    name: str,
    module: ModuleType,
    expected_version: str,
    metadata_version: str,
    purelib: Path,
) -> ImportIdentity:
    loaded_from = Path(str(getattr(module, "__file__", ""))).resolve()
    imported_version = str(getattr(module, "__version__", "<missing>"))
    purelib = purelib.resolve()
    if imported_version != expected_version:
        raise ExecutionEnvironmentMismatch(
            f"{name} corpus mismatch: imported {imported_version} from "
            f"{loaded_from}; required exact {expected_version}"
        )
    if not _inside(loaded_from, purelib):
        raise ExecutionEnvironmentMismatch(
            f"{name} loaded from {loaded_from}, outside this interpreter's own "
            f"site-packages {purelib}; refusing a leaking environment"
        )
    if metadata_version != imported_version:
        raise ExecutionEnvironmentMismatch(
            f"{name} dist-info records {metadata_version}, but imported module "
            f"reports {imported_version} from {loaded_from}"
        )
    return ImportIdentity(name, imported_version, loaded_from)


def authenticate_lift(module: ModuleType, repo_root: Path) -> ImportIdentity:
    expected_root = (
        repo_root / "implementations/python/sugar-lift-py-tests/src"
    ).resolve()
    loaded_from = Path(str(getattr(module, "__file__", ""))).resolve()
    if not _inside(loaded_from, expected_root):
        raise ExecutionEnvironmentMismatch(
            f"lift import escaped the synced checkout: loaded "
            f"sugar_lift_py_tests from {loaded_from}; required {expected_root}"
        )
    return ImportIdentity("sugar_lift_py_tests", "checkout-source", loaded_from)


def corpus_manifest_cid(files: Sequence[str]) -> str:
    ordered = sorted(str(path) for path in files)
    if not ordered:
        raise ExecutionEnvironmentMismatch("pandas corpus manifest is empty")
    if len(set(ordered)) != len(ordered):
        raise ExecutionEnvironmentMismatch("pandas corpus manifest contains duplicates")
    preimage = json.dumps(ordered, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(preimage.encode("utf-8")).hexdigest()


def activate_checkout_import_roots(repo_root: Path, search_path: list[str]) -> None:
    """Activate exactly the mounted roots declared by the managed closure."""
    dockerfile = repo_root / "tools/sugar-build/Dockerfile"
    matches = re.findall(
        r"^ENV PYTHONPATH=(.*)$",
        dockerfile.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if len(matches) != 1:
        raise ExecutionEnvironmentMismatch(
            f"expected one managed PYTHONPATH declaration in {dockerfile}, found {len(matches)}"
        )
    prefix = "/workspace/sugar/"
    roots: list[str] = []
    for entry in matches[0].split(":"):
        if not entry.startswith(prefix):
            raise ExecutionEnvironmentMismatch(
                f"managed PYTHONPATH entry escaped the synced checkout: {entry}"
            )
        root = (repo_root / entry[len(prefix) :]).resolve()
        if not root.is_dir():
            raise ExecutionEnvironmentMismatch(
                f"managed PYTHONPATH entry does not exist in the synced checkout: {root}"
            )
        roots.append(str(root))
    search_path[0:0] = roots


def _declared_corpus(package_root: Path) -> tuple[dict[str, str], str]:
    pyproject = package_root / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    requirements = data["project"]["optional-dependencies"]["test"]
    pins: dict[str, str] = {}
    for requirement in requirements:
        for name in ("numpy", "pandas"):
            prefix = f"{name}=="
            if requirement.startswith(prefix):
                pins[name] = requirement[len(prefix) :]
    if set(pins) != {"numpy", "pandas"}:
        raise ExecutionEnvironmentMismatch(
            f"measured corpus pins are incomplete in {pyproject}: {pins}"
        )
    expected_cid = data["tool"]["sugar"]["measured-corpus"]["pandas-manifest-cid"]
    return pins, str(expected_cid)


def authenticate_environment() -> (
    tuple[ImportIdentity, ImportIdentity, ImportIdentity, str]
):
    package_root = Path(__file__).resolve().parents[2]
    repo_root = Path(__file__).resolve().parents[5]
    activate_checkout_import_roots(repo_root, sys.path)
    pins, expected_cid = _declared_corpus(package_root)
    purelib = Path(sysconfig.get_paths()["purelib"])

    pandas = import_module("pandas")
    numpy = import_module("numpy")
    lift = import_module("sugar_lift_py_tests")
    pandas_identity = authenticate_distribution(
        name="pandas",
        module=pandas,
        expected_version=pins["pandas"],
        metadata_version=metadata.version("pandas"),
        purelib=purelib,
    )
    numpy_identity = authenticate_distribution(
        name="numpy",
        module=numpy,
        expected_version=pins["numpy"],
        metadata_version=metadata.version("numpy"),
        purelib=purelib,
    )
    lift_identity = authenticate_lift(lift, repo_root)

    from sugar_source_tree.tree import SourceTree

    pandas_root = pandas_identity.loaded_from.parent
    files = [
        path.resolve().relative_to(pandas_root).as_posix()
        for path in SourceTree(pandas_root).paths()
    ]
    observed_cid = corpus_manifest_cid(files)
    if observed_cid != expected_cid:
        raise ExecutionEnvironmentMismatch(
            "pandas corpus manifest CID mismatch: "
            f"observed {observed_cid} over {len(files)} files; "
            f"required {expected_cid}"
        )
    return pandas_identity, numpy_identity, lift_identity, observed_cid


def main(argv: Sequence[str] | None = None) -> int:
    try:
        pandas_identity, numpy_identity, lift_identity, manifest_cid = (
            authenticate_environment()
        )
    except Exception as error:
        print(
            "BATTLEAXE EXECUTION ENVIRONMENT REFUSED: " + str(error),
            file=sys.stderr,
            flush=True,
        )
        return 78

    print(
        "authenticated execution environment: "
        f"corpusManifestCid={manifest_cid} "
        f"pandas={pandas_identity.version} pandasPath={pandas_identity.loaded_from} "
        f"numpy={numpy_identity.version} numpyPath={numpy_identity.loaded_from} "
        f"liftPath={lift_identity.loaded_from}",
        flush=True,
    )
    import pytest

    return int(pytest.main(list(argv) if argv is not None else sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
