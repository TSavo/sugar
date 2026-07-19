from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.source_fragment import SourceFragment

_TYPED_DICT_MODULES = frozenset({"typing", "typing_extensions"})


@dataclass(frozen=True)
class TypedDictTotalClassRecognition:
    total_value: SourceFragment


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
