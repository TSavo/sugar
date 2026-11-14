from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair

_BUILTINS_PREFIX = "python:builtins."


@dataclass(frozen=True)
class NameSugar(ConstructedTermSugar):
    """A name that survives to the meaning layer is a free formal or builtin.

    substitute runs before sugar (FunctionDef.sugar), so every temporal binding
    -- a local assignment, a conditional phi -- is already rewritten into the
    tree: a bound name has been replaced by its value node and never reaches
    here. Parameters are masked by substitute and stay free formals. Builtin
    type and callable names (``tuple``, ``isinstance``, …) also survive as
    Name nodes: they were never local bindings. When a reduction context
    carries a temporal, such a name resolves to the builtin floor's value only
    when the read's own binding is the builtin namespace
    (``_builtin_floor_value``), never by its spelling; otherwise a free name
    is its symbolic Var.
    A name nothing in the module binds is not free: its read halts with
    ``NameError``.

    Meaning-only, node-constructed: no owns/new/role. A name is a leaf.
    """

    name: str
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        # A parameter flows through its name to the return: the truthful twin
        # rides the identity, the lying twin asserts a different value -- the
        # pair proves the lift discriminates on what the name is bound to.
        prefix = "def A(z):\n    return z\n\n"
        return _call_pair(
            name="name_return",
            owner_sugar="NameSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:name-construction",
            (self.occurrence_term(owner=owner), str_const(self.name)),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        from sugar_lift_py_tests.floor import SymbolicValue
        from sugar_lift_py_tests.ir import make_var
        from sugar_lift_py_tests.outcome import ExitSet

        # A binding the source made and the reduction installed (a formal, a
        # module-final global, a generator's write) is source-visible
        # testimony, not a free formal: following it is alias -> defining
        # source; minting a Var that erases it is fabricated free-name
        # testimony.  The builtin floor's own bindings, the root every
        # temporal starts from, are not such testimony: they hold a builtin
        # under its spelling, whatever this read is bound to.
        temporal = getattr(ctx, "temporal", None) if ctx is not None else None
        if temporal is not None:
            from sugar_lift_py_tests.temporal.builtin_name_bindings import (
                is_builtin_floor_binding,
            )

            binding = temporal.latest(self.name)
            if (
                binding is not None
                and binding.value is not None
                and not is_builtin_floor_binding(binding)
            ):
                from sugar_lift_py_tests.floor.object_identity import arrived

                # A formal's actual, a module global, a generator's write:
                # the value reached this read by binding.
                return ExitSet.completed(arrived(binding.value))
            # A builtin is read only through the binding at this read
            # (``_builtin_floor_value``): a name a star import, a module or
            # function rebinding, or a parameter may bind is not the builtin.
            builtin = self._builtin_floor_value()
            if builtin is not None:
                return ExitSet.completed(builtin)
        # A name nothing binds -- not local, not a parameter, not module-level,
        # not imported, not a builtin -- is no free variable: reading it raises
        # NameError, and that halt is its meaning.  A name only a star import
        # the lifter cannot read may bind is not bound nowhere: it is the free
        # operand below, never the builtin its spelling names.
        unit = getattr(self.site, "unit", None)
        name_bound_nowhere = getattr(unit, "name_bound_nowhere", None)
        if name_bound_nowhere is not None:
            if name_bound_nowhere(self.name):
                from sugar_lift_py_tests.effect import NameErrorEffect

                return ExitSet.halted(
                    NameErrorEffect.at(name=self.name, site=self.site)
                )
        return ExitSet.completed(SymbolicValue(make_var(self.name)))

    def _builtin_floor_value(self):
        """The builtin floor's value this read is bound to, else None.

        The value the builtin floor holds under the name the read's binding
        at its own coordinate names (``SourceUnit.name_reference_at``: the
        one import reference table, then the builtin namespace nothing
        rebinds), never under the read's spelling: ``int`` under ``from m
        import *``, after ``int = str`` in the module or the function, or as
        a parameter reaches no builtin value, and ``from builtins import int
        as I`` reaches ``int``'s.
        """
        from sugar_source_tree.nodes import Name

        node = getattr(self.site, "node", None)
        unit = getattr(self.site, "unit", None)
        if unit is None or not isinstance(node, Name) or node.id != self.name:
            return None
        target = unit.name_reference_at(node.id, node.line_col_span())
        if target is None or not target.startswith(_BUILTINS_PREFIX):
            return None
        from sugar_lift_py_tests.temporal.builtin_name_bindings import (
            builtin_name_temporal,
        )

        return builtin_name_temporal().value_if_bound(
            target[len(_BUILTINS_PREFIX) :]
        )
