"""Recognition of imported native source shapes.

Sugars consume these semantic shape claims.  They never reinterpret qualified
vendor spellings themselves.
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
    NEVER_SUPPRESSING_MANAGER = auto()
    ASSERTING_MANAGER = auto()
    CLASS_IDENTITY_DECORATOR = auto()


_CALL_SHAPES = {
    "pandas.DatetimeIndex": NativeShape.INDEX_SEQUENCE,
    "pandas.Index": NativeShape.INDEX_SEQUENCE,
    "pandas.IntervalIndex": NativeShape.INDEX_SEQUENCE,
    "pandas.IntervalIndex.from_breaks": NativeShape.INDEX_SEQUENCE,
    "pandas.MultiIndex.from_arrays": NativeShape.INDEX_SEQUENCE,
    "pandas.PeriodIndex": NativeShape.INDEX_SEQUENCE,
    "pandas.RangeIndex": NativeShape.INDEX_SEQUENCE,
    "pandas.core.indexes.api.Index": NativeShape.INDEX_SEQUENCE,
    "pandas.TimedeltaIndex": NativeShape.INDEX_SEQUENCE,
    "pandas.core.indexes.datetimes.date_range": NativeShape.INDEX_SEQUENCE,
    "pandas.core.indexes.period.period_range": NativeShape.INDEX_SEQUENCE,
    "pandas.core.indexes.timedeltas.timedelta_range": NativeShape.INDEX_SEQUENCE,
    "as_unit": NativeShape.INDEX_PRESERVING,
    "pandas._config.config.options": NativeShape.OPTION_NAMESPACE,
    "pandas._config.config.register_option": NativeShape.OPTION_REGISTER,
    "pandas._config.config.set_option": NativeShape.OPTION_UPDATE,
    "pandas._config.config.reset_option": NativeShape.OPTION_UPDATE,
    "numpy._utils.asbytes": NativeShape.BYTES_COERCER,
    "numpy.add": NativeShape.INTEGER_ADD,
    "numpy.floor_divide": NativeShape.INTEGER_FLOOR_DIVIDE,
    "numpy.maximum": NativeShape.INTEGER_MAXIMUM,
    "numpy.minimum": NativeShape.INTEGER_MINIMUM,
    "numpy.mod": NativeShape.INTEGER_MODULO,
    "numpy.multiply": NativeShape.INTEGER_MULTIPLY,
    "numpy.power": NativeShape.INTEGER_POWER,
    "numpy.subtract": NativeShape.INTEGER_SUBTRACT,
    "numpy.divide": NativeShape.REAL_DIVIDE,
    "numpy.nditer": NativeShape.ITERATOR,
    "numpy.arange": NativeShape.RANGE_ARRAY,
    "numpy.random.randint": NativeShape.RANDOM_INTEGER_ARRAY,
    "open": NativeShape.NEVER_SUPPRESSING_MANAGER,
    "builtins.open": NativeShape.NEVER_SUPPRESSING_MANAGER,
    "contextlib.closing": NativeShape.NEVER_SUPPRESSING_MANAGER,
    "numpy.testing.assert_raises": NativeShape.ASSERTING_MANAGER,
    "numpy.testing._private.utils.assert_raises": NativeShape.ASSERTING_MANAGER,
    "numpy.testing.assert_raises_regex": NativeShape.ASSERTING_MANAGER,
    "numpy.testing._private.utils.assert_raises_regex": NativeShape.ASSERTING_MANAGER,
    "pandas._testing.external_error_raised": NativeShape.ASSERTING_MANAGER,
}

_NEVER_SUPPRESSING_MANAGERS = {
    name: True
    for name in (
        "open",
        "builtins.open",
        "contextlib.closing",
        "numpy.errstate",
        "numpy.nditer",
        "pandas.HDFStore",
        "pandas._testing.assert_produces_warning",
        "pandas._testing.raises_chained_assignment_error",
        "pandas.option_context",
        "pytest.warns",
    )
}

_IDENTITY_DECORATORS = {
    key: True
    for key in (
        ("dataclasses", "dataclass"),
        ("pandas.core.indexes.extension", "inherit_names"),
        ("pandas.util._decorators", "set_module"),
        ("pandas.api.extensions", "register_dataframe_accessor"),
        ("pandas.api.extensions", "register_index_accessor"),
        ("pandas.api.extensions", "register_series_accessor"),
    )
}

_MODULE_NAMES = {
    name: True
    for name in (
        "pytest",
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
        "datetime",
        "time",
        "random",
        "string",
        "warnings",
        "contextlib",
        "inspect",
        "operator",
        "enum",
        "numpy",
        "pandas",
        "itsdangerous",
        "requests",
        "freezegun",
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


def recognizes_module_name(name: str) -> bool:
    return bool(_MODULE_NAMES.get(name))


def recognizes_identity_decorator(module: str, name: str) -> bool:
    return bool(_IDENTITY_DECORATORS.get((module, name)))
