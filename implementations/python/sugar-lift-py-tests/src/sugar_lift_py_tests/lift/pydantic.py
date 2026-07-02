# SPDX-License-Identifier: Apache-2.0
#
# sugar.lift.pydantic: lift Pydantic BaseModel field constraints to
# canonical IR.
#
# Cross-domain equivalence guarantee: a Pydantic model constraint that
# expresses the same runtime check as another annotation family MUST
# produce byte-for-byte identical IR. For example:
#
#   class User(BaseModel):
#       name: Annotated[str, Field(min_length=1)]
#
# must produce the same IR as Bean Validation @NotEmpty or JML
# //@ requires name != null && strlen(name) > 0.

from __future__ import annotations

import inspect
import json
import sys
from dataclasses import dataclass
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Type,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

from ..canonicalizer import encode_jcs
from ..ir import (
    ContractDecl,
    Formula,
    Term,
    Int,
    String,
    Bool,
    atomic,
    comparison_with_none_guard,
    eq,
    ne,
    gt,
    gte,
    lt,
    lte,
    make_var,
    num,
    str_const,
    bool_const,
    ctor,
    and_,
    or_,
    formula_to_value,
)

# ---------------------------------------------------------------------------
# Pydantic lift adapter
# ---------------------------------------------------------------------------


def lift_pydantic_model(model_cls: Type) -> List[ContractDecl]:
    """Lift all field constraints from a Pydantic BaseModel into IR contracts.

    Returns one ContractDecl per field that has recognizable constraints.
    The contract name is ``<ModelName>.<field_name>``.
    """
    decls: List[ContractDecl] = []
    model_name = model_cls.__name__

    # Pydantic v2 uses model_fields; v1 uses __fields__.
    fields = _get_fields(model_cls)
    if fields is None:
        return decls

    for field_name, field_info in fields.items():
        pres = _lift_field_constraints(field_name, field_info)
        if pres:
            # Build a single contract with all preconditions ANDed.
            folded = _fold_and(pres)
            decls.append(
                ContractDecl(
                    name=f"{model_name}.{field_name}",
                    pre=folded,
                )
            )

    return decls


def _get_fields(model_cls: Type) -> Optional[Dict[str, Any]]:
    """Return a dict of field_name -> field_info, or None if not a model."""
    # Pydantic v2
    if hasattr(model_cls, "model_fields"):
        return dict(model_cls.model_fields)
    # Pydantic v1
    if hasattr(model_cls, "__fields__"):
        return dict(model_cls.__fields__)
    return None


def _lift_field_constraints(field_name: str, field_info: Any) -> List[Formula]:
    """Extract constraints from a Pydantic field info object."""
    pres: List[Formula] = []
    var = make_var(field_name)

    # Pydantic v2: metadata list + field info attributes.
    metadata = getattr(field_info, "metadata", None) or []
    for item in metadata:
        f = _lift_metadata_item(var, item)
        if f is not None:
            pres.append(f)

    # Direct attributes on FieldInfo (v2) or Field (v1).
    ge = getattr(field_info, "ge", None)
    if ge is not None:
        pres.append(gte(var, num(ge)))
    le = getattr(field_info, "le", None)
    if le is not None:
        pres.append(lte(var, num(le)))
    gt_ = getattr(field_info, "gt", None)
    if gt_ is not None:
        pres.append(gt(var, num(gt_)))
    lt_ = getattr(field_info, "lt", None)
    if lt_ is not None:
        pres.append(lt(var, num(lt_)))
    min_length = getattr(field_info, "min_length", None)
    if min_length is not None:
        pres.append(gte(ctor("strlen", [var]), num(min_length)))
    max_length = getattr(field_info, "max_length", None)
    if max_length is not None:
        pres.append(lte(ctor("strlen", [var]), num(max_length)))
    pattern = getattr(field_info, "pattern", None)
    if pattern is not None:
        pres.append(atomic("matches", [var, str_const(str(pattern))]))

    # Annotated types with constraint objects.
    for item in metadata:
        if hasattr(item, "min_length") and item.min_length is not None:
            pres.append(gte(ctor("strlen", [var]), num(item.min_length)))
        if hasattr(item, "max_length") and item.max_length is not None:
            pres.append(lte(ctor("strlen", [var]), num(item.max_length)))
        if hasattr(item, "ge") and item.ge is not None:
            pres.append(gte(var, num(item.ge)))
        if hasattr(item, "le") and item.le is not None:
            pres.append(lte(var, num(item.le)))
        if hasattr(item, "gt") and item.gt is not None:
            pres.append(gt(var, num(item.gt)))
        if hasattr(item, "lt") and item.lt is not None:
            pres.append(lt(var, num(item.lt)))
        if hasattr(item, "pattern") and item.pattern is not None:
            pres.append(atomic("matches", [var, str_const(str(item.pattern))]))

    return pres


def _lift_metadata_item(var: Term, item: Any) -> Optional[Formula]:
    """Lift a single Pydantic metadata constraint object."""
    # Pydantic v2 uses Annotated metadata objects like:
    #   annotated_types.Gt, annotated_types.Ge, annotated_types.Len, etc.
    cls_name = type(item).__name__
    if cls_name in ("Gt", "GreaterThan"):
        return gt(var, num(getattr(item, "gt", getattr(item, "value", 0))))
    if cls_name in ("Ge", "GreaterThanOrEqual"):
        return gte(var, num(getattr(item, "ge", getattr(item, "value", 0))))
    if cls_name in ("Lt", "LessThan"):
        return lt(var, num(getattr(item, "lt", getattr(item, "value", 0))))
    if cls_name in ("Le", "LessThanOrEqual"):
        return lte(var, num(getattr(item, "le", getattr(item, "value", 0))))
    if cls_name in ("Len", "Length"):
        min_l = getattr(item, "min_length", None)
        max_l = getattr(item, "max_length", None)
        parts: List[Formula] = []
        if min_l is not None:
            parts.append(gte(ctor("strlen", [var]), num(min_l)))
        if max_l is not None:
            parts.append(lte(ctor("strlen", [var]), num(max_l)))
        return _fold_and(parts) if parts else None
    if cls_name in ("Pattern", "Regex"):
        return atomic(
            "matches",
            [var, str_const(str(getattr(item, "pattern", getattr(item, "value", ""))))],
        )
    # Skip unrecognized metadata.
    return None


def _fold_and(parts: List[Formula]) -> Formula:
    if len(parts) == 1:
        return parts[0]
    return and_(parts)


# ---------------------------------------------------------------------------
# Sugar bridge helpers: pydantic source/witness shape
# ---------------------------------------------------------------------------


def emit_pydantic_model_source(model_name: str, fields: List[Dict[str, Any]]) -> str:
    """Emit a small pydantic model surface from structured field specs."""
    lines = [f"class {model_name}(BaseModel):"]
    if not fields:
        lines.append("    pass")
        return "\n".join(lines) + "\n"
    for field in fields:
        name = str(field["name"])
        type_name = str(field.get("type", "Any"))
        args = (
            field.get("field_args") if isinstance(field.get("field_args"), dict) else {}
        )
        if args:
            rendered_args = ", ".join(
                f"{key}={_py_literal(value)}" for key, value in sorted(args.items())
            )
            lines.append(f"    {name}: {type_name} = Field(..., {rendered_args})")
        else:
            lines.append(f"    {name}: {type_name}")
    return "\n".join(lines) + "\n"


def lift_pydantic_model_witnesses(
    model_cls: Type,
    *,
    concept_site_cid: str | None = None,
    contract_cid: str | None = None,
    original_predicate_text: str | None = None,
) -> List[Dict[str, Any]]:
    """Lift pydantic fields into bind witness records with honest loss."""
    fields = _get_fields(model_cls)
    if fields is None:
        return []
    try:
        annotations = get_type_hints(model_cls, include_extras=True)
    except Exception:
        annotations = getattr(model_cls, "__annotations__", {})

    witnesses: List[Dict[str, Any]] = []
    for field_name, field_info in fields.items():
        annotation = annotations.get(
            field_name, getattr(field_info, "annotation", None)
        )
        formulas: List[Formula] = []
        is_optional = _is_optional_annotation(annotation)
        requiredness = _field_required(
            getattr(model_cls, "__name__", "<unknown>"), field_name, field_info
        )
        requiredness_loss_record: Dict[str, Any] = {}
        if isinstance(requiredness, _RequirednessUnknown):
            if not is_optional:
                requiredness_loss_record = requiredness.to_loss_record()
        elif requiredness and not is_optional:
            formulas.append(
                comparison_with_none_guard("≠", make_var(field_name), ctor("None", []))
            )
        type_name = _annotation_name(annotation)
        if type_name and type_name != "Any":
            formulas.append(
                atomic("is_type", [make_var(field_name), str_const(type_name)])
            )
        formulas.extend(_lift_field_constraints(field_name, field_info))

        for formula in formulas:
            predicate = _formula_to_json(formula)
            predicate_text = _formula_text(predicate)
            extension_fields: Dict[str, Any] = {
                "field": field_name,
                "loss_record": _merge_loss_records(
                    _pydantic_loss_record(
                        original_predicate_text,
                        predicate_text,
                    ),
                    requiredness_loss_record,
                ),
                "surface": "pydantic-field",
            }
            if concept_site_cid is not None:
                extension_fields["concept_site_cid"] = concept_site_cid
            if contract_cid is not None:
                extension_fields["contract_cid"] = contract_cid
            witnesses.append(
                {
                    "col": None,
                    "confidence_basis_points": 10000,
                    "extension_fields": extension_fields,
                    "line": None,
                    "predicate": predicate,
                    "predicate_text": predicate_text,
                    "role": "pre",
                    "source_kind": "native-surface",
                }
            )
    return witnesses


def _py_literal(value: Any) -> str:
    if isinstance(value, str):
        return repr(value)
    if isinstance(value, bool):
        return "True" if value else "False"
    if value is None:
        return "None"
    return str(value)


def _field_required(
    model_name: str, field_name: str, field_info: Any
) -> bool | "_RequirednessUnknown":
    is_required = getattr(field_info, "is_required", None)
    if callable(is_required):
        try:
            return bool(is_required())
        except Exception as exc:
            return gap_record(model_name, field_name, exc)
    required = getattr(field_info, "required", None)
    if required is not None:
        return bool(required)
    return getattr(field_info, "default", None) is ...


@dataclass(frozen=True)
class _RequirednessUnknown:
    model: str
    field: str
    caught: str
    reason: str

    @property
    def dropped_precondition(self) -> str:
        return f"{self.field} != None"

    def to_loss_record(self) -> Dict[str, Any]:
        return {
            "pydantic_requiredness_loss": {
                "model": self.model,
                "field": self.field,
                "caught": self.caught,
                "dropped_precondition": self.dropped_precondition,
                "reason": self.reason,
            }
        }


def gap_record(
    model_name: str, field_name: str, exc: Exception
) -> _RequirednessUnknown:
    return _RequirednessUnknown(
        model=model_name,
        field=field_name,
        caught=type(exc).__name__,
        reason=f"is_required() raised: {exc}",
    )


def _is_optional_annotation(annotation: Any) -> bool:
    args = get_args(annotation)
    return any(arg is type(None) for arg in args)


def _annotation_name(annotation: Any) -> str:
    if annotation is None:
        return "Any"
    origin = get_origin(annotation)
    if origin is not None and str(origin).endswith("Annotated"):
        args = get_args(annotation)
        if args:
            return _annotation_name(args[0])
    if annotation in (str, int, bool, float):
        return annotation.__name__
    name = getattr(annotation, "__name__", None)
    if isinstance(name, str):
        return name
    text = str(annotation)
    return text.replace("<class '", "").replace("'>", "")


def _formula_to_json(formula: Formula) -> Dict[str, Any]:
    return json.loads(encode_jcs(formula_to_value(formula)))


def _pydantic_loss_record(
    original_predicate_text: str | None,
    surface_predicate_text: str,
) -> Dict[str, Any]:
    if (
        original_predicate_text is None
        or original_predicate_text == surface_predicate_text
    ):
        return {}
    return {
        "pydantic_expressivity_gap": {
            "original_predicate_text": original_predicate_text,
            "surface_predicate_text": surface_predicate_text,
        }
    }


def _merge_loss_records(*records: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for record in records:
        merged.update(record)
    return merged


def _formula_text(formula: Dict[str, Any]) -> str:
    if formula.get("kind") == "atomic":
        name = formula.get("name")
        args = formula.get("args")
        if name == "is_type" and isinstance(args, list) and len(args) == 2:
            return f"type({_term_text(args[0])}) == {_term_text(args[1])}"
        if isinstance(name, str) and isinstance(args, list):
            if len(args) == 2:
                return f"{_term_text(args[0])} {_operator_text(name)} {_term_text(args[1])}"
            return f"{name}({', '.join(_term_text(arg) for arg in args)})"
    if formula.get("kind") in {"and", "or"} and isinstance(
        formula.get("operands"), list
    ):
        sep = f" {formula['kind']} "
        return sep.join(_formula_text(part) for part in formula["operands"])
    return "<formula>"


def _operator_text(name: str) -> str:
    return {"=": "==", "≠": "!=", "≥": ">=", "≤": "<="}.get(name, name)


def _term_text(term: Dict[str, Any]) -> str:
    if term.get("kind") == "var":
        return str(term.get("name"))
    if term.get("kind") == "const":
        value = term.get("value")
        return "None" if value is None else str(value)
    if term.get("kind") == "ctor":
        name = str(term.get("name"))
        args = term.get("args")
        if isinstance(args, list):
            return f"{name}({', '.join(_term_text(arg) for arg in args)})"
    return "<?>"
