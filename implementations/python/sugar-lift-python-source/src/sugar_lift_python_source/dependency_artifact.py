"""Authenticated installed Python artifacts and static object resolution.

This module is a preconstruction boundary.  It reads distribution-recorded
files once, content-addresses them, and resolves only source-visible static
imports and re-exports.  It never imports or executes a target module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor
from email.parser import BytesParser
from functools import partial
import importlib.metadata
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Literal, Mapping

from .canonical import blake3_512_of, cid_of_json
from .source_oracle import SourceUnavailable, dependency_artifact_file


class DependencyArtifactAuthenticationError(Exception):
    """The selected installed artifact cannot be authenticated exactly."""


_ARTIFACT_INTAKE_AUTHORITY = object()


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
    kind: Literal["function", "class", "import"]
    source_cid: str
    start_line: int
    start_col: int
    end_line: int
    end_col: int
    fragment_cid: str

    def __post_init__(self) -> None:
        _string(self.name, "definition name")
        if self.kind not in {"function", "class", "import"}:
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
        if value["kind"] not in {"function", "class", "import"}:
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
        if self.definition.kind != "import":
            raise ValueError("re-export warrant must cite an import definition")
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
        revalidated = resolve_import_binding(authenticated_use, graph=graph)
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
class DependencyArtifactGraph:
    distribution_name: str
    distribution_version: str
    distribution_artifact_cid: str
    files: tuple[AuthenticatedArtifactFileV1, ...]
    modules: Mapping[str, AuthenticatedModuleSourceV1]
    _intake_authority: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._intake_authority is not _ARTIFACT_INTAKE_AUTHORITY:
            raise DependencyArtifactAuthenticationError(
                "dependency artifact graph was not minted by SourceOracle intake"
            )
        metadata_files = [
            item
            for item in self.files
            if item.source_seat.endswith(".dist-info/METADATA")
        ]
        if len(metadata_files) != 1:
            raise DependencyArtifactAuthenticationError(
                "distribution graph must retain one METADATA preimage"
            )
        metadata = BytesParser().parsebytes(metadata_files[0].content)
        if (
            metadata.get("Name") != self.distribution_name
            or metadata.get("Version") != self.distribution_version
        ):
            raise DependencyArtifactAuthenticationError(
                "distribution identity does not match its METADATA preimage"
            )
        records = [
            {"path": item.source_seat, "contentCid": item.content_cid}
            for item in self.files
        ]
        if records != sorted(records, key=lambda item: item["path"]):
            raise DependencyArtifactAuthenticationError(
                "artifact files must be canonically ordered"
            )
        expected = cid_of_json(
            {
                "kind": "python-dependency-artifact",
                "schemaVersion": "1",
                "distributionName": self.distribution_name,
                "distributionVersion": self.distribution_version,
                "files": records,
            }
        )
        if expected != self.distribution_artifact_cid:
            raise DependencyArtifactAuthenticationError(
                "distribution artifact CID does not match its file preimage"
            )
        files_by_seat = {item.source_seat: item for item in self.files}
        if len(files_by_seat) != len(self.files):
            raise DependencyArtifactAuthenticationError(
                "distribution artifact contains duplicate file seats"
            )
        for module_name, module in self.modules.items():
            recorded = files_by_seat.get(module.source_seat)
            if (
                module_name != module.module_name
                or module_name != _module_name(PurePosixPath(module.source_seat))
                or recorded is None
                or recorded.content_cid != module.source_cid
            ):
                raise DependencyArtifactAuthenticationError(
                    "module source is not projected from the artifact file manifest"
                )
        expected_modules = {
            name
            for item in self.files
            for name in [_module_name(PurePosixPath(item.source_seat))]
            if name is not None
        }
        if set(self.modules) != expected_modules:
            raise DependencyArtifactAuthenticationError(
                "artifact module projection is incomplete or contains invented modules"
            )

    @classmethod
    def authenticate(
        cls, distribution: importlib.metadata.Distribution
    ) -> "DependencyArtifactGraph":
        """Hash every recorded installed file and publish authenticated modules."""
        files = distribution.files
        if files is None:
            raise DependencyArtifactAuthenticationError(
                "installed distribution has no recorded file manifest"
            )
        authenticated_files: list[AuthenticatedArtifactFileV1] = []
        modules: dict[str, AuthenticatedModuleSourceV1] = {}
        recorded_files = tuple(sorted(files, key=lambda item: str(item)))
        if recorded_files:
            workers = min(8, len(recorded_files))
            with ThreadPoolExecutor(max_workers=workers) as executor:
                authenticated = executor.map(
                    partial(_authenticate_recorded_file, distribution), recorded_files
                )
                authenticated = tuple(authenticated)
        else:
            authenticated = ()
        for relative, content, content_cid in authenticated:
            authenticated_files.append(
                AuthenticatedArtifactFileV1(
                    source_seat=relative.as_posix(),
                    content_cid=content_cid,
                    content=content,
                )
            )
            module_name = _module_name(relative)
            if module_name is None:
                continue
            try:
                source = content.decode("utf-8")
            except UnicodeError as exc:
                raise DependencyArtifactAuthenticationError(
                    f"recorded Python module {module_name} is not UTF-8 source"
                ) from exc
            if module_name in modules:
                raise DependencyArtifactAuthenticationError(
                    f"distribution contains duplicate module seat {module_name}"
                )
            modules[module_name] = AuthenticatedModuleSourceV1(
                module_name=module_name,
                source_seat=relative.as_posix(),
                source_cid=content_cid,
                source=source,
            )
        metadata_files = [
            item
            for item in authenticated_files
            if item.source_seat.endswith(".dist-info/METADATA")
        ]
        if len(metadata_files) != 1:
            raise DependencyArtifactAuthenticationError(
                "installed distribution must contain one recorded METADATA file"
            )
        metadata = BytesParser().parsebytes(metadata_files[0].content)
        name = metadata.get("Name")
        version = metadata.get("Version")
        if not isinstance(name, str) or not name or not version:
            raise DependencyArtifactAuthenticationError(
                "installed distribution lacks name or version metadata"
            )
        preimage = {
            "kind": "python-dependency-artifact",
            "schemaVersion": "1",
            "distributionName": name,
            "distributionVersion": version,
            "files": [
                {"path": item.source_seat, "contentCid": item.content_cid}
                for item in authenticated_files
            ],
        }
        return cls(
            distribution_name=name,
            distribution_version=version,
            distribution_artifact_cid=cid_of_json(preimage),
            files=tuple(authenticated_files),
            modules=MappingProxyType(modules),
            _intake_authority=_ARTIFACT_INTAKE_AUTHORITY,
        )


def _authenticate_recorded_file(distribution, recorded):
    """Read and hash one independent manifest seat; callers preserve file order."""
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
    return relative, content, content_cid


def resolve_import_binding(
    authenticated_use: Any,
    *,
    graph: DependencyArtifactGraph,
) -> PythonObjectResolutionV1:
    """Resolve a final-checked #6090 import use through one artifact graph."""
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
        expected = base + bound
        if requested != expected or len(bound) != 1:
            return _gap(
                "target-outside-binding",
                binding_cid,
                graph,
                module_name,
                target_symbol,
            )
        exported_name = bound[0]
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
    if path.suffix != ".py":
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
