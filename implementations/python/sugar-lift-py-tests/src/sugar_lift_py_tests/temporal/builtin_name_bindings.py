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


def builtin_name_temporal():
    """Construct lexical coordinates for Python's builtin name values."""
    from sugar_lift_py_tests.floor import (
        BlockValue,
        BuiltinExceptionClassValue,
        ClassValue,
        SymbolicValue,
    )
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.temporal.temporal_context import TemporalContext

    # Construct the raw root directly. TemporalContext.empty() delegates here
    # so every ordinary lexical scope starts with this one builtin floor.
    temporal = TemporalContext()
    for name in sorted(builtin_callable_names()):
        temporal = temporal.bind_value(
            name,
            ClassValue(name=name, bases=(), record=BlockValue(())),
        )
    for name in sorted(builtin_constant_names()):
        temporal = temporal.bind_value(
            name,
            SymbolicValue(ctor("python:builtin", [str_const(name)])),
        )
    # Override generic callable coordinates with exact builtins ownership. No
    # exception constructor object is imported or executed to establish it.
    for name in sorted(BUILTIN_EXCEPTION_NAMES):
        temporal = temporal.bind_value(
            name,
            BuiltinExceptionClassValue(name=name, bases=(), record=BlockValue(())),
        )
    return temporal
