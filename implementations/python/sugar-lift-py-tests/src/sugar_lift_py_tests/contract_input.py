"""What a function's contract takes beside its parameters (#7757, step 4).

A function's body reads, at its call, more than its parameters: an enclosing
function's cell a local ``def`` or a lambda captured, and the default its
``def`` statement bound for a parameter the call omits. The caller supplies
each at the call, as it supplies an actual for a parameter, so the contract
states each as a formal of its own, spelled ``<kind>:<name>``:

- ``cell:<name>``: a captured cell (``_captured_bindings``), supplied by the
  call term's ``py.closure(<name>, <value>)``;
- ``global:<name>``: a module global read at the call, supplied by
  ``py.global(<name>, <value>)``;
- ``default:<param>``: the default bound for ``<param>``, supplied by
  ``py.default(<param>, <value>)``; a parameter the call does not pass is
  bound to it.

Prove's one binder (``consistency::bind_call_arguments``) binds each from
the caller's named argument exactly as it binds an actual to a parameter. In
the function's own proof no caller supplies it: the body reads a cell as the
free input, as it reads a parameter (``FormalRefSugar``).

A module global is read as the free input too (step 5): the keys the module's
final binding of it reads through are bound to the input at the entry
(``call_site_sugar.bind_global_inputs``). The row states the value the
module's one run left for it (``call_site_sugar.stated_global_values``,
``inputValues``), and prove's one binder binds a ``global:<name>`` no call
supplies to that value, as it binds an omitted parameter to its default: a
call after import, and the row's own claims (pytest's call of a test
function), read the module-final value; a call made while the module runs
supplies the binding standing there (``py.global``). A class or a decorated
``def`` is a definition, never an input (#7757, decision (c)).
"""

from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.ir import PrimitiveSort

CELL_INPUT = "cell"
GLOBAL_INPUT = "global"
DEFAULT_INPUT = "default"

_INPUT_KINDS = (CELL_INPUT, GLOBAL_INPUT, DEFAULT_INPUT)


def input_formal(kind: str, name: str) -> str:
    """The contract formal an input of ``kind`` named ``name`` is spelled as."""
    if kind not in _INPUT_KINDS:
        raise ValueError(f"contract input kind is unknown: {kind!r}")
    if not name:
        raise ValueError("contract input name must be nonempty")
    return f"{kind}:{name}"


def is_contract_input(formal: str) -> bool:
    """True for a contract input's formal, never a parameter's: no Python
    identifier holds a colon."""
    return any(formal.startswith(f"{kind}:") for kind in _INPUT_KINDS)


@dataclass(frozen=True)
class ContractInputCoordinateV1:
    """The coordinate of one contract input, as a ``FormalParameterCoordinateV1``
    is of one parameter: the function it belongs to, its kind and name, and
    the Python ``Value`` sort every formal carries. An operation on the input
    waits for the caller's value as one on a parameter does
    (``NativeOperationExitCarrierV1``, keyed by ``coordinate_cid``)."""

    owner_definition_cid: str
    input_kind: str
    name: str
    sort: PrimitiveSort
    coordinate_cid: str

    @classmethod
    def mint(
        cls, *, owner_definition_cid: str, input_kind: str, name: str
    ) -> "ContractInputCoordinateV1":
        from sugar_lift_python_source.canonical import cid_of_json

        formal = input_formal(input_kind, name)
        return cls(
            owner_definition_cid,
            input_kind,
            name,
            PrimitiveSort("Value"),
            cid_of_json(
                {
                    "kind": "contract-input-coordinate",
                    "schemaVersion": "1",
                    "ownerDefinitionCid": owner_definition_cid,
                    "formal": formal,
                    "sort": {"kind": "primitive", "name": "Value"},
                }
            ),
        )

    @property
    def declared_name(self) -> str:
        """The contract formal this input is spelled as."""
        return input_formal(self.input_kind, self.name)


@dataclass(frozen=True)
class ContractInputV1:
    """One input of a function's contract: its coordinate, and the key the
    body reads it through (``read_cid``: a captured cell's coordinate), or
    ``None`` for an input not read through one coordinate: a default (the
    body reads the parameter it binds) and a module global (read through
    the keys of the module's binding of it, each bound to the free input at
    the entry, ``call_site_sugar.bind_global_inputs``)."""

    coordinate: ContractInputCoordinateV1
    read_cid: str | None = None

    @classmethod
    def mint(
        cls,
        *,
        owner_definition_cid: str,
        input_kind: str,
        name: str,
        read_cid: str | None = None,
    ) -> "ContractInputV1":
        return cls(
            ContractInputCoordinateV1.mint(
                owner_definition_cid=owner_definition_cid,
                input_kind=input_kind,
                name=name,
            ),
            read_cid,
        )

    @property
    def formal(self) -> str:
        return self.coordinate.declared_name

    def value(self):
        """The input as the function's own proof reads it: the free formal,
        carrying its coordinate as a parameter's ``FormalRefSugar`` does."""
        from sugar_lift_py_tests.floor import SymbolicValue
        from sugar_lift_py_tests.ir import make_var

        return SymbolicValue(make_var(self.formal), formal_coordinate=self.coordinate)


def bind_contract_inputs(ctx, inputs, *, owner: str):
    """``ctx`` with each input the body reads (``read_cid``) bound to its free
    formal (``ContractInputV1.value``), as a call binds a captured cell to the
    caller's value (``call_site_sugar.with_captured_values``). The function's
    own proof has no caller, so the value is the input itself. ``ctx`` comes
    back unchanged when nothing is read."""
    read = tuple(item for item in inputs if item.read_cid is not None)
    if not read:
        return ctx
    from dataclasses import replace

    from sugar_lift_py_tests.context import ReduceContext

    entered = ReduceContext.root(owner=owner) if ctx is None else ctx
    for item in read:
        if entered.temporal.value_if_bound(item.read_cid) is not None:
            continue
        entered = replace(
            entered,
            temporal=entered.temporal.bind_value(
                item.read_cid, item.value(), blame=owner
            ),
        )
    return entered
