from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.source_fragment import SourceFragment

_TYPED_DICT_MODULES = frozenset({"typing", "typing_extensions"})


@dataclass(frozen=True)
class TypedDictTotalClassRecognition:
    total_value: SourceFragment


@dataclass(frozen=True)
class PydanticBaseModelExtraClassRecognition:
    extra_value: SourceFragment


def recognize_typed_dict_total_class(
    site: SourceFragment,
) -> TypedDictTotalClassRecognition | None:
    """Recognize the exact imported TypedDict + literal ``total`` partition."""
    if site.observed != "ClassDef" or site.class_decorators():
        return None
    bases = site.class_bases()
    keywords = site.class_keywords()
    if len(bases) != 1 or len(keywords) != 1:
        return None
    base_name = bases[0].dotted_expr_name()
    keyword = keywords[0]
    if base_name is None or keyword.keyword_arg_name() != "total":
        return None
    total_value = keyword.keyword_value()
    if (
        total_value.observed != "Constant"
        or type(total_value.literal_value()) is not bool
    ):
        return None

    try:
        root = SourceFragment.from_source(site.source, site.filename or "")
    except (SyntaxError, TypeError):
        return None
    authenticated_names: set[str] = set()
    for declaration in (
        declaration
        for fragment in root.fragments()
        for declaration in fragment.statements()
    ):
        if (
            declaration.observed != "ImportFrom"
            or declaration.importfrom_level() != 0
            or declaration.importfrom_module() not in _TYPED_DICT_MODULES
        ):
            continue
        for imported, alias in declaration.importfrom_names():
            if imported == "TypedDict":
                authenticated_names.add(alias or imported)
    if base_name not in authenticated_names:
        return None
    return TypedDictTotalClassRecognition(total_value=total_value)


def recognize_pydantic_base_model_extra_class(
    site: SourceFragment,
) -> PydanticBaseModelExtraClassRecognition | None:
    """Recognize authenticated Pydantic BaseModel with exact ``extra='allow'``."""
    from sugar_lift_py_tests.recognition.native_shape import (
        NativeShape,
        recognize_native_class_import,
        recognize_native_class_option,
    )

    if site.observed != "ClassDef" or site.class_decorators():
        return None
    bases = site.class_bases()
    keywords = site.class_keywords()
    if len(bases) != 1 or len(keywords) != 1:
        return None
    base_name = bases[0].dotted_expr_name()
    keyword = keywords[0]
    extra_value = keyword.keyword_value()
    if (
        base_name is None
        or extra_value.observed != "Constant"
        or type(extra_value.literal_value()) is not str
    ):
        return None

    try:
        root = SourceFragment.from_source(site.source, site.filename or "")
    except (SyntaxError, TypeError):
        return None
    authenticated_names: dict[str, NativeShape] = {}
    authenticated_modules: dict[str, str] = {}
    for declaration in (
        declaration
        for fragment in root.fragments()
        for declaration in fragment.statements()
    ):
        if (declaration.line, declaration.col) >= (site.line, site.col):
            break
        if (
            declaration.observed == "ImportFrom"
            and declaration.importfrom_level() == 0
        ):
            module = declaration.importfrom_module()
            for imported, alias in declaration.importfrom_names():
                bound_name = alias or imported
                authenticated_names.pop(bound_name, None)
                authenticated_modules.pop(bound_name, None)
                shape = recognize_native_class_import(module, imported)
                if shape is not None:
                    authenticated_names[bound_name] = shape
        elif declaration.observed == "Import":
            for imported, alias in declaration.import_names():
                head = imported.split(".", 1)[0]
                bound_name = alias or head
                authenticated_names.pop(bound_name, None)
                authenticated_modules[bound_name] = imported if alias else head
        else:
            if declaration.observed == "ClassDef":
                rebound_names = (declaration.class_name(),)
            elif declaration.observed in {"FunctionDef", "AsyncFunctionDef"}:
                rebound_names = (declaration.function_name(),)
            else:
                rebound_names = declaration.stored_or_deleted_names()
            for rebound_name in rebound_names:
                authenticated_names.pop(rebound_name, None)
                authenticated_modules.pop(rebound_name, None)

    base_shape = authenticated_names.get(base_name)
    if base_shape is None:
        head, separator, tail = base_name.partition(".")
        module = authenticated_modules.get(head)
        if not separator or module is None:
            return None
        qualified = f"{module}.{tail}"
        export_module, _, export_name = qualified.rpartition(".")
        base_shape = recognize_native_class_import(export_module, export_name)
    if base_shape is not NativeShape.PYDANTIC_BASE_MODEL:
        return None
    if (
        recognize_native_class_option(
            base_shape,
            keyword.keyword_arg_name(),
            extra_value.literal_value(),
        )
        is not NativeShape.PYDANTIC_EXTRA_ALLOW_CLASS_OPTION
    ):
        return None
    return PydanticBaseModelExtraClassRecognition(extra_value=extra_value)
