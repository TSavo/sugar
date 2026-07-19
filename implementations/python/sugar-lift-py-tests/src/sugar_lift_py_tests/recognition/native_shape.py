"""Recognition of imported native source shapes.

Sugars consume these structural shape claims. They never reinterpret qualified
vendor spellings themselves. Lives under ``recognition/`` — not ``factory/`` —
so the factory boundary stays select-or-panic only.
"""

from __future__ import annotations

from enum import Enum, auto


class NativeShape(Enum):
    INDEX_SEQUENCE = auto()
    INDEX_PRESERVING = auto()
    OPTION_NAMESPACE = auto()
    OPTION_REGISTER = auto()
    OPTION_UPDATE = auto()
    BYTES_COERCER = auto()
    INTEGER_ADD = auto()
    INTEGER_FLOOR_DIVIDE = auto()
    INTEGER_MAXIMUM = auto()
    INTEGER_MINIMUM = auto()
    INTEGER_MODULO = auto()
    INTEGER_MULTIPLY = auto()
    INTEGER_POWER = auto()
    INTEGER_SUBTRACT = auto()
    REAL_DIVIDE = auto()
    ITERATOR = auto()
    RANGE_ARRAY = auto()
    RANDOM_INTEGER_ARRAY = auto()
    NUMPY_ISNAT = auto()
    SOURCE_AUTHENTICATED_CALLABLE = auto()
    NUMPY_ALL = auto()
    NUMPY_ITER_GOTO1D = auto()
    NUMPY_NPYITER_DELAYED_BUFALLOC = auto()
    NUMPY_NPYITER_INDEX = auto()
    NUMPY_SCALARTYPE_INDEX = auto()
    NUMPY_EDIFF1D = auto()
    NUMPY_FINFO = auto()
    NUMPY_PROD = auto()
    NUMPY_RESULT_TYPE = auto()
    NUMPY_ARRAY_NAMESPACE = auto()
    NUMPY_EQUAL = auto()
    NUMPY_LESS_EQUAL = auto()
    NUMPY_GREATER = auto()
    NUMPY_GREATER_EQUAL = auto()
    NUMPY_LESS = auto()
    NUMPY_NOT_EQUAL = auto()
    NUMPY_SUPPORT_CALLABLE = auto()
    NEVER_SUPPRESSING_MANAGER = auto()
    ASSERTING_MANAGER = auto()
    CLASS_IDENTITY_DECORATOR = auto()
    IMPLEMENTATION_PRESERVING_DECORATOR = auto()
    FIXTURE_DECORATOR = auto()
    # SQLALCHEMY_ORM_REGISTRY retired (#5603): hard-coded sqlalchemy.orm.registry /
    # as_declarative / mapped coordinates were illegal logo branches — deleted.
    # ClassDef identity for those shapes stays loud until an external kit contract.
    GENERIC_CLASS = auto()
    PYDANTIC_BASE_MODEL = auto()
    PYDANTIC_EXTRA_ALLOW_CLASS_OPTION = auto()
    REGEX_PATTERN = auto()
    PATH = auto()
    NUMPY_ARRAY = auto()
    NUMPY_GENERATOR = auto()


# Language / builtin protocol coordinates only (#5603).
# Vendor-root strings (numpy/pandas/sqlalchemy/pydantic/pytest/requests/…)
# must NOT appear here as hard-coded construction keys — those are either
# externally-loaded kit contracts or illegal logo branches. Enum members for
# retired vendor shapes may remain for API stability; tables must not.
_CALL_SHAPES = {
    # Language / builtin managers and constructors.
    "open": NativeShape.NEVER_SUPPRESSING_MANAGER,
    "builtins.open": NativeShape.NEVER_SUPPRESSING_MANAGER,
    "contextlib.closing": NativeShape.NEVER_SUPPRESSING_MANAGER,
    "re.compile": NativeShape.REGEX_PATTERN,
    "pathlib.Path": NativeShape.PATH,
    # Bare leaf spellings that are not vendor-rooted module paths.
    "as_unit": NativeShape.INDEX_PRESERVING,
    "uniform": NativeShape.NUMPY_SUPPORT_CALLABLE,
    "strip": NativeShape.NUMPY_SUPPORT_CALLABLE,
    "selectedrealkind": NativeShape.NUMPY_SUPPORT_CALLABLE,
    "op": NativeShape.NUMPY_SUPPORT_CALLABLE,
    "iter_goto1d": NativeShape.NUMPY_ITER_GOTO1D,
    "npyiter_has_delayed_bufalloc": NativeShape.NUMPY_NPYITER_DELAYED_BUFALLOC,
    "npyiter_has_index": NativeShape.NUMPY_NPYITER_INDEX,
}

_NEVER_SUPPRESSING_MANAGERS = {
    name: True
    for name in (
        "open",
        "builtins.open",
        "contextlib.closing",
    )
}

# Language-level identity decorators only (stdlib / typing_extensions PEP 702).
_IDENTITY_DECORATORS = {
    key: True
    for key in (
        ("dataclasses", "dataclass"),
        ("warnings", "deprecated"),
        ("typing_extensions", "deprecated"),
    )
}

_NATIVE_DECORATORS = {
    "functools.wraps": NativeShape.IMPLEMENTATION_PRESERVING_DECORATOR,
}

# Fixture providers: no hard-coded logo. Stay loud until an explicit kit/bridge
# contract loads a fixture protocol (#5603). Empty by construction.
_FIXTURE_DECORATORS: dict[str, NativeShape] = {}

# Instance class-decorators derived from vendor shapes are retired until those
# shapes arrive via external contract (not hard-coded coordinates).
_NATIVE_INSTANCE_CLASS_DECORATORS: dict[
    tuple[NativeShape, str], NativeShape
] = {}

_NATIVE_INSTANCE_CALLS = {
    (NativeShape.REGEX_PATTERN, "search"): "re.Pattern.search",
    (NativeShape.PATH, "resolve"): "pathlib.Path.resolve",
}

_CLASS_IMPORT_SHAPES = {
    ("typing", "Generic"): NativeShape.GENERIC_CLASS,
}

_CLASS_OPTION_SHAPES: dict[tuple[NativeShape, str | None, object], NativeShape] = {}

# Language / stdlib module names only — not vendor packages.
_MODULE_NAMES = {
    name: True
    for name in (
        "unittest",
        "mock",
        "typing",
        "types",
        "sys",
        "os",
        "re",
        "json",
        "math",
        "abc",
        "functools",
        "itertools",
        "collections",
        "dataclasses",
        "pathlib",
        "io",
        "copy",
        "struct",
        "base64",
        "hashlib",
        "hmac",
        "binascii",
        "zlib",
        "uuid",
        "datetime",  # language-level stdlib; auditor may still root-match "datetime"
        "time",
        "random",
        "string",
        "warnings",
        "contextlib",
        "inspect",
        "operator",
        "enum",
        "secrets",
        "urllib",
        "http",
        "email",
        "logging",
        "pickle",
    )
}


def recognize_native_call(target: str | None) -> NativeShape | None:
    return _CALL_SHAPES.get(target)


def has_native_shape(target: str | None, shape: NativeShape) -> bool:
    if shape is NativeShape.NEVER_SUPPRESSING_MANAGER:
        return bool(_NEVER_SUPPRESSING_MANAGERS.get(target))
    return recognize_native_call(target) is shape


def recognize_source_callable(value) -> NativeShape | None:
    """Authenticate a callee from resolved source provenance, never spelling."""
    if getattr(value, "body", None) is not None and getattr(value, "name", None):
        return NativeShape.SOURCE_AUTHENTICATED_CALLABLE
    return None


def recognizes_module_name(name: str) -> bool:
    return bool(_MODULE_NAMES.get(name))


def recognizes_identity_decorator(module: str, name: str) -> bool:
    return (
        recognize_native_class_decorator(f"{module}.{name}")
        is NativeShape.CLASS_IDENTITY_DECORATOR
    )


def recognize_native_class_decorator(target: str | None) -> NativeShape | None:
    """Recognize a class decorator only at an authenticated import coordinate."""

    if target is None:
        return None
    module, separator, name = target.rpartition(".")
    if not separator or not _IDENTITY_DECORATORS.get((module, name)):
        return None
    return NativeShape.CLASS_IDENTITY_DECORATOR


def recognize_native_instance_class_decorator(
    receiver: NativeShape,
    member: str,
) -> NativeShape | None:
    """Recognize a class decorator projected from an authenticated instance."""

    return _NATIVE_INSTANCE_CLASS_DECORATORS.get((receiver, member))


def recognize_native_instance_call(
    receiver: NativeShape,
    member: str,
) -> str | None:
    """Resolve a member call from its authenticated constructed receiver shape."""

    return _NATIVE_INSTANCE_CALLS.get((receiver, member))


def recognize_native_decorator(target: str | None) -> NativeShape | None:
    """Recognize a decorator only from its authenticated import coordinate."""

    return _NATIVE_DECORATORS.get(target)


def recognize_native_fixture_decorator(target: str | None) -> NativeShape | None:
    """Fixture protocol table is empty until a kit/bridge contract loads it.

    #5603: no hard-coded pytest/vendor fixture logos. Missing → None → loud.
    """

    return _FIXTURE_DECORATORS.get(target) if target is not None else None


def recognize_native_class_import(module: str, name: str) -> NativeShape | None:
    """Recognize a class base only from its authenticated import coordinate."""

    return _CLASS_IMPORT_SHAPES.get((module, name))


def recognize_native_class_option(
    base_shape: NativeShape,
    keyword: str | None,
    value: object,
) -> NativeShape | None:
    """Recognize an exact class option contract on an authenticated base."""

    return _CLASS_OPTION_SHAPES.get((base_shape, keyword, value))
