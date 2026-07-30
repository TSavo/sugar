from __future__ import annotations

import builtins

# Language-owned exception identities are explicit rather than discovered by
# executing/importing their constructors. This vocabulary is the builtins
# exception hierarchy supported by the Python kit; lexical rebinding replaces
# the corresponding temporal floor normally.
BUILTIN_EXCEPTION_NAMES = frozenset(
    {
        "ArithmeticError",
        "AssertionError",
        "AttributeError",
        "BaseException",
        "BaseExceptionGroup",
        "BlockingIOError",
        "BrokenPipeError",
        "BufferError",
        "BytesWarning",
        "ChildProcessError",
        "ConnectionAbortedError",
        "ConnectionError",
        "ConnectionRefusedError",
        "ConnectionResetError",
        "DeprecationWarning",
        "EOFError",
        "EncodingWarning",
        "EnvironmentError",
        "Exception",
        "ExceptionGroup",
        "FileExistsError",
        "FileNotFoundError",
        "FloatingPointError",
        "FutureWarning",
        "GeneratorExit",
        "ImportError",
        "ImportWarning",
        "IndentationError",
        "IndexError",
        "InterruptedError",
        "IOError",
        "IsADirectoryError",
        "KeyError",
        "KeyboardInterrupt",
        "LookupError",
        "MemoryError",
        "ModuleNotFoundError",
        "NameError",
        "NotADirectoryError",
        "NotImplementedError",
        "OSError",
        "OverflowError",
        "PendingDeprecationWarning",
        "PermissionError",
        "ProcessLookupError",
        "RecursionError",
        "ReferenceError",
        "ResourceWarning",
        "RuntimeError",
        "RuntimeWarning",
        "StopAsyncIteration",
        "StopIteration",
        "SyntaxError",
        "SyntaxWarning",
        "SystemError",
        "SystemExit",
        "TabError",
        "TimeoutError",
        "TypeError",
        "UnboundLocalError",
        "UnicodeDecodeError",
        "UnicodeEncodeError",
        "UnicodeError",
        "UnicodeTranslateError",
        "UnicodeWarning",
        "UserWarning",
        "ValueError",
        "Warning",
        "ZeroDivisionError",
    }
)


def builtin_callable_names() -> frozenset[str]:
    """Return callable objects Python exposes in its builtin namespace."""
    return frozenset(
        name for name in dir(builtins) if callable(getattr(builtins, name))
    )


def builtin_constant_names() -> frozenset[str]:
    """Return the non-callable complement of Python's builtin namespace."""
    return frozenset(
        name for name in dir(builtins) if not callable(getattr(builtins, name))
    )


_EMPTY_BUILTIN_TEMPORAL = None


# Python owns its exception hierarchy, so the kit TRANSPORTS it rather than
# deriving or assuming it. Every entry names one builtin exception's immediate
# bases, restricted to ``BUILTIN_EXCEPTION_NAMES`` (the set is closed under
# this relation: no base falls outside it except ``object``).
#
# Before this table existed every builtin exception carried ``bases=()``, which
# is not "unknown" -- it is the positive claim that the class has no ancestry.
# ``except Exception`` therefore did not catch ``raise ValueError``, and
# ``issubclass(ValueError, Exception)`` reduced to ``False``. A fabricated
# empty ancestry is a decided answer standing in for vendor testimony; this is
# the testimony.
BUILTIN_EXCEPTION_BASES: dict[str, tuple[str, ...]] = {
    "ArithmeticError": ("Exception",),
    "AssertionError": ("Exception",),
    "AttributeError": ("Exception",),
    "BaseException": (),
    "BaseExceptionGroup": ("BaseException",),
    "BlockingIOError": ("OSError",),
    "BrokenPipeError": ("ConnectionError",),
    "BufferError": ("Exception",),
    "BytesWarning": ("Warning",),
    "ChildProcessError": ("OSError",),
    "ConnectionAbortedError": ("ConnectionError",),
    "ConnectionError": ("OSError",),
    "ConnectionRefusedError": ("ConnectionError",),
    "ConnectionResetError": ("ConnectionError",),
    "DeprecationWarning": ("Warning",),
    "EOFError": ("Exception",),
    "EncodingWarning": ("Warning",),
    "EnvironmentError": ("Exception",),
    "Exception": ("BaseException",),
    "ExceptionGroup": ("BaseExceptionGroup", "Exception"),
    "FileExistsError": ("OSError",),
    "FileNotFoundError": ("OSError",),
    "FloatingPointError": ("ArithmeticError",),
    "FutureWarning": ("Warning",),
    "GeneratorExit": ("BaseException",),
    "IOError": ("Exception",),
    "ImportError": ("Exception",),
    "ImportWarning": ("Warning",),
    "IndentationError": ("SyntaxError",),
    "IndexError": ("LookupError",),
    "InterruptedError": ("OSError",),
    "IsADirectoryError": ("OSError",),
    "KeyError": ("LookupError",),
    "KeyboardInterrupt": ("BaseException",),
    "LookupError": ("Exception",),
    "MemoryError": ("Exception",),
    "ModuleNotFoundError": ("ImportError",),
    "NameError": ("Exception",),
    "NotADirectoryError": ("OSError",),
    "NotImplementedError": ("RuntimeError",),
    "OSError": ("Exception",),
    "OverflowError": ("ArithmeticError",),
    "PendingDeprecationWarning": ("Warning",),
    "PermissionError": ("OSError",),
    "ProcessLookupError": ("OSError",),
    "RecursionError": ("RuntimeError",),
    "ReferenceError": ("Exception",),
    "ResourceWarning": ("Warning",),
    "RuntimeError": ("Exception",),
    "RuntimeWarning": ("Warning",),
    "StopAsyncIteration": ("Exception",),
    "StopIteration": ("Exception",),
    "SyntaxError": ("Exception",),
    "SyntaxWarning": ("Warning",),
    "SystemError": ("Exception",),
    "SystemExit": ("BaseException",),
    "TabError": ("IndentationError",),
    "TimeoutError": ("OSError",),
    "TypeError": ("Exception",),
    "UnboundLocalError": ("NameError",),
    "UnicodeDecodeError": ("UnicodeError",),
    "UnicodeEncodeError": ("UnicodeError",),
    "UnicodeError": ("ValueError",),
    "UnicodeTranslateError": ("UnicodeError",),
    "UnicodeWarning": ("Warning",),
    "UserWarning": ("Warning",),
    "ValueError": ("Exception",),
    "Warning": ("Exception",),
    "ZeroDivisionError": ("ArithmeticError",),
}


def builtin_name_temporal():
    """Return the shared immutable lexical floor for Python's builtin names.

    The empty temporal is a pure value: every ordinary scope starts with the
    same builtin bindings. Constructing it once keeps module-seed frames from
    reallocating the entire builtin surface on every dig.module_seed entry
    (stata/typing module_seed cascade tip).
    """
    global _EMPTY_BUILTIN_TEMPORAL
    if _EMPTY_BUILTIN_TEMPORAL is not None:
        return _EMPTY_BUILTIN_TEMPORAL

    from sugar_lift_py_tests.floor import (
        BlockValue,
        BuiltinExceptionClassValue,
        BuiltinDictClassValue,
        BuiltinObjectClassValue,
        BuiltinSemanticCallable,
        ClassValue,
        SymbolicValue,
    )
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.temporal.temporal_context import TemporalContext

    # Construct the raw root directly. TemporalContext.empty() delegates here
    # so every ordinary lexical scope starts with this one builtin floor.
    temporal = TemporalContext()
    for name in sorted(builtin_callable_names()):
        if name == "object":
            continue
        temporal = temporal.bind_value(
            name,
            ClassValue(name=name, bases=(), record=BlockValue(())),
        )
    # ``object`` is Python language vocabulary, not a host-discovered callable.
    # Its typed owner remains enrolled even when host builtin enumeration is
    # absent or substituted.
    temporal = temporal.bind_value(
        "object",
        BuiltinObjectClassValue(name="object", bases=(), record=BlockValue(())),
    )
    # ``dict`` is a builtin class with receiver-state semantics, not merely a
    # callable coordinate.  Its distinct Floor type is what source subclasses
    # authenticate and transport; downstream code never admits by spelling.
    temporal = temporal.bind_value(
        "dict",
        BuiltinDictClassValue(operation="python.dict.construct"),
    )
    for name in sorted(builtin_constant_names()):
        temporal = temporal.bind_value(
            name,
            SymbolicValue(ctor("python:builtin", [str_const(name)])),
        )
    # Override generic callable coordinates with exact builtins ownership. No
    # exception constructor object is imported or executed to establish it.
    # Bind exception classes in ancestry order so every base is already the
    # exact ClassValue its subclass points at -- one object per class, so the
    # `candidate is supertype` walk in ClassValue.test_python_subtype answers
    # on identity rather than on a re-spelled copy.
    exception_values: dict[str, BuiltinExceptionClassValue] = {}

    def exception_value(name: str) -> BuiltinExceptionClassValue:
        existing = exception_values.get(name)
        if existing is not None:
            return existing
        bases = tuple(exception_value(base) for base in BUILTIN_EXCEPTION_BASES[name])
        value = BuiltinExceptionClassValue(
            name=name, bases=bases, record=BlockValue(())
        )
        exception_values[name] = value
        return value

    for name in sorted(BUILTIN_EXCEPTION_NAMES):
        temporal = temporal.bind_value(name, exception_value(name))
    temporal = temporal.bind_value(
        "issubclass", BuiltinSemanticCallable(operation="python.issubclass")
    )
    temporal = temporal.bind_value(
        "isinstance", BuiltinSemanticCallable(operation="python.isinstance")
    )
    temporal = temporal.bind_value(
        "len", BuiltinSemanticCallable(operation="python.len")
    )
    temporal = temporal.bind_value(
        "enumerate", BuiltinSemanticCallable(operation="python.enumerate.construct")
    )
    temporal = temporal.bind_value(
        "super", BuiltinSemanticCallable(operation="python.super.construct")
    )
    temporal = temporal.bind_value(
        "set", BuiltinSemanticCallable(operation="python.set.construct")
    )
    temporal = temporal.bind_value(
        "tuple", BuiltinSemanticCallable(operation="python.tuple.construct")
    )
    _EMPTY_BUILTIN_TEMPORAL = temporal
    return temporal
