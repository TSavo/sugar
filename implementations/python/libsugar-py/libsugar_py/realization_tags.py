"""Concept API tagging primitives for realization mementos."""

from __future__ import annotations

from dataclasses import dataclass
import shutil
import subprocess
from typing import Any, Callable, Mapping, Sequence, TypeAlias

JsonValue: TypeAlias = (
    None | bool | int | str | Sequence["JsonValue"] | Mapping[str, "JsonValue"]
)


class RealizationTagError(ValueError):
    """Raised when a realization tag cannot be built."""


class _DecoratableRealization:
    def __call__(self, target: Callable[..., Any]) -> Callable[..., Any]:
        tags = list(getattr(target, "__sugar_realization_tags__", ()))
        tags.append(self)
        setattr(target, "__sugar_realization_tags__", tuple(tags))
        return target


@dataclass(frozen=True)
class FirstClassRealization(_DecoratableRealization):
    """A first-class language-native concept realization."""

    syntactic_pattern: str
    surface_locator: str

    def to_json(self) -> dict[str, str]:
        return {
            "kind": "first-class",
            "surface_locator": self.surface_locator,
            "syntactic_pattern": self.syntactic_pattern,
        }

    def to_jcs_string(self) -> str:
        return _encode_jcs(self.to_json())

    def recompute_cid(self) -> str:
        return _blake3_512_of(self.to_jcs_string().encode("utf-8"))


@dataclass(frozen=True)
class CompositionRealization(_DecoratableRealization):
    """A realization expressed as a content-addressed concept composition tree."""

    composition_tree_cid: str

    def to_json(self) -> dict[str, str]:
        return {
            "composition_tree_cid": self.composition_tree_cid,
            "kind": "composition",
        }

    def to_jcs_string(self) -> str:
        return _encode_jcs(self.to_json())

    def recompute_cid(self) -> str:
        return _blake3_512_of(self.to_jcs_string().encode("utf-8"))


@dataclass(frozen=True)
class BoundaryRealization(_DecoratableRealization):
    """A library or API boundary realization."""

    library: str
    api: str
    boundary_contract_cid: str

    def to_json(self) -> dict[str, str]:
        return {
            "api": self.api,
            "boundary_contract_cid": self.boundary_contract_cid,
            "kind": "boundary",
            "library": self.library,
        }

    def to_jcs_string(self) -> str:
        return _encode_jcs(self.to_json())

    def recompute_cid(self) -> str:
        return _blake3_512_of(self.to_jcs_string().encode("utf-8"))


@dataclass(frozen=True)
class SugarCarrierRealization(_DecoratableRealization):
    """A realization carried implicitly by concept-citation comment sugar."""

    def to_json(self) -> dict[str, str]:
        return {"kind": "sugar-carrier"}

    def to_jcs_string(self) -> str:
        return _encode_jcs(self.to_json())

    def recompute_cid(self) -> str:
        return _blake3_512_of(self.to_jcs_string().encode("utf-8"))


RealizationMemento: TypeAlias = (
    FirstClassRealization
    | CompositionRealization
    | BoundaryRealization
    | SugarCarrierRealization
)


def tag_first_class(
    op_name: str,
    syntactic_pattern: str,
    surface_locator: str,
) -> FirstClassRealization:
    """Tag a concept op with a language-native syntactic form.

    Example:
        >>> realization = tag_first_class(
        ...     "concept:add",
        ...     "${x} + ${y}",
        ...     "binary-operator",
        ... )
        >>> realization.to_json()["kind"]
        'first-class'

        >>> @tag_first_class("concept:add", "${x} + ${y}", "binary-operator")
        ... def add(x, y):
        ...     return x + y
    """
    _require_text(op_name, "op_name")
    return FirstClassRealization(
        syntactic_pattern=_require_text(syntactic_pattern, "syntactic_pattern"),
        surface_locator=_require_text(surface_locator, "surface_locator"),
    )


def tag_composition(op_name: str, composition_tree: str) -> CompositionRealization:
    """Tag a concept op with a content-addressed composition tree.

    Example:
        >>> realization = tag_composition("concept:list", "blake3-512:" + "1" * 128)
        >>> realization.to_json()["kind"]
        'composition'

        >>> @tag_composition("concept:list", "blake3-512:" + "1" * 128)
        ... def build_list(xs):
        ...     return list(xs)
    """
    _require_text(op_name, "op_name")
    return CompositionRealization(
        composition_tree_cid=_require_text(composition_tree, "composition_tree"),
    )


def tag_boundary(
    op_name: str,
    library: str,
    api: str,
    boundary_contract_cid: str,
) -> BoundaryRealization:
    """Tag a concept op with a library or API boundary contract.

    Example:
        >>> realization = tag_boundary(
        ...     "concept:http-request",
        ...     "python-requests",
        ...     "requests.get",
        ...     "blake3-512:" + "2" * 128,
        ... )
        >>> realization.to_json()["kind"]
        'boundary'

        >>> @tag_boundary("concept:http-request", "python-requests", "requests.get", "blake3-512:" + "2" * 128)
        ... def get(url):
        ...     return requests.get(url)
    """
    _require_text(op_name, "op_name")
    return BoundaryRealization(
        library=_require_text(library, "library"),
        api=_require_text(api, "api"),
        boundary_contract_cid=_require_text(
            boundary_contract_cid, "boundary_contract_cid"
        ),
    )


def tag_sugar_carrier(op_name: str) -> SugarCarrierRealization:
    """Tag a concept op as a concept-citation sugar carrier.

    Example:
        >>> realization = tag_sugar_carrier("concept:free")
        >>> realization.to_json()["kind"]
        'sugar-carrier'

        >>> @tag_sugar_carrier("concept:free")
        ... def no_native_free(ptr):
        ...     return ptr
    """
    _require_text(op_name, "op_name")
    return SugarCarrierRealization()


def _require_text(value: str, field: str) -> str:
    if not isinstance(value, str):
        raise RealizationTagError(f"{field} must be str")
    if not value:
        raise RealizationTagError(f"{field} must be non-empty")
    return value


def _encode_jcs(value: JsonValue) -> str:
    out: list[str] = []
    _encode_value(value, out)
    return "".join(out)


def _encode_value(value: JsonValue, out: list[str]) -> None:
    if value is None:
        out.append("null")
    elif isinstance(value, bool):
        out.append("true" if value else "false")
    elif isinstance(value, int) and not isinstance(value, bool):
        out.append(str(value))
    elif isinstance(value, str):
        _encode_string(value, out)
    elif isinstance(value, Mapping):
        out.append("{")
        for index, key in enumerate(sorted(value.keys())):
            if not isinstance(key, str):
                raise TypeError("canonical JSON object keys must be str")
            if index:
                out.append(",")
            _encode_string(key, out)
            out.append(":")
            _encode_value(value[key], out)
        out.append("}")
    elif isinstance(value, Sequence):
        out.append("[")
        for index, item in enumerate(value):
            if index:
                out.append(",")
            _encode_value(item, out)
        out.append("]")
    else:
        raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def _encode_string(value: str, out: list[str]) -> None:
    out.append('"')
    for char in value:
        codepoint = ord(char)
        if char == '"':
            out.append('\\"')
        elif char == "\\":
            out.append("\\\\")
        elif codepoint < 0x20:
            out.append("\\u00")
            out.append("0123456789abcdef"[(codepoint >> 4) & 0xF])
            out.append("0123456789abcdef"[codepoint & 0xF])
        else:
            out.append(char)
    out.append('"')


def _blake3_512_of(data: bytes) -> str:
    try:
        import blake3

        digest = blake3.blake3(data).digest(length=64)
        return "blake3-512:" + digest.hex()
    except ModuleNotFoundError:
        b3sum = shutil.which("b3sum")
        if b3sum is None:
            raise RuntimeError(
                "BLAKE3 support requires the blake3 module or b3sum"
            ) from None
        process = subprocess.run(
            [b3sum, "--length", "64", "--no-names", "-"],
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        return "blake3-512:" + process.stdout.decode("utf-8").strip()
