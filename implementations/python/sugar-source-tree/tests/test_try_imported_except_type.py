"""Zero-name (dotted) except types authenticate through the same closed import
identity that ``raise re.error(...)`` operands ride.

``except re.error`` is the exact wall pytest's ``AbstractRaises.__init__``
force-floors (``try: re.compile(match) / except re.error as e``) when a with
site constructs ``pytest.raises(..., match=...)``.  Two edits make it hold:
the except-TYPE expression is now enrolled as an import value-use (so its head
is import-bound), and ``Try._construct_sugar`` authenticates a non-Name handler
type through ``exception_type_identity``.  A dotted head that is NOT
import-bound (an instance/param attribute) has no identity: its match is the
retained question, never decided.
"""

import tempfile
from pathlib import Path

from sugar_lift_py_tests.ir import ctor, str_const
from with_resolution_fixture import source_file_with_preconstruction


def _function(src: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return next(source_file_with_preconstruction(Path(path)).functions())


def _except_type_node(function, attr: str):
    return next(
        node
        for node in function.walk()
        if node.kind == "Attribute" and getattr(node, "attr", None) == attr
    )


_TRUTHFUL = (
    "import re\n"
    "\n"
    "def f(pattern):\n"
    "    try:\n"
    "        compiled = re.compile(pattern)\n"
    "    except re.error as exc:\n"
    "        compiled = exc\n"
    "    return compiled\n"
)


def test_except_type_head_is_now_import_enrolled() -> None:
    # The re.error head inside the except clause is enrolled as an import
    # value-use, so its dotted identity authenticates (previously None).
    fn = _function(_TRUTHFUL)
    node = _except_type_node(fn, "error")
    identity = fn.unit.exception_type_identity(node)
    assert identity == ctor(
        "python:exception_type_identity",
        [str_const("import"), str_const("re.error")],
    )


def test_dotted_import_bound_except_type_constructs() -> None:
    # Construction (Try._construct_sugar) no longer raises for re.error.
    _function(_TRUTHFUL).sugar()


_LIAR = (
    "def f(registry):\n"
    "    try:\n"
    "        registry.load()\n"
    "    except registry.Error as exc:\n"
    "        registry = exc\n"
    "    return registry\n"
)


def test_non_import_bound_dotted_except_type_is_retained_never_authenticated() -> None:
    """A dotted head that is not import-bound (a parameter attribute) has no
    authenticated identity, so nothing decides the match: the arm is the
    retained question ``adt.is_python_type(raised, handler)``
    (``authenticated_exception_matching``) over the handler value read, and
    the miss face still raises.  (It once refused by name at construction;
    main carries the undecided question instead, #7757.)"""
    from sugar_lift_py_tests.outcome import Completed, ExitSet

    fn = _function(_LIAR)
    # The param head is not import-bound: no authenticated identity ...
    assert fn.unit.exception_type_identity(
        _except_type_node(fn, "Error")
    ) is None
    # ... and the match is retained rather than decided from a fabricated one.
    out = fn.sugar().desugar()
    assert "adt.is_python_type" in repr(out)
    halts = list(out.halts())
    for face in out.exits:
        if not isinstance(face, Completed):
            continue
        record = getattr(face.value, "record", None)
        if record is not None:
            halts.extend(
                halt
                for entry in record.contribution()
                if isinstance(entry, ExitSet) and entry.halts() == entry.exits
                for halt in entry.halts()
            )
    assert halts, "the miss face of the retained match must still raise"
