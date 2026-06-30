from __future__ import annotations

from sugar_lift_py_tests.ir import Term, bool_const, ctor, make_var, num, str_const


def can_symbolic_term(site) -> bool:
    if site.observed == "Name":
        return True
    if site.observed == "PrimitiveLiteral":
        return isinstance(site.literal_value(), (bool, int, str))
    if site.observed == "List":
        return all(can_symbolic_term(item) for item in site.terms())
    if site.observed == "Attribute":
        return can_symbolic_term(site.attr_receiver())
    if site.observed == "Subscript":
        return can_symbolic_term(site.subscript_receiver()) and can_symbolic_term(
            site.subscript_index()
        )
    if site.observed != "Call":
        return False
    if site.call_target_name() is None:
        return False
    if not all(can_symbolic_term(arg) for arg in site.call_args()):
        return False
    return all(
        keyword.keyword_arg_name() is not None
        and can_symbolic_term(keyword.keyword_value())
        for keyword in site.call_keywords()
    )


def symbolic_term(site, *, owner: str) -> Term:
    if site.observed == "Name":
        return make_var(site.name_id())
    if site.observed == "PrimitiveLiteral":
        value = site.literal_value()
        if isinstance(value, bool):
            return bool_const(value)
        if isinstance(value, int):
            return num(value)
        if isinstance(value, str):
            return str_const(value)
    if site.observed == "List":
        return ctor("array", [symbolic_term(item, owner=owner) for item in site.terms()])
    if site.observed == "Attribute":
        return ctor(
            "py.attr",
            [
                symbolic_term(site.attr_receiver(), owner=owner),
                str_const(site.attr_name()),
            ],
        )
    if site.observed == "Subscript":
        return ctor(
            "py.subscript",
            [
                symbolic_term(site.subscript_receiver(), owner=owner),
                symbolic_term(site.subscript_index(), owner=owner),
            ],
        )
    if site.observed == "Call":
        target = site.call_target_name()
        if target is not None:
            args = [symbolic_term(arg, owner=owner) for arg in site.call_args()]
            for keyword in site.call_keywords():
                arg_name = keyword.keyword_arg_name()
                if arg_name is None:
                    raise TypeError(
                        f"write more Sugar for {owner} `**kwargs`: "
                        "add symbolic keyword expansion"
                    )
                args.append(
                    ctor(
                        f"kw:{arg_name}",
                        [symbolic_term(keyword.keyword_value(), owner=owner)],
                    )
                )
            return ctor(f"call:{target}", args)
    raise TypeError(
        f"write more Sugar for {owner} `{site.observed}`: "
        "add a symbolic term shape"
    )
