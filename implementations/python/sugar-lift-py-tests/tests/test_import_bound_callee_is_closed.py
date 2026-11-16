"""An import-bound callee head is a CLOSED coordinate, never a free Var.

`np.rot90(m)` under `import numpy as np` is not a method call on a value: `np`
is a lexical import binding, so the callee names the closed coordinate
`numpy.rot90`. Constructing the head as a receiver minted `np` as a universe
Var that no contract ever declared, and `ScopedFormula` refused it (correctly)
with `illegal free var(s): np`.

The binding comes from the ONE lexical import pass (reaching definitions in
``import_binding``), never from spelling. So the discrimination arm matters as
much as the positive one: a head that is NOT uniquely import-bound is never an
import coordinate. A name nothing binds halts with ``NameError`` where it is
read; a shadowed alias is the value that shadowed it. A fix that closes either
as an import has broken the detector.
"""

from __future__ import annotations

import os
import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile

from sugar_lift_py_tests.proofir.formulas import formula_from_ir
from sugar_lift_py_tests.proofir.scope import ScopedFormula
from sugar_lift_py_tests.proofir.sorts import UnknownSort
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1


def _post(source: str):
    directory = tempfile.mkdtemp()
    path = os.path.join(directory, "m.py")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(source)
    function = next(
        iter(
            SourceFile(
                path_source(path),
                construction_context=TreeConstructionContextV1.for_test_without_workspace(),
            ).functions()
        )
    )
    return _completed(function.sugar().desugar(None)).post()


def _completed(outcome):
    """The one completed face's value.  A call of a module member the import
    door did not cite may raise (``UnknownCallee:<target>``), and so may a
    dotted read of one (``ImportMemberValue.read``: the member may be absent,
    and the lifter holds no module's namespace)."""
    from sugar_lift_py_tests.outcome import Completed, Halted

    exits = outcome.exits
    completed = [face for face in exits if isinstance(face, Completed)]
    assert len(completed) == 1, exits
    assert all(
        face.effect.producer_node_owner.startswith("UnknownCallee:")
        or face.effect.producer_node_owner == "ImportMemberValue.read"
        for face in exits
        if isinstance(face, Halted)
    )
    return completed[0].value


def _application(post):
    """The application one evaluation's ``python:call_result`` names."""
    result = post.args[1]
    assert result.name == "python:call_result"
    return result.args[0]


def _scoped(post, formals: tuple[str, ...]) -> ScopedFormula:
    sort = UnknownSort(reason="lift is sort-silent; the compiler decides")
    allowed = {name: sort for name in (*formals, "out")}
    return ScopedFormula(formula_from_ir(post, var_sorts=allowed), allowed_vars=allowed)


def test_module_alias_call_head_projects_a_closed_coordinate() -> None:
    post = _post("import numpy as np\n\n\ndef turn(m):\n    return np.rot90(m)\n")
    assert _application(post).name == "call:numpy.rot90"
    scoped = _scoped(post, ("m",))
    assert scoped.formula.free_vars == {"m", "out"}


def test_dotted_import_head_closes_the_whole_chain() -> None:
    # `os.path.join` -- the same gap shape the pandas census catalogues with
    # `os` (docs/audits/pandas-gap-census.md, pandas-gap-21).
    post = _post("import os\n\n\ndef j(a, b):\n    return os.path.join(a, b)\n")
    assert _application(post).name == "call:os.path.join"
    assert _scoped(post, ("a", "b")).formula.free_vars == {"a", "b", "out"}


def test_from_import_module_binding_closes_too() -> None:
    post = _post(
        "from numpy import testing as t\n\n\ndef e(a, b):\n"
        "    return t.assert_equal(a, b)\n"
    )
    assert _application(post).name == "call:numpy.testing.assert_equal"


def test_showcase_shape_binds_through_the_local_assignment() -> None:
    # ``r[0][0]`` indexes an opaque call result, so each subscript may raise
    # (an UndeterminedRaiseEffect under the complement of its completion
    # atom). Every completed face still closes over ``out`` alone.
    from sugar_lift_py_tests.outcome import Completed, Halted

    directory = tempfile.mkdtemp()
    path = os.path.join(directory, "m.py")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(
            "import numpy as np\n\n\ndef test_rot90_quarter_turn():\n"
            "    r = np.rot90([[1, 2], [3, 4]])\n    return r[0][0]\n"
        )
    function = next(
        iter(
            SourceFile(
                path_source(path),
                construction_context=TreeConstructionContextV1.for_test_without_workspace(),
            ).functions()
        )
    )
    exits = function.sugar().desugar(None)
    halts = [face for face in exits.exits if isinstance(face, Halted)]
    owners = {face.effect.producer_node_owner for face in halts}
    # ``r[0]`` reads the call result; ``[0]`` reads that read's symbolic
    # result. Each undecided read names its own receiver.
    assert owners == {
        "CallSiteValue.subscript",
        "SymbolicValue.subscript",
        "UnknownCallee:numpy.rot90",
    }
    completed = [face for face in exits.exits if isinstance(face, Completed)]
    assert len(completed) == 1
    assert _scoped(completed[0].value.post(), ()).formula.free_vars == {"out"}


def _function_outcome(source: str):
    """The one reduction of the source's first function."""
    directory = tempfile.mkdtemp()
    path = os.path.join(directory, "m.py")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(source)
    function = next(
        iter(
            SourceFile(
                path_source(path),
                construction_context=TreeConstructionContextV1.for_test_without_workspace(),
            ).functions()
        )
    )
    return function.sugar().desugar(None)


def test_a_head_that_is_not_import_bound_is_an_unbound_name() -> None:
    # THE DISCRIMINATION. `zz` is bound by nothing, so it is never an import
    # coordinate, and it is no free Var either: Python raises ``NameError``
    # reading it, before the call it heads is made. The function is that one
    # halt -- no completion, no call, nothing for a scope to refuse.
    from sugar_lift_py_tests.effect import NameErrorEffect

    outcome = _function_outcome("def turn(m):\n    return zz.rot90(m)\n")
    assert outcome.halts() == outcome.exits
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, NameErrorEffect)
    assert halt.effect.name == "zz"
    assert halt.effect.exception_name == "NameError"


def test_a_shadowed_import_alias_is_not_import_bound() -> None:
    # The alias is rebound before the use, so the reaching definition is no
    # longer the import: the head is the formal ``m``, an ordinary receiver.
    # ``m`` is read bare (``np = m``, the argument), so its class is no input
    # of ``turn``'s contract: the call is the one unanswered call, two-faced
    # and owed (#7757 NEW-1), never a carrier waiting for an actual and never
    # the closed ``numpy.rot90`` coordinate.

    outcome = _function_outcome(
        "import numpy as np\n\n\ndef turn(m):\n    np = m\n    return np.rot90(m)\n"
    )
    owners = {halt.effect.producer_node_owner for halt in outcome.halts()}
    assert "UnknownCallee:rot90" in owners
    assert "UnknownCallee:numpy.rot90" not in owners


def test_a_parameter_method_call_is_untouched() -> None:
    # Not import-bound: the formal receiver's class is ``turn``'s ``class:m``
    # input, so the call is the dispatched edge (#7757 step 8), resolved at
    # prove where a caller binds the class -- never an import coordinate.
    outcome = _function_outcome("def turn(m):\n    return m.copy()\n")
    owners = {halt.effect.producer_node_owner for halt in outcome.halts()}
    assert "UnknownCallee:dispatch:copy" in owners
