"""Authenticate the managed pandas corpus before pytest can collect work."""

from __future__ import annotations

import sys
import sysconfig
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from importlib import import_module, metadata
from pathlib import Path
from types import ModuleType
from typing import Iterable, Sequence

from sugar_lift_py_tests.demand_table_identity import corpus_manifest_cid
from sugar_lift_py_tests.repo_root import (
    RepoRootUnresolved,
    resolve_repo_root,
    sugar_lift_py_tests_package_root,
)


class ExecutionEnvironmentMismatch(RuntimeError):
    """The interpreter cannot truthfully name the corpus it would measure."""


@dataclass(frozen=True)
class ImportIdentity:
    name: str
    version: str
    loaded_from: Path


@dataclass(frozen=True)
class InterpreterIdentity:
    implementation: str
    version: str
    executable: Path


@dataclass(frozen=True)
class AuthenticatedPandasCorpus:
    """Machine-local seat for one machine-independent authenticated corpus."""

    root: Path
    distribution: str
    version: str
    manifest_cid: str
    file_count: int


def authenticate_corpus(root: Path) -> AuthenticatedPandasCorpus:
    """Authenticate a small directory corpus for tests and fixtures.

    Manifest and file count are measured from bytes. A directory may not
    self-declare the strong pandas identity; that remains package-authenticated
    exclusively by :func:`authenticated_pandas_corpus`.
    """
    from sugar_source_tree.tree import SourceTree

    root = Path(root).resolve()
    sidecar = root.parent / f"{root.name}.identity.json"
    if not sidecar.is_file():
        raise ExecutionEnvironmentMismatch(
            f"authenticated corpus sidecar missing beside {root}: {sidecar}"
        )
    import json

    try:
        claims = json.loads(sidecar.read_text(encoding="utf-8"))
        distribution = str(claims["distribution"]).strip()
        version = str(claims["version"]).strip()
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ExecutionEnvironmentMismatch(
            f"authenticated corpus sidecar malformed: {sidecar}: {exc}"
        ) from exc
    if not distribution or not version or distribution == "pandas":
        raise ExecutionEnvironmentMismatch(
            "generic corpus authentication refuses pandas or empty claimed identity"
        )
    from sugar_lift_py_tests.corpus_pin import pin_corpus

    pin = pin_corpus(root, distribution=distribution, version=version)
    return AuthenticatedPandasCorpus(
        root=root,
        distribution=distribution,
        version=version,
        manifest_cid=pin.aggregate_hash,
        file_count=pin.file_count,
    )


def interpreter_identity() -> InterpreterIdentity:
    version = sys.version_info
    return InterpreterIdentity(
        implementation=sys.implementation.name,
        version=f"{version.major}.{version.minor}.{version.micro}",
        executable=Path(sys.executable).absolute(),
    )


def declared_interpreter_runtime() -> str:
    """Read the one managed Python authority from the build manifest."""
    try:
        repo_root = resolve_repo_root()
    except RepoRootUnresolved as error:
        raise ExecutionEnvironmentMismatch(str(error)) from error
    manifest_path = repo_root / "sugar-build.toml"
    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    version = str(manifest["tools"]["python"])
    return f"cpython-{version}"


def authenticate_interpreter_runtime(
    identity: InterpreterIdentity,
) -> InterpreterIdentity:
    """Refuse execution testimony minted outside the declared runtime."""
    observed = f"{identity.implementation}-{identity.version}"
    required = declared_interpreter_runtime()
    if observed != required:
        raise ExecutionEnvironmentMismatch(
            "Python runtime authority mismatch: "
            f"required {required}; observed {observed} at {identity.executable}"
        )
    return identity


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def authenticate_distribution(
    *,
    name: str,
    module: ModuleType,
    expected_version: str,
    metadata_version: str,
    metadata_location: Path,
    purelib: Path,
) -> ImportIdentity:
    loaded_from = Path(str(getattr(module, "__file__", ""))).resolve()
    imported_version = str(getattr(module, "__version__", "<missing>"))
    purelib = purelib.resolve()
    metadata_location = metadata_location.resolve()
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
    if not _inside(metadata_location, purelib):
        raise ExecutionEnvironmentMismatch(
            f"{name} dist-info loaded from {metadata_location}, outside this "
            f"interpreter's own site-packages {purelib}; refusing foreign metadata"
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


def authenticate_corpus_manifest(
    root: Path, paths: Iterable[Path], expected_cid: str
) -> tuple[str, int]:
    """Authenticate relative paths AND bytes using the shared manifest CID.

    This deliberately reuses ``demand_table_identity.corpus_manifest_cid``.
    The former path-only SHA-256 proved only which files existed, so identical
    paths with edited, truncated, or partially synchronized bytes passed as an
    authenticated corpus. Reading the pinned 1,421 files costs a measured
    median 1.255 seconds (max 1.591 seconds over five workstation runs), which
    is acceptable once before pytest collection; false authentication is not.
    """
    observed_cid, file_count = corpus_manifest_cid(root, paths)
    if file_count == 0:
        raise ExecutionEnvironmentMismatch("pandas corpus manifest is empty")
    if observed_cid != expected_cid:
        raise ExecutionEnvironmentMismatch(
            "pandas corpus content manifest CID mismatch: "
            f"observed {observed_cid} over {file_count} files; "
            f"required {expected_cid}"
        )
    return observed_cid, file_count


def activate_checkout_import_roots(repo_root: Path, search_path: list[str]) -> None:
    """Activate exactly the mounted roots declared by the managed closure.

    Shares the Dockerfile declaration with ``tools/managed_checkout_pythonpath.py``
    (the CI env binder). Prefer that tool for process-start PYTHONPATH: by the
    time this function runs inside ``sugar_lift_py_tests``, the package is
    already imported, so rebinding ``sys.path`` cannot unseat a site-packages
    copy already in ``sys.modules``. CI must export checkout roots *before*
    any import of this package.
    """
    try:
        from managed_checkout_pythonpath import (  # type: ignore[import-not-found]
            ManagedCheckoutPythonpathError,
            managed_checkout_import_roots,
        )
    except ImportError:
        # stdlib-only loader so authentication still works when tools/ is not
        # already on sys.path (the common authenticated-pytest entry shape).
        import importlib.util

        tool = (
            Path(repo_root).resolve() / "tools" / "managed_checkout_pythonpath.py"
        )
        spec = importlib.util.spec_from_file_location(
            "managed_checkout_pythonpath", tool
        )
        if spec is None or spec.loader is None:
            raise ExecutionEnvironmentMismatch(
                f"cannot load managed checkout PYTHONPATH tool from {tool}"
            )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        ManagedCheckoutPythonpathError = module.ManagedCheckoutPythonpathError
        managed_checkout_import_roots = module.managed_checkout_import_roots

    try:
        roots = [str(root) for root in managed_checkout_import_roots(repo_root)]
    except ManagedCheckoutPythonpathError as error:
        raise ExecutionEnvironmentMismatch(str(error)) from error
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
    authenticate_interpreter_runtime(interpreter_identity())
    try:
        repo_root = resolve_repo_root()
        package_root = sugar_lift_py_tests_package_root(repo_root)
    except RepoRootUnresolved as error:
        raise ExecutionEnvironmentMismatch(str(error)) from error
    # Activate checkout roots before any further first-party import (e.g.
    # sugar_source_tree). sugar_lift_py_tests itself is already loaded when this
    # module runs; process-start PYTHONPATH (python-test-environment) is the
    # authority for that first import. authenticate_lift still refuses a
    # site-packages copy — never relax that check.
    activate_checkout_import_roots(repo_root, sys.path)
    pins, expected_cid = _declared_corpus(package_root)

    purelib = Path(sysconfig.get_paths()["purelib"])

    pandas = import_module("pandas")
    numpy = import_module("numpy")
    # Prefer the already-loaded package (process-start path) over a second
    # import_module after path mutation, which would leave a wrong copy in
    # sys.modules if the first import came from site-packages.
    lift = sys.modules.get("sugar_lift_py_tests") or import_module("sugar_lift_py_tests")
    pandas_distribution = metadata.distribution("pandas")
    numpy_distribution = metadata.distribution("numpy")
    pandas_identity = authenticate_distribution(
        name="pandas",
        module=pandas,
        expected_version=pins["pandas"],
        metadata_version=pandas_distribution.version,
        metadata_location=Path(pandas_distribution.locate_file("")),
        purelib=purelib,
    )
    numpy_identity = authenticate_distribution(
        name="numpy",
        module=numpy,
        expected_version=pins["numpy"],
        metadata_version=numpy_distribution.version,
        metadata_location=Path(numpy_distribution.locate_file("")),
        purelib=purelib,
    )
    lift_identity = authenticate_lift(lift, repo_root)

    from sugar_source_tree.tree import SourceTree

    pandas_root = pandas_identity.loaded_from.parent
    files = list(SourceTree(pandas_root).paths())
    observed_cid, _ = authenticate_corpus_manifest(pandas_root, files, expected_cid)
    return pandas_identity, numpy_identity, lift_identity, observed_cid


@lru_cache(maxsize=1)
def authenticated_pandas_corpus() -> AuthenticatedPandasCorpus:
    """Return the launcher's pandas seat only after content authentication.

    Semantic tests may use ``root`` to open enrolled files, but identity is the
    manifest CID and file count.  The path is deliberately absent from the
    authentication preimage, so relocating byte-identical site-packages is
    harmless while editing bytes in place refuses.
    """
    pandas_identity, _, _, manifest_cid = authenticate_environment()
    from sugar_source_tree.tree import SourceTree

    root = pandas_identity.loaded_from.parent
    try:
        package_root = sugar_lift_py_tests_package_root()
    except RepoRootUnresolved as error:
        raise ExecutionEnvironmentMismatch(str(error)) from error
    _, expected_cid = _declared_corpus(package_root)
    observed_cid, file_count = authenticate_corpus_manifest(
        root, SourceTree(root).paths(), expected_cid
    )
    if observed_cid != manifest_cid:
        raise ExecutionEnvironmentMismatch(
            "launcher corpus identity changed between authentication projections"
        )
    return AuthenticatedPandasCorpus(
        root=root,
        distribution="pandas",
        version=pandas_identity.version,
        manifest_cid=observed_cid,
        file_count=file_count,
    )


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

    interpreter = interpreter_identity()
    print(
        "authenticated execution environment: "
        f"python={interpreter.implementation}-{interpreter.version} "
        f"pythonExecutable={interpreter.executable} "
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
