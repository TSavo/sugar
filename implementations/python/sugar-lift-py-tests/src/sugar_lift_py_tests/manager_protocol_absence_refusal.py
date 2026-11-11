"""What CPython raises when a non-manager object heads a sync ``with``.

``with x:`` looks ``__enter__`` up on ``type(x)`` (its MRO, never the
instance, never ``__getattr__``).  When it is missing the ``with`` statement
raises ``TypeError`` before anything is entered; when ``__enter__`` is present
and ``__exit__`` is missing it raises a ``TypeError`` with a different text.

THE TYPE AND THE TEXT ARE OBSERVED, NOT TRANSCRIBED (the law of
``generator_object_with_refusal``): this module runs the interpreter's own
``with`` once over an object of a fresh class with the same ``__name__`` and the
same presence of ``__enter__`` / ``__exit__``, and records what it raised.

It also cites the two language-owned bases a source MRO may end in --
``object`` and ``abc.ABC`` (with its metaclass ``abc.ABCMeta``) -- by reading
their attribute sets from the running interpreter, so an absence proof never
invents what they define.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from sugar_lift_py_tests.floor.closed_operation_witness import PythonRuntimeIdentity

PROTOCOL_NAMES = ("__enter__", "__exit__")


@dataclass(frozen=True)
class NonManagerWithRefusalV1:
    """The observed ``with`` refusal for an object lacking a protocol method."""

    runtime: PythonRuntimeIdentity
    type_name: str
    has_enter: bool
    has_exit: bool
    exception_name: str
    message: str


@lru_cache(maxsize=64)
def observed_non_manager_with_refusal(
    type_name: str, *, has_enter: bool, has_exit: bool
) -> NonManagerWithRefusalV1:
    """Run ``with <instance>:`` once over a fresh ``type_name`` class."""
    if has_enter and has_exit:
        raise ValueError("an object with __enter__ and __exit__ is a manager")
    namespace = {}
    if has_enter:
        namespace["__enter__"] = lambda self: None
    if has_exit:
        namespace["__exit__"] = lambda self, *exc: None
    head = type(type_name, (), namespace)()
    entered = False
    try:
        with head:  # type: ignore[attr-defined]
            entered = True  # pragma: no cover
    except Exception as raised:  # the interpreter raises TypeError here
        if entered:  # pragma: no cover
            raise AssertionError("the with body ran over a non-manager")
        return NonManagerWithRefusalV1(
            runtime=PythonRuntimeIdentity.current(),
            type_name=type_name,
            has_enter=has_enter,
            has_exit=has_exit,
            exception_name=type(raised).__name__,
            message=str(raised),
        )
    raise AssertionError(
        "the interpreter entered an object lacking the context manager protocol; "
        "the refusal this module observes no longer exists"
    )


@dataclass(frozen=True)
class CitedLanguageBaseV1:
    """One interpreter-owned class a source MRO may end in, read live."""

    runtime: PythonRuntimeIdentity
    qualified_name: str
    # The class's own MRO, by qualified name, as the interpreter reports it.
    linearization: tuple[str, ...]
    # Which of ``__enter__`` / ``__exit__`` any class of that MRO defines.
    protocol_names: frozenset[str]
    # Attributes a body-less subclass gains from the base's metaclass and
    # ``__init_subclass__`` beyond the class statement's own, observed by
    # creating one.  An absence proof requires none of them is a protocol name.
    subclass_gains: frozenset[str]
    # Whether the metaclass overrides ``__call__`` (so construction could
    # return something that is not an instance of the class).
    metaclass_overrides_call: bool


def _qualified(cls) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


@lru_cache(maxsize=None)
def cited_language_base(qualified_name: str) -> CitedLanguageBaseV1 | None:
    """Cite ``builtins.object`` or ``abc.ABC`` from the running interpreter."""
    import abc

    classes = {"builtins.object": object, "abc.ABC": abc.ABC}
    cls = classes.get(qualified_name)
    if cls is None:
        return None
    present = frozenset(
        name for name in PROTOCOL_NAMES for base in cls.__mro__ if name in vars(base)
    )
    probe = type(cls)("_SugarAbsenceProbe", (cls,), {"__module__": __name__})
    statement_owned = {"__module__", "__qualname__", "__doc__", "__dict__", "__weakref__"}
    gains = frozenset(set(vars(probe)) - statement_owned)
    metaclass = type(cls)
    overrides_call = any(
        "__call__" in vars(meta) for meta in metaclass.__mro__ if meta is not type
        and meta is not object
    )
    return CitedLanguageBaseV1(
        runtime=PythonRuntimeIdentity.current(),
        qualified_name=qualified_name,
        linearization=tuple(_qualified(base) for base in cls.__mro__),
        protocol_names=present,
        subclass_gains=gains,
        metaclass_overrides_call=overrides_call,
    )


@lru_cache(maxsize=None)
def cited_identity_decorator(qualified_name: str) -> bool:
    """Whether a language-owned method decorator returns its argument unchanged.

    Only ``abc.abstractmethod`` is cited: applying it to a probe function is
    observed to return that same function, adding ``__isabstractmethod__``
    only.  A decorator that returned anything else could rebind a name.
    """
    import abc

    if qualified_name != "abc.abstractmethod":
        return False

    def probe():  # pragma: no cover - never called
        return None

    before = set(vars(probe))
    result = abc.abstractmethod(probe)
    return result is probe and set(vars(probe)) - before <= {"__isabstractmethod__"}
