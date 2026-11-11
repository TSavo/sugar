"""A loop over an iterable whose contents nothing decided (#7742, #7676).

A dependency frame reads a mutable module global as the pinned object itself
(``python:mutable_global_pin``): anything may have mutated it before the
function runs.  ``pandas.io.common.infer_compression`` reads::

    for extension, compression in extension_to_compression.items():
        if filepath_or_buffer.lower().endswith(extension):
            return compression

``.items()`` on that pin is a call nobody projected.  Such an iterable (or the
pin itself) takes the opaque loop recurrence -- the body runs an undecided
number of times -- and iterating it may raise (``UndecidedIteration``), never a
construction refusal for an iterator protocol it cannot own.  A literal, and a
call whose body is projected, keep their own iterator law.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.outcome import Halted, outcome_to_exitset
from sugar_source_tree.nodes import FunctionDef

from test_contextmanager_generator_protocol import _imported

_IMPL = (
    "table = {'.gz': 'gzip', '.bz2': 'bz2'}\n"
    "def boom():\n"
    "    raise KeyError(1)\n"
    "def infer(p):\n"
    "    for ext in ITERABLE:\n"
    "        if p.endswith(ext):\n"
    "            return ext\n"
    "    return None\n"
    "class M:\n"
    "    def __enter__(self):\n"
    "        infer('a.gz')\n"
    "        return 1\n"
    "    def __exit__(self, *exc):\n"
    "        return False\n"
    "def cm():\n"
    "    return M()\n"
)


def _owners(tmp_path: Path, iterable: str):
    tree, _with_node = _imported(
        tmp_path, _IMPL.replace("ITERABLE", iterable), "pass", contextlib_enrolled=False
    )
    func = next(
        n for n in tree.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    exits = outcome_to_exitset(func.sugar().desugar()).exits
    halts = [face for face in exits if isinstance(face, Halted)]
    names = {getattr(face.effect, "exception_name", None) for face in halts}
    return {
        str(getattr(face.effect, "producer_node_owner", None)) for face in halts
    } | {f"raises:{name}" for name in names if name}


def test_a_call_on_a_mutable_global_is_iterated_opaquely(tmp_path):
    assert "UndecidedIteration" in _owners(tmp_path, "table.items()")


def test_a_mutable_global_itself_is_iterated_opaquely(tmp_path):
    # Pair A, truthful: ``table`` is a mutable global (a dict): its contents
    # are not the module body's literal.
    assert "UndecidedIteration" in _owners(tmp_path, "table")


def test_an_immutable_global_keeps_its_own_iterator_law(tmp_path):
    # Pair A, lying: the same loop over a global that cannot be mutated (a
    # string): its contents are decided, it is never undecided.
    (tmp_path / "t").mkdir()
    tree_source = _IMPL.replace(
        "table = {'.gz': 'gzip', '.bz2': 'bz2'}\n",
        "table = '.gz'\n",
    )
    tree, _w = _imported(
        tmp_path / "t",
        tree_source.replace("ITERABLE", "table"),
        "pass",
        contextlib_enrolled=False,
    )
    func = next(
        n for n in tree.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    # Its own (decided-string) iterator law answers -- here still unwritten,
    # so it refuses by name -- never the undecided recurrence.
    import pytest

    with pytest.raises(BaseException, match="LoopRecurrenceSugar:StringValue"):
        outcome_to_exitset(func.sugar().desugar())


def _module_rows(tmp_path: Path, source: str):
    """Owners and exception names of every halt ``f`` can leave by."""
    from test_contextlib_suppress_source_exit_faces import _corpus, _open

    source_file = _open(_corpus(tmp_path, source))
    func = next(
        n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    exits = outcome_to_exitset(func.sugar().desugar()).exits
    halts = [face for face in exits if isinstance(face, Halted)]
    return (
        {str(getattr(face.effect, "producer_node_owner", None)) for face in halts}
        | {f"raises:{getattr(face.effect, 'exception_name', None)}" for face in halts},
        len(exits) - len(halts),
    )


def test_an_iterable_that_always_raises_is_never_a_completed_loop(tmp_path):
    # A halt is never dropped: the iterable's raise is the loop's only outcome.
    source = (
        "def boom():\n"
        "    raise KeyError(1)\n"
        "def f():\n"
        "    for x in boom():\n"
        "        pass\n"
        "    return 7\n"
    )
    owners, completed = _module_rows(tmp_path, source)
    assert "raises:KeyError" in owners
    assert completed == 0


def test_an_undecided_iterable_keeps_every_face(tmp_path):
    # The iterable call may raise (unknown callee), iterating it may raise,
    # and the body may raise on a trip: all three stay, beside the completion.
    source = (
        "def f(n):\n"
        "    for x in mystery():\n"
        "        if x:\n"
        "            raise ValueError(n)\n"
        "    return 7\n"
    )
    owners, completed = _module_rows(tmp_path, source)
    assert "UndecidedIteration" in owners
    assert "UnknownCallee:mystery" in owners
    assert "raises:ValueError" in owners
    assert completed >= 1


_CALLEE = (
    "{definition}"
    "def f(n):\n"
    "    for x in mystery():\n"
    "        pass\n"
    "    return 7\n"
)


def test_a_bodiless_call_result_is_iterated_opaquely(tmp_path):
    # Pair B, truthful: ``mystery`` is bound nowhere, so the call has no body.
    owners, _completed = _module_rows(tmp_path, _CALLEE.format(definition=""))
    assert "UndecidedIteration" in owners


def test_a_call_with_a_projected_body_is_not_undecided(tmp_path):
    # Pair B, lying: the same call, with ``mystery`` defined in the module, so
    # its body is projected: never read as an undecided call result (its own
    # iterator law, still unwritten for a call value, keeps refusing by name).
    import pytest

    with pytest.raises(BaseException, match="LoopRecurrenceSugar"):
        _module_rows(
            tmp_path, _CALLEE.format(definition="def mystery():\n    return [1]\n")
        )
