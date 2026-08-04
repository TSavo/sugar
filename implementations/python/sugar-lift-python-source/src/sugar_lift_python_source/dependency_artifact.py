"""Authenticated installed Python artifacts and static object resolution.

This module is a preconstruction boundary.  It reads distribution-recorded
files once, content-addresses them, and resolves only source-visible static
imports and re-exports.  It never imports or executes a target module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from email.parser import BytesParser
import importlib.machinery
import importlib.metadata
import logging
import os
from pathlib import Path, PurePosixPath
import sys
import sysconfig
from types import MappingProxyType
from typing import Any, Literal, Mapping

from .canonical import blake3_512_of, cid_of_json
from .resolution_session import SourceResolutionSession, session_or_new
from .source_oracle import SourceUnavailable, dependency_artifact_file


class DependencyArtifactAuthenticationError(Exception):
    """The selected installed artifact cannot be authenticated exactly."""


class DependencyArtifactConstructionError(DependencyArtifactAuthenticationError):
    """A graph allocation bypassed its authenticated input constructor."""


class DependencyArtifactCacheInputError(DependencyArtifactAuthenticationError):
    """A disk seat does not encode dependency graph constructor inputs."""


_LOG = logging.getLogger(__name__)
_DEPENDENCY_ARTIFACT_CACHE_SCHEMA = "dep-graph-v4"

# The authenticated-graph memo is CONTENT-ADDRESSED, and that is the whole
# reason it may be process-global (#6266's distinction, applied here).
#
# The key is the ``distribution_artifact_cid`` -- the CID over every recorded
# file's content CID.  ``h = h(p)``: the key is a pure function of exactly the
# bytes the value authenticates, so "the installation changed but the memo did
# not" is not a bug to detect, it is a sentence that cannot be written.  A miss
# is the only thing a changed byte can produce.
#
# It was keyed by dist-info PATH, and that shipped a CID that did not address
# its bytes: authenticate -> edit the installed source -> authenticate returned
# the first graph, reporting an artifact CID for content that no longer existed
# on disk.  The neighbouring disk cache stat'ed ``RECORD``, which is not touched
# when an installed ``.py`` file is edited, so it served the same stale graph
# across processes.  Both are now keyed by the artifact CID.
#
# The VALUE is legitimately shareable here, which is why this is a registry and
# not a session: ``DependencyArtifactGraph`` is a frozen dataclass over a tuple
# of frozen files and a ``MappingProxyType``, holding bytes and str only.  It
# owns no live construction context, so no caller can write into a served graph
# and have that write reach another authentication.  (Contrast
# ``resolution_session``: those memo VALUES were bound to a mutable
# ``TreeConstructionContextV1``, which is why they needed an owner.)
_AUTHENTICATE_GRAPH_CACHE: dict[str, "DependencyArtifactGraph"] = {}

# Memoization switch. Flipping it must change SPEED ONLY: never a CID, never a
# verdict, never a graph. Paying full price is always a legal answer.
_AUTHENTICATE_CACHE_ENABLED = True


def _require_parseable_module_source(
    source: str, *, path: str, module_name: str
) -> None:
    """Parse gate only — not a typed tree, not retained construction.

    Full ``SourceFile`` materialize (parse + bind) was used here and discarded.
    That re-parsed every installed module on every authenticate call (~50ms each
    × thousands of files) and dominated census child walls. Content addressing
    already proved the bytes; this only rejects unparseable UTF-8 source.
    """
    try:
        compile(source, path, "exec", dont_inherit=True)
    except SyntaxError as exc:
        raise DependencyArtifactAuthenticationError(
            f"recorded Python module {module_name} is not parseable UTF-8 source"
        ) from exc


def _cache_root() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "sugar"


def _artifact_disk_cache_path(artifact_cid: str) -> Path:
    """On-disk seat for one authenticated graph, addressed by its own CID.

    The seat is a pure function of the artifact CID, so a changed installed byte
    changes the CID, which changes the seat: a stale hit has no filename to live
    at. The seat this replaced was a digest over ``RECORD``'s ``(mtime, size)``,
    which does not move when an installed ``.py`` file is edited.
    """
    digest = artifact_cid.removeprefix("blake3-512:")[:32]
    return _cache_root() / "dependency-artifact-graphs" / f"{digest}.pkl"


def _load_authenticate_disk_cache(
    artifact_cid: str,
) -> "DependencyArtifactGraph | None":
    path = _artifact_disk_cache_path(artifact_cid)
    if not path.is_file():
        return None
    try:
        import pickle

        with path.open("rb") as stream:
            payload = pickle.load(stream)
        inputs = _decode_dependency_artifact_cache_inputs(payload)
        graph = DependencyArtifactGraph._construct_from_authenticated_inputs(inputs)
    except Exception as exc:
        _refuse_authenticate_disk_cache(
            artifact_cid=artifact_cid,
            path=path,
            reason=f"{type(exc).__name__}: {exc}",
        )
        return None
    # Construction re-derived the CID from the retained inputs. Pin that it is
    # the CID that was ASKED for, so a payload parked at a wrong seat cannot
    # answer a question it does not address.
    if graph.distribution_artifact_cid != artifact_cid:
        _refuse_authenticate_disk_cache(
            artifact_cid=artifact_cid,
            path=path,
            reason=(
                "parked artifact CID mismatch: "
                f"payload={graph.distribution_artifact_cid}"
            ),
        )
        return None
    return graph


def _decode_dependency_artifact_cache_inputs(
    payload: object,
) -> "_DistributionGraphInputs":
    """Construct distribution inputs from the cache's primitive wire form."""
    if not isinstance(payload, dict) or set(payload) != {"schema", "files"}:
        raise DependencyArtifactCacheInputError(
            "dependency artifact cache input has an invalid key set"
        )
    if payload["schema"] != _DEPENDENCY_ARTIFACT_CACHE_SCHEMA:
        raise DependencyArtifactCacheInputError(
            "disk cache schema mismatch: "
            f"expected={_DEPENDENCY_ARTIFACT_CACHE_SCHEMA} "
            f"actual={payload['schema']}"
        )
    rows = payload["files"]
    if not isinstance(rows, list):
        raise DependencyArtifactCacheInputError(
            "dependency artifact cache files must be a list"
        )
    located: list[tuple[AuthenticatedArtifactFileV1, str]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != {
            "source_seat",
            "content_cid",
            "content",
        }:
            raise DependencyArtifactCacheInputError(
                f"dependency artifact cache file {index} has an invalid key set"
            )
        source_seat = row["source_seat"]
        content_cid = row["content_cid"]
        content = row["content"]
        if not isinstance(source_seat, str) or not source_seat:
            raise DependencyArtifactCacheInputError(
                f"dependency artifact cache file {index} has an invalid source seat"
            )
        if not isinstance(content_cid, str) or not content_cid.startswith(
            "blake3-512:"
        ):
            raise DependencyArtifactCacheInputError(
                f"dependency artifact cache file {index} has an invalid content CID"
            )
        if not isinstance(content, bytes):
            raise DependencyArtifactCacheInputError(
                f"dependency artifact cache file {index} has non-byte content"
            )
        located.append(
            (
                AuthenticatedArtifactFileV1(
                    source_seat=source_seat,
                    content_cid=content_cid,
                    content=content,
                ),
                source_seat,
            )
        )
    return _DistributionGraphInputs(tuple(located))


def _refuse_authenticate_disk_cache(
    *,
    artifact_cid: str,
    path: Path,
    reason: str,
) -> None:
    """Make one rejected cache seat visible, then make it absent."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        invalidated = False
    else:
        invalidated = not path.exists()
    _LOG.warning(
        "dependency-artifact-cache-refused " "artifact_cid=%s reason=%s invalidated=%s",
        artifact_cid,
        reason,
        invalidated,
    )


def _store_authenticate_disk_cache(
    graph: "DependencyArtifactGraph",
) -> None:
    path = _artifact_disk_cache_path(graph.distribution_artifact_cid)
    try:
        import pickle
        import tempfile

        payload = {
            # v4 persists constructor INPUTS only. Identity, kind, CID, and
            # module projection are re-derived through graph construction.
            "schema": _DEPENDENCY_ARTIFACT_CACHE_SCHEMA,
            "files": [
                {
                    "source_seat": item.source_seat,
                    "content_cid": item.content_cid,
                    "content": item.content,
                }
                for item in graph.files
            ],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(path.parent), prefix=".auth-", suffix=".pkl"
        )
        try:
            with os.fdopen(fd, "wb") as stream:
                pickle.dump(payload, stream, protocol=pickle.HIGHEST_PROTOCOL)
            Path(tmp_name).replace(path)
        except Exception:
            try:
                Path(tmp_name).unlink(missing_ok=True)
            except OSError:
                pass
            raise
    except Exception:
        return


@dataclass(frozen=True)
class AuthenticatedArtifactFileV1:
    source_seat: str
    content_cid: str
    content: bytes = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if blake3_512_of(self.content) != self.content_cid:
            raise DependencyArtifactAuthenticationError(
                "artifact file CID does not match its retained bytes"
            )


@dataclass(frozen=True)
class AuthenticatedModuleSourceV1:
    module_name: str
    source_seat: str
    source_cid: str
    source: str = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if blake3_512_of(self.source.encode("utf-8")) != self.source_cid:
            raise DependencyArtifactAuthenticationError(
                "module source CID does not match its retained source"
            )


@dataclass(frozen=True)
class DefinitionCoordinateV1:
    name: str
    kind: Literal["function", "class", "import", "alias"]
    source_cid: str
    start_line: int
    start_col: int
    end_line: int
    end_col: int
    fragment_cid: str

    def __post_init__(self) -> None:
        _string(self.name, "definition name")
        if self.kind not in {"function", "class", "import", "alias"}:
            raise ValueError("definition coordinate has unknown kind")
        _cid(self.source_cid, "definition sourceCid")
        for value, label in (
            (self.start_line, "startLine"),
            (self.start_col, "startCol"),
            (self.end_line, "endLine"),
            (self.end_col, "endCol"),
        ):
            _nonnegative_int(value, label)
        _cid(self.fragment_cid, "definition fragmentCid")

    def to_value(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "sourceCid": self.source_cid,
            "startLine": self.start_line,
            "startCol": self.start_col,
            "endLine": self.end_line,
            "endCol": self.end_col,
            "fragmentCid": self.fragment_cid,
        }

    @classmethod
    def from_value(cls, value: Any) -> "DefinitionCoordinateV1":
        _require_exact_keys(
            value,
            {
                "name",
                "kind",
                "sourceCid",
                "startLine",
                "startCol",
                "endLine",
                "endCol",
                "fragmentCid",
            },
            "definition coordinate",
        )
        if value["kind"] not in {"function", "class", "import", "alias"}:
            raise ValueError("definition coordinate has unknown kind")
        return cls(
            name=_string(value["name"], "definition name"),
            kind=value["kind"],
            source_cid=_cid(value["sourceCid"], "definition sourceCid"),
            start_line=_nonnegative_int(value["startLine"], "startLine"),
            start_col=_nonnegative_int(value["startCol"], "startCol"),
            end_line=_nonnegative_int(value["endLine"], "endLine"),
            end_col=_nonnegative_int(value["endCol"], "endCol"),
            fragment_cid=_cid(value["fragmentCid"], "definition fragmentCid"),
        )


@dataclass(frozen=True)
class ReexportWarrantV1:
    from_module: str
    from_source_cid: str
    to_module: str
    to_source_cid: str
    exported_name: str
    imported_name: str
    definition: DefinitionCoordinateV1
    cid: str = ""

    def __post_init__(self) -> None:
        if self.definition.kind not in {"import", "alias"}:
            raise ValueError(
                "re-export warrant must cite an import or alias definition"
            )
        if self.definition.source_cid != self.from_source_cid:
            raise ValueError("re-export definition is not in its from-module source")
        expected = cid_of_json(self._preimage())
        if self.cid and self.cid != expected:
            raise ValueError("re-export warrant CID does not match its preimage")
        object.__setattr__(self, "cid", expected)

    def _preimage(self) -> dict[str, Any]:
        return {
            "kind": "python-static-reexport-warrant",
            "schemaVersion": "1",
            "fromModule": self.from_module,
            "fromSourceCid": self.from_source_cid,
            "toModule": self.to_module,
            "toSourceCid": self.to_source_cid,
            "exportedName": self.exported_name,
            "importedName": self.imported_name,
            "definition": self.definition.to_value(),
        }

    def to_value(self) -> dict[str, Any]:
        return {**self._preimage(), "cid": self.cid}

    @classmethod
    def from_value(cls, value: Any) -> "ReexportWarrantV1":
        _require_exact_keys(
            value,
            {
                "kind",
                "schemaVersion",
                "fromModule",
                "fromSourceCid",
                "toModule",
                "toSourceCid",
                "exportedName",
                "importedName",
                "definition",
                "cid",
            },
            "re-export warrant",
        )
        if (
            value["kind"] != "python-static-reexport-warrant"
            or value["schemaVersion"] != "1"
        ):
            raise ValueError("unsupported re-export warrant")
        return cls(
            from_module=_string(value["fromModule"], "fromModule"),
            from_source_cid=_cid(value["fromSourceCid"], "fromSourceCid"),
            to_module=_string(value["toModule"], "toModule"),
            to_source_cid=_cid(value["toSourceCid"], "toSourceCid"),
            exported_name=_string(value["exportedName"], "exportedName"),
            imported_name=_string(value["importedName"], "importedName"),
            definition=DefinitionCoordinateV1.from_value(value["definition"]),
            cid=_cid(value["cid"], "warrant cid"),
        )


@dataclass(frozen=True)
class ResolvedPythonObjectV1:
    distribution_artifact_cid: str
    import_binding_cid: str
    module_name: str
    source_cid: str
    reexport_warrants: tuple[ReexportWarrantV1, ...]
    definition: DefinitionCoordinateV1
    cid: str = ""

    def __post_init__(self) -> None:
        if self.definition.kind not in {"function", "class"}:
            raise ValueError(
                "resolved Python object must name a callable or class definition"
            )
        if self.definition.source_cid != self.source_cid:
            raise ValueError("resolved definition is not in the resolved module source")
        for left, right in zip(
            self.reexport_warrants,
            self.reexport_warrants[1:],
            strict=False,
        ):
            if (
                left.to_module != right.from_module
                or left.to_source_cid != right.from_source_cid
            ):
                raise ValueError("re-export warrants do not form one source chain")
        if self.reexport_warrants:
            last = self.reexport_warrants[-1]
            if (
                last.to_module != self.module_name
                or last.to_source_cid != self.source_cid
            ):
                raise ValueError(
                    "re-export warrants do not reach the resolved definition"
                )
        expected = cid_of_json(self._preimage())
        if self.cid and self.cid != expected:
            raise ValueError("resolved Python object CID does not match its preimage")
        object.__setattr__(self, "cid", expected)

    def _preimage(self) -> dict[str, Any]:
        return {
            "kind": "resolved-python-object",
            "schemaVersion": "1",
            "distributionArtifactCid": self.distribution_artifact_cid,
            "importBindingCid": self.import_binding_cid,
            "moduleName": self.module_name,
            "sourceCid": self.source_cid,
            "reexportWarrants": [item.to_value() for item in self.reexport_warrants],
            "definition": self.definition.to_value(),
        }

    def to_value(self) -> dict[str, Any]:
        return {**self._preimage(), "cid": self.cid}

    @classmethod
    def from_value(
        cls,
        value: Any,
        *,
        graph: "DependencyArtifactGraph",
        authenticated_use: Any,
        session: "SourceResolutionSession",
    ) -> "ResolvedPythonObjectV1":
        """Authenticate wire input by re-resolving every cited preimage.

        Parsing and recomputing this object's outer CID is insufficient: an
        invented but self-consistent payload is not artifact authentication.
        """
        _require_exact_keys(
            value,
            {
                "kind",
                "schemaVersion",
                "distributionArtifactCid",
                "importBindingCid",
                "moduleName",
                "sourceCid",
                "reexportWarrants",
                "definition",
                "cid",
            },
            "resolved Python object",
        )
        if value["kind"] != "resolved-python-object" or value["schemaVersion"] != "1":
            raise ValueError("unsupported resolved Python object")
        warrants = value["reexportWarrants"]
        if not isinstance(warrants, list):
            raise ValueError("reexportWarrants must be a list")
        revalidated = resolve_import_binding(
            authenticated_use, graph=graph, session=session
        )
        if not isinstance(revalidated, cls) or revalidated.to_value() != value:
            raise DependencyArtifactAuthenticationError(
                "resolved object is not byte-identical to artifact re-resolution"
            )
        decoded = cls(
            distribution_artifact_cid=_cid(
                value["distributionArtifactCid"], "distributionArtifactCid"
            ),
            import_binding_cid=_cid(value["importBindingCid"], "importBindingCid"),
            module_name=_string(value["moduleName"], "moduleName"),
            source_cid=_cid(value["sourceCid"], "sourceCid"),
            reexport_warrants=tuple(
                ReexportWarrantV1.from_value(item) for item in warrants
            ),
            definition=DefinitionCoordinateV1.from_value(value["definition"]),
            cid=_cid(value["cid"], "resolved object cid"),
        )
        if decoded != revalidated:
            raise DependencyArtifactAuthenticationError(
                "decoded resolved object differs from its authenticated preimage"
            )
        return revalidated


@dataclass(frozen=True)
class PythonObjectResolutionGapV1:
    kind: Literal[
        "malformed-import-binding",
        "artifact-module-absent",
        "target-outside-binding",
        "dynamic-export",
        "unsupported-statement",
        "ambiguous-static-export",
        "static-export-absent",
        "opaque-source",
        "reexport-cycle",
    ]
    import_binding_cid: str
    distribution_artifact_cid: str
    module_name: str
    exported_name: str


PythonObjectResolutionV1 = ResolvedPythonObjectV1 | PythonObjectResolutionGapV1


@dataclass(frozen=True)
class _DistributionGraphInputs:
    located: tuple[tuple[AuthenticatedArtifactFileV1, str], ...]


@dataclass(frozen=True)
class _StdlibGraphInputs:
    located: tuple[tuple[AuthenticatedArtifactFileV1, str], ...]
    requested_module_name: str


_DependencyArtifactGraphInputs = _DistributionGraphInputs | _StdlibGraphInputs


@dataclass(frozen=True, init=False)
class DependencyArtifactGraph:
    artifact_kind: Literal["distribution", "stdlib"]
    distribution_name: str
    distribution_version: str
    distribution_artifact_cid: str
    files: tuple[AuthenticatedArtifactFileV1, ...]
    modules: Mapping[str, AuthenticatedModuleSourceV1]

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise DependencyArtifactConstructionError(
            "DependencyArtifactGraph cannot be allocated from graph fields; "
            "construct it from authenticated artifact inputs"
        )

    @classmethod
    def _construct_from_authenticated_inputs(
        cls, inputs: _DependencyArtifactGraphInputs
    ) -> "DependencyArtifactGraph":
        """The only allocation path from authenticated artifact testimony."""
        located = inputs.located
        files = tuple(item for item, _ in located)
        records = [
            {"path": item.source_seat, "contentCid": item.content_cid} for item in files
        ]
        if records != sorted(records, key=lambda item: item["path"]):
            raise DependencyArtifactAuthenticationError(
                "artifact files must be canonically ordered"
            )
        files_by_seat = {item.source_seat: item for item in files}
        if len(files_by_seat) != len(files):
            raise DependencyArtifactAuthenticationError(
                "distribution artifact contains duplicate file seats"
            )

        modules: dict[str, AuthenticatedModuleSourceV1] = {}
        for item, diagnostic_path in located:
            relative = PurePosixPath(item.source_seat)
            module_name = _module_name(relative)
            if module_name is None:
                continue
            try:
                source = item.content.decode("utf-8")
            except UnicodeError as exc:
                raise DependencyArtifactAuthenticationError(
                    f"recorded Python module {module_name} is not parseable UTF-8 source"
                ) from exc
            _require_parseable_module_source(
                source, path=diagnostic_path, module_name=module_name
            )
            if module_name in modules:
                raise DependencyArtifactAuthenticationError(
                    f"distribution contains duplicate module seat {module_name}"
                )
            modules[module_name] = AuthenticatedModuleSourceV1(
                module_name=module_name,
                source_seat=relative.as_posix(),
                source_cid=item.content_cid,
                source=source,
            )

        if isinstance(inputs, _DistributionGraphInputs):
            metadata_files = [
                item
                for item in files
                if item.source_seat.endswith(".dist-info/METADATA")
            ]
            if len(metadata_files) != 1:
                raise DependencyArtifactAuthenticationError(
                    "distribution graph must retain one METADATA preimage"
                )
            metadata = BytesParser().parsebytes(metadata_files[0].content)
            name = metadata.get("Name")
            version = metadata.get("Version")
            if not isinstance(name, str) or not name or not version:
                raise DependencyArtifactAuthenticationError(
                    "installed distribution lacks name or version metadata"
                )
            artifact_kind: Literal["distribution", "stdlib"] = "distribution"
            distribution_name = name
            distribution_version = str(version)
            artifact_preimage_kind = "python-dependency-artifact"
        elif isinstance(inputs, _StdlibGraphInputs):
            if inputs.requested_module_name not in modules:
                raise DependencyArtifactAuthenticationError(
                    "requested stdlib module is not projected from authenticated source"
                )
            artifact_kind = "stdlib"
            distribution_name = f"{sys.implementation.name}-stdlib"
            distribution_version = (
                sys.implementation.cache_tag or sys.version.split()[0]
            )
            artifact_preimage_kind = "python-stdlib-artifact"
        else:
            raise DependencyArtifactConstructionError(
                "dependency artifact graph inputs have an unknown variant"
            )

        artifact_cid = cid_of_json(
            {
                "kind": artifact_preimage_kind,
                "schemaVersion": "1",
                "distributionName": distribution_name,
                "distributionVersion": distribution_version,
                "files": records,
            }
        )

        graph = object.__new__(cls)
        object.__setattr__(graph, "artifact_kind", artifact_kind)
        object.__setattr__(graph, "distribution_name", distribution_name)
        object.__setattr__(graph, "distribution_version", distribution_version)
        object.__setattr__(graph, "distribution_artifact_cid", artifact_cid)
        object.__setattr__(graph, "files", files)
        object.__setattr__(graph, "modules", MappingProxyType(modules))
        return graph

    @staticmethod
    def _read_recorded_installation(
        distribution: importlib.metadata.Distribution,
    ) -> list[tuple[AuthenticatedArtifactFileV1, str]]:
        """Read and content-address the graph constructor's file inputs.

        This is the half that CANNOT be memoized across content change: it is
        what establishes which bytes are on disk right now. Every authentication
        reads it before consulting a memo keyed by the resulting content CID.
        """
        files = distribution.files
        if files is None:
            raise DependencyArtifactAuthenticationError(
                "installed distribution has no recorded file manifest"
            )
        located: list[tuple[AuthenticatedArtifactFileV1, str]] = []
        for recorded in sorted(files, key=lambda item: str(item)):
            relative = PurePosixPath(str(recorded))
            if relative.is_absolute():
                raise DependencyArtifactAuthenticationError(
                    "distribution manifest contains an absolute file seat"
                )
            path = Path(distribution.locate_file(recorded))
            try:
                content, _seat, content_cid = dependency_artifact_file(str(path))
            except SourceUnavailable as exc:
                raise DependencyArtifactAuthenticationError(
                    f"cannot read recorded distribution file {relative}"
                ) from exc
            located.append(
                (
                    AuthenticatedArtifactFileV1(
                        source_seat=relative.as_posix(),
                        content_cid=content_cid,
                        content=content,
                    ),
                    str(path),
                )
            )
        return located

    @classmethod
    def authenticate(
        cls, distribution: importlib.metadata.Distribution
    ) -> "DependencyArtifactGraph":
        """Hash every recorded installed file and publish authenticated modules."""
        located = cls._read_recorded_installation(distribution)
        constructed = cls._construct_from_authenticated_inputs(
            _DistributionGraphInputs(tuple(located))
        )
        artifact_cid = constructed.distribution_artifact_cid
        if _AUTHENTICATE_CACHE_ENABLED:
            cached = _AUTHENTICATE_GRAPH_CACHE.get(artifact_cid)
            if cached is not None:
                return cached
            disk = _load_authenticate_disk_cache(artifact_cid)
            if disk is not None:
                _AUTHENTICATE_GRAPH_CACHE[artifact_cid] = disk
                return disk
        graph = constructed
        if _AUTHENTICATE_CACHE_ENABLED:
            _AUTHENTICATE_GRAPH_CACHE[artifact_cid] = graph
            _store_authenticate_disk_cache(graph)
        return graph

    @classmethod
    def authenticate_stdlib_module(cls, module_name: str) -> "DependencyArtifactGraph":
        """Authenticate source reached through the running Python's stdlib root."""
        if not module_name or not all(
            part.isidentifier() for part in module_name.split(".")
        ):
            raise DependencyArtifactAuthenticationError("invalid stdlib module name")
        root = Path(sysconfig.get_path("stdlib")).resolve()
        top_level = module_name.split(".", 1)[0]
        spec = importlib.machinery.PathFinder.find_spec(top_level, [str(root)])
        if spec is None or spec.origin is None:
            raise DependencyArtifactAuthenticationError(
                "module has no source in the authenticated stdlib root"
            )
        return cls.authenticate_stdlib_path(
            top_level, Path(spec.origin), stdlib_root=root
        )

    @classmethod
    def authenticate_stdlib_path(
        cls, module_name: str, path: Path, *, stdlib_root: Path
    ) -> "DependencyArtifactGraph":
        """Content-address one stdlib module/package after root containment."""
        root = stdlib_root.resolve()
        source_path = path.resolve()
        if (
            not source_path.is_relative_to(root)
            or any(
                part in {"site-packages", "dist-packages"} for part in source_path.parts
            )
            or source_path.suffix != ".py"
        ):
            raise DependencyArtifactAuthenticationError(
                "module source is outside the authenticated stdlib root"
            )
        paths = (
            sorted(source_path.parent.rglob("*.py"))
            if source_path.name == "__init__.py"
            else [source_path]
        )
        located: list[tuple[AuthenticatedArtifactFileV1, str]] = []
        for candidate in paths:
            relative = PurePosixPath(candidate.relative_to(root).as_posix())
            try:
                content, _seat, content_cid = dependency_artifact_file(str(candidate))
            except (
                SourceUnavailable,
                ValueError,
            ) as exc:
                raise DependencyArtifactAuthenticationError(
                    f"cannot authenticate stdlib source {relative}"
                ) from exc
            located.append(
                (
                    AuthenticatedArtifactFileV1(
                        relative.as_posix(), content_cid, content
                    ),
                    str(candidate),
                )
            )
        return cls._construct_from_authenticated_inputs(
            _StdlibGraphInputs(tuple(located), module_name)
        )


# packages_distributions() walks every installed dist's file list (measured
# ~0.5s+ per call). Content of the install map — not a projection memo — so a
# process cache is legitimate. Top-level graph answers reuse the same map.
_PACKAGES_DISTRIBUTIONS_CACHE: Mapping[str, list[str]] | None = None
_TOP_LEVEL_GRAPH_CACHE: dict[str, "DependencyArtifactGraph"] = {}


def clear_top_level_authentication_caches() -> None:
    """Drop top-level auth memos (tests / hermetic process reuse)."""
    global _PACKAGES_DISTRIBUTIONS_CACHE
    _PACKAGES_DISTRIBUTIONS_CACHE = None
    _TOP_LEVEL_GRAPH_CACHE.clear()


def _packages_distributions() -> Mapping[str, list[str]]:
    global _PACKAGES_DISTRIBUTIONS_CACHE
    if _PACKAGES_DISTRIBUTIONS_CACHE is None:
        _PACKAGES_DISTRIBUTIONS_CACHE = importlib.metadata.packages_distributions()
    return _PACKAGES_DISTRIBUTIONS_CACHE


def authenticate_dependency_top_level(
    top_level: str,
    *,
    distribution_index: Mapping[str, importlib.metadata.Distribution] | None = None,
) -> DependencyArtifactGraph:
    """Authenticate a distribution or stdlib module through one graph door."""
    if distribution_index is not None and top_level in distribution_index:
        return DependencyArtifactGraph.authenticate(distribution_index[top_level])
    # Ambient install map only — never share with an explicit distribution_index.
    if _AUTHENTICATE_CACHE_ENABLED:
        cached = _TOP_LEVEL_GRAPH_CACHE.get(top_level)
        if cached is not None:
            return cached
    # Fast path: many top-levels share the distribution name (pandas, numpy, …).
    # ``packages_distributions()`` walks every installed dist (~0.2s measured);
    # try the direct door first and only pay the install-map walk on miss
    # (e.g. dateutil → python-dateutil) or multi-owner conflict.
    graph: DependencyArtifactGraph | None = None
    try:
        graph = DependencyArtifactGraph.authenticate(
            importlib.metadata.distribution(top_level)
        )
    except importlib.metadata.PackageNotFoundError:
        packages = _packages_distributions()
        distributions = tuple(packages.get(top_level, ()))
        if len(distributions) == 1:
            graph = DependencyArtifactGraph.authenticate(
                importlib.metadata.distribution(distributions[0])
            )
        elif distributions:
            raise DependencyArtifactAuthenticationError(
                "top-level module belongs to multiple installed distributions"
            )
        else:
            graph = DependencyArtifactGraph.authenticate_stdlib_module(top_level)
    if _AUTHENTICATE_CACHE_ENABLED:
        _TOP_LEVEL_GRAPH_CACHE[top_level] = graph
    return graph


def resolve_import_binding(
    authenticated_use: Any,
    *,
    graph: DependencyArtifactGraph,
    session: "SourceResolutionSession | None" = None,
) -> PythonObjectResolutionV1:
    """Resolve a final-checked #6090 import use through one artifact graph.

    ``session`` owns every resolution memo consulted on the way.  ``None``
    opens one bounded to this single call; it is never process state.
    """
    from sugar_lift_py_tests.import_binding import AuthenticatedImportUseV1

    if not isinstance(authenticated_use, AuthenticatedImportUseV1):
        raise DependencyArtifactAuthenticationError(
            "source resolution requires AuthenticatedImportUseV1"
        )
    try:
        authenticated_use.revalidate()
    except ValueError as exc:
        raise DependencyArtifactAuthenticationError(
            "authenticated import use failed lexical revalidation"
        ) from exc
    binding_value = authenticated_use.import_binding.to_value()
    target_symbol = authenticated_use.target_symbol
    binding_cid = cid_of_json(binding_value)
    if binding_cid != authenticated_use.import_binding.cid:
        raise DependencyArtifactAuthenticationError(
            "authenticated import binding differs from its final-checked preimage"
        )
    try:
        module_name, bound_path, authenticated_source_cid = _binding_target(
            binding_value
        )
    except (KeyError, TypeError, ValueError):
        return _gap("malformed-import-binding", binding_cid, graph, "", target_symbol)
    prefix = "python:"
    if not target_symbol.startswith(prefix):
        return _gap(
            "target-outside-binding", binding_cid, graph, module_name, target_symbol
        )
    requested = target_symbol[len(prefix) :].split(".")
    module = graph.modules.get(module_name)
    if (
        authenticated_source_cid is not None
        and module is not None
        and module.source_cid != authenticated_source_cid
    ):
        return _gap("opaque-source", binding_cid, graph, module_name, target_symbol)
    base = module_name.split(".")
    bound = list(bound_path)
    if bound:
        binding_prefix = base + bound
        if len(bound) != 1:
            return _gap(
                "target-outside-binding",
                binding_cid,
                graph,
                module_name,
                target_symbol,
            )
        if requested == binding_prefix:
            exported_name = bound[0]
        else:
            suffix = requested[len(binding_prefix) :]
            nested_module = ".".join(binding_prefix)
            demand_kind = authenticated_use.demand.get("kind")
            if (
                requested[: len(binding_prefix)] != binding_prefix
                or len(suffix) != 1
                or nested_module not in graph.modules
                or (
                    demand_kind == "import-value-use-demand"
                    and list(authenticated_use.use.get("exportedMemberPath") or ())
                    != suffix
                )
            ):
                return _gap(
                    "target-outside-binding",
                    binding_cid,
                    graph,
                    module_name,
                    target_symbol,
                )
            module_name = nested_module
            exported_name = suffix[0]
    elif requested[: len(base)] == base and len(requested) == len(base) + 1:
        exported_name = requested[-1]
    else:
        return _gap(
            "target-outside-binding", binding_cid, graph, module_name, target_symbol
        )
    return _resolve_export(
        graph,
        binding_cid,
        module_name,
        exported_name,
        (),
        frozenset(),
        session=session_or_new(session),
    )


def resolve_authenticated_module_export(
    *,
    graph: DependencyArtifactGraph,
    binding_cid: str,
    module_name: str,
    exported_name: str,
    session: "SourceResolutionSession | None" = None,
) -> PythonObjectResolutionV1:
    """Resolve a provider export after its module binding was authenticated.

    This is the non-``import`` spelling of :func:`resolve_import_binding`: a
    source-derived module provider (for example, a returned module value) owns
    ``binding_cid`` and ``module_name`` already.  Export traversal remains the
    same content-addressed source/re-export walk; callers cannot supply a
    definition, CID, or successful result directly.
    """
    _cid(binding_cid, "provider binding cid")
    _string(module_name, "provider module name")
    _string(exported_name, "provider exported name")
    return _resolve_export(
        graph,
        binding_cid,
        module_name,
        exported_name,
        (),
        frozenset(),
        session=session_or_new(session),
    )


def _binding_target(
    value: Mapping[str, Any],
) -> tuple[str, tuple[str, ...], str | None]:
    if value["kind"] != "python-import-binding" or value["schemaVersion"] != "1":
        raise ValueError("unsupported import binding")
    target = value["target"]
    identity = target["moduleIdentity"]
    if identity["kind"] == "unavailable-python-module":
        module_name = identity["name"]
        source_cid = None
    elif identity["kind"] == "authenticated-python-module":
        module_name = identity["moduleName"]
        source_cid = _cid(identity["sourceCid"], "module identity sourceCid")
    else:
        raise ValueError("unsupported module identity")
    path = target["exportedPath"]
    if not isinstance(path, list) or not all(
        isinstance(item, str) and item for item in path
    ):
        raise ValueError("invalid exported path")
    return _string(module_name, "module name"), tuple(path), source_cid


def _module_name(path: PurePosixPath) -> str | None:
    # PEP 484 stubs are defining Python source for names and class ancestry.
    # Wheels with native extension modules commonly ship the callable runtime
    # in ``.so`` and the source-visible type definitions in a sibling ``.pyi``
    # (PyArrow's exception hierarchy is one such provider).  Discarding that
    # recorded, content-addressed source turns a reachable class definition
    # into opacity.  A distribution containing both ``x.py`` and ``x.pyi``
    # remains a duplicate module seat and is refused by the existing intake
    # check; this door never chooses whichever file is convenient.
    if path.suffix not in {".py", ".pyi"}:
        return None
    parts = list(path.with_suffix("").parts)
    if any(part.endswith(".dist-info") or part.endswith(".data") for part in parts):
        return None
    if parts[-1] == "__init__":
        parts.pop()
    if not parts or not all(part.isidentifier() for part in parts):
        return None
    return ".".join(parts)


def _gap(
    kind: Any,
    binding_cid: str,
    graph: DependencyArtifactGraph,
    module_name: str,
    exported_name: str,
) -> PythonObjectResolutionGapV1:
    return PythonObjectResolutionGapV1(
        kind=kind,
        import_binding_cid=binding_cid,
        distribution_artifact_cid=graph.distribution_artifact_cid,
        module_name=module_name,
        exported_name=exported_name,
    )


def _require_exact_keys(value: Any, expected: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"{label} has an invalid key set")


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a nonempty string")
    return value


def _cid(value: Any, label: str) -> str:
    value = _string(value, label)
    if not value.startswith("blake3-512:"):
        raise ValueError(f"{label} must be a content CID")
    return value


def _nonnegative_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} must be a nonnegative integer")
    return value


def _resolve_export(*args, **kwargs):
    from .dependency_export_adapter import resolve_export

    return resolve_export(*args, **kwargs)


def export_statement_coverage():
    from .dependency_export_adapter import export_statement_coverage as _coverage

    return _coverage()
