"""Twins: a class body applies its methods' decorators where it runs (#7757).

Python runs ``d(m)`` for ``@d def m(self): ...`` when the class body runs,
at import.  The class body used to evaluate a method's decorator expressions
and apply none of them (``ClassDef._class_method_defaults``): a decorator
that raises was a dropped halt, so ``Box()`` after such a class completed
at lift and a lying claim that the import completes could read ``sat``.

Now every decorated class-body ``def`` is the one decorator application
(``_decorated_statement_sugar``), as a decorated ``def`` in a module or
function body is; a builtin ``staticmethod``, ``classmethod`` or
``property`` is answered there by the one builtin door (the descriptor
wrapping the function, ``builtin_decorator_application``).  The decorator's call is ``d``'s edge, joined at prove;
its halts are the class statement's, so the module's run.

Each twin goes through ``run_source_through_real_solver``: real ``sugar
mint`` then real ``sugar prove``.  One thing differs between the halves.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

# The decorator returns the function, or raises when the class body runs.
_RAISING = (
    "def d(fn):\n"
    "    {body}\n"
    "\n"
    "\n"
    "class Box:\n"
    "    @d\n"
    "    def pick(self):\n"
    "        return 1\n"
    "\n"
    "\n"
    "def test_box():\n"
    "    Box()\n"
    "    assert 1 == 1\n"
)


def test_a_class_whose_decorator_returns_is_never_unsat(tmp_path: Path) -> None:
    truthful = run_source_through_real_solver(
        tmp_path / "t", _RAISING.format(body="return fn")
    )

    assert truthful.verdict != "unsat", truthful.prove_doc


def test_a_class_whose_decorator_raises_never_reads_sat(tmp_path: Path) -> None:
    # The import raises at the class statement, so ``test_box`` never runs
    # to its assert: the claim that it does is a lie, never ``sat``.
    lying = run_source_through_real_solver(
        tmp_path / "l", _RAISING.format(body="raise ValueError('decorator')")
    )

    assert lying.verdict != "sat", lying.prove_doc


# The decorator returns a wrapper: the method a call reaches is the wrapper,
# never the plain body.
_WRAPPER = (
    "def wrap(fn):\n"
    "    return lambda self: 7\n"
    "\n"
    "\n"
    "class Box:\n"
    "    @wrap\n"
    "    def pick(self):\n"
    "        return 1\n"
    "\n"
    "\n"
    "def test_box():\n"
    "    assert Box().pick() == {claim}\n"
)


def test_the_wrapper_is_the_method_never_unsat(tmp_path: Path) -> None:
    truthful = run_source_through_real_solver(
        tmp_path / "t", _WRAPPER.format(claim="7")
    )

    assert truthful.verdict != "unsat", truthful.prove_doc


def test_the_plain_body_is_never_the_method(tmp_path: Path) -> None:
    # ``pick``'s own body returns 1; the class binds what ``wrap`` returned.
    # A claim read off the plain body is a lie, never ``sat``: the call is
    # owed or joined to the wrapper, never the written function.
    lying = run_source_through_real_solver(tmp_path / "l", _WRAPPER.format(claim="1"))

    assert lying.verdict != "sat", lying.prove_doc
