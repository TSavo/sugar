from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.ir import Term


@dataclass(frozen=True)
class ReceiverContractWitness:
    """Cited class ownership carried through a bound receiver call chain."""

    concrete_method_owner: str
    bound_self: Term
    returned_receiver_provenance: object | None = None

    def __post_init__(self) -> None:
        if not self.concrete_method_owner:
            raise ValueError("receiver witness requires a concrete method owner")


def cited_same_class_return(fn_site, witness: ReceiverContractWitness):
    """Return a same-owner witness only for ``return type(self)(...)`` source."""
    import ast

    self_name = fn_site.function_params()[0] if fn_site.function_params() else None
    if self_name is None:
        return None
    for node in ast.walk(fn_site.node):
        if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Call):
            continue
        constructor = node.value.func
        if not (
            isinstance(constructor, ast.Call)
            and isinstance(constructor.func, ast.Name)
            and constructor.func.id == "type"
            and len(constructor.args) == 1
            and isinstance(constructor.args[0], ast.Name)
            and constructor.args[0].id == self_name
        ):
            continue
        return ReceiverContractWitness(
            concrete_method_owner=witness.concrete_method_owner,
            bound_self=witness.bound_self,
            returned_receiver_provenance=fn_site.memento(),
        )
    return None
