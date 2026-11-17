from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_py_tests.sugar.witnesses import _assertion_pair

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
        # A local flows through its name to the assertion: the truthful twin
        # rides the identity, the lying twin asserts a different value -- the
        # pair proves the lift discriminates on what the name is bound to.
        return _assertion_pair(
            name="name_return",
            owner_sugar="NameSugar",
            statements="z = 5",
            truthful="z == 5",
            lying="z == 6",
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
                from sugar_lift_py_tests.temporal.temporal_binding import (
                    FormalActualBinding,
                )

                if isinstance(binding, FormalActualBinding):
                    # A formal a followed call bound to the caller's actual
                    # (a lambda's parameter): that actual as the formal holds
                    # it (``object_identity.as_bound_formals``), with the
                    # caller's currency where no other actual may reach it.
                    return ExitSet.completed(binding.value)
                from sugar_lift_py_tests.floor.object_identity import arrived

                # A module global, a generator's write: the value reached
                # this read by binding.
                return ExitSet.completed(arrived(binding.value, self.site))
            # A builtin is read only through the binding at this read
            # (``_builtin_floor_value``): a name a star import, a module or
            # function rebinding, or a parameter may bind is not the builtin.
            builtin = self._builtin_floor_value()
            if builtin is not None:
                return ExitSet.completed(builtin)
            # A module global only a star import may bind is the function's
            # free ``global:<name>`` input with no stated value: its contract
            # entry bound the global's undecided key to that input
            # (``call_site_sugar.bind_global_inputs``), as for a global the
            # module's run leaves undecided (#8802).
            held = self._star_import_global_value(temporal)
            if held is not None:
                from sugar_lift_py_tests.floor.object_identity import arrived

                return ExitSet.completed(arrived(held, self.site))
        # A module attribute the import system set (``__file__``,
        # ``__name__``, ...) that nothing in the source binds: the one
        # undecided read off the module, never the free name.
        faces = self._interpreter_module_attribute_faces()
        if faces is not None:
            return faces
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

    def _star_import_global_value(self, temporal):
        """The value bound under the undecided key of the module global this
        read reads, when only a star import may bind it
        (``SourceUnit.star_import_global_read``), else None.

        The tree keeps the read as this name, so an exception class read
        through it stays the undecided citation; its value is read through
        the one key an undecided global is read through
        (``nodes.undecided_module_binding_key``), which a function's own
        contract binds at its entry to its free ``global:<name>`` input
        (``call_site_sugar.bind_global_inputs``).  Where nothing bound the
        key (a read outside a function's own contract), None: the read stays
        the free name, as before."""
        from sugar_source_tree.nodes import Name, undecided_module_binding_key

        node = getattr(self.site, "node", None)
        unit = getattr(self.site, "unit", None)
        if unit is None or not isinstance(node, Name) or node.id != self.name:
            return None
        star_import_global_read = getattr(unit, "star_import_global_read", None)
        if star_import_global_read is None or not star_import_global_read(
            node.id, node.line_col_span()
        ):
            return None
        return temporal.value_if_bound(undecided_module_binding_key(unit, self.name))

    def _interpreter_module_attribute_faces(self):
        """The read of a module attribute the import system set before the
        body ran (``SourceUnit.interpreter_module_attribute_at``: ``__file__``,
        ``__name__``, ``__spec__``, ... where nothing in the source binds the
        name and no star import may), else None.

        Python reads the name off the module's own namespace (``LOAD_GLOBAL``
        / ``LOAD_NAME``), where the import system put it; what it holds is
        the loader's and the importer's to decide, never this source's, and
        the namespace may lack it (no ``__file__`` for a frozen module, no
        ``__path__`` outside a package).  So it is the one two-faced
        undecided read (``floor_value.undecided_attribute_result``) of the
        attribute off the module the import door spells
        (``module_coordinate``): it completes with
        ``python:attribute_result("<name>", python:module(<m>), <key>)`` under
        its completes atom, halts with an undetermined raise under the
        complement, and owes the ``undecided`` member, keyed per evaluation.
        No path, no module name and no ``NameError`` is decided.  Before, the
        read was the free name, and ``ScopedFormula`` refused its whole
        function by it (#7757: ``illegal free var(s): __file__``)."""
        from sugar_source_tree.nodes import Name

        node = getattr(self.site, "node", None)
        unit = getattr(self.site, "unit", None)
        if unit is None or not isinstance(node, Name) or node.id != self.name:
            return None
        reached = getattr(unit, "interpreter_module_attribute_at", None)
        if reached is None:
            return None
        module = reached(node.id, node.line_col_span())
        if module is None:
            return None
        from sugar_lift_py_tests.floor.floor_value import undecided_attribute_result
        from sugar_lift_py_tests.floor.import_member_value import module_coordinate

        return undecided_attribute_result(
            None,
            self.name,
            self.site,
            owner="NameSugar.interpreter_module_attribute",
            receiver_term=module_coordinate(module),
        )

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
