from __future__ import annotations

from decimal import Decimal

from sugar_lift_py_tests.ir import (
    Term,
    bool_const,
    ctor,
    make_var,
    num,
    real_lit,
    str_const,
)

_BINOP_SYMBOL: dict[str, str] = {
    "Add": "+",
    "Sub": "-",
    "Mult": "*",
    "Div": "/",
    "FloorDiv": "//",
    "Mod": "%",
    "Pow": "**",
    "BitXor": "^",
}
_COMPARE_TERMS = {
    "Eq",
    "NotEq",
    "Lt",
    "LtE",
    "Gt",
    "GtE",
    "Is",
    "IsNot",
    "In",
    "NotIn",
}


def can_symbolic_term(site) -> bool:
    if site.observed == "Name":
        return True
    if site.observed == "PrimitiveLiteral":
        return site.literal_value() is None or isinstance(
            site.literal_value(),
            (bool, int, float, str),
        )
    if site.observed == "Constant":
        return isinstance(site.literal_value(), (bytes, complex))
    if site.observed == "List":
        return all(can_symbolic_term(item) for item in site.terms())
    if site.observed == "Tuple":
        return all(can_symbolic_term(item) for item in site.terms())
    if site.observed == "Dict":
        return all(
            (key is None or can_symbolic_term(key)) and can_symbolic_term(value)
            for key, value in site.dict_entries()
        )
    if site.observed == "Attribute":
        return can_symbolic_term(site.attr_receiver())
    if site.observed == "Subscript":
        return can_symbolic_term(site.subscript_receiver()) and can_symbolic_term(
            site.subscript_index()
        )
    if site.observed == "Slice":
        return all(
            bound is None or can_symbolic_term(bound)
            for bound in (
                site.slice_lower(),
                site.slice_upper(),
                site.slice_step(),
            )
        )
    if site.observed == "BinOp":
        return (
            site.operator_kind() in _BINOP_SYMBOL
            and can_symbolic_term(site.binop_left())
            and can_symbolic_term(site.binop_right())
        )
    if site.observed == "UnaryOp":
        return site.operator_kind() in {"UAdd", "USub"} and can_symbolic_term(
            site.unaryop_operand()
        )
    if site.observed == "Compare":
        comparators = site.compare_comparators()
        return (
            bool(comparators)
            and len(site.compare_ops()) == len(comparators)
            and all(operator in _COMPARE_TERMS for operator in site.compare_ops())
            and all(
                can_symbolic_term(operand)
                for operand in [site.compare_left(), *comparators]
            )
        )
    if site.observed == "JoinedStr":
        return all(can_symbolic_term(fragment) for fragment in site.fragments())
    if site.observed == "FormattedValue":
        terms = site.terms()
        return bool(terms) and all(can_symbolic_term(term) for term in terms)
    if site.observed in {"GeneratorExp", "comprehension"}:
        return all(can_symbolic_term(fragment) for fragment in site.fragments())
    if site.observed != "Call":
        return False
    if site.call_target_name() is None:
        return False
    receiver = site.call_receiver()
    if receiver is not None and not can_symbolic_term(receiver):
        return False
    if not all(can_symbolic_term(arg) for arg in site.call_args()):
        return False
    return all(
        keyword.keyword_arg_name() is not None
        and can_symbolic_term(keyword.keyword_value())
        for keyword in site.call_keywords()
    )


def symbolic_term(
    site,
    *,
    owner: str,
    import_aliases: dict[str, str] | None = None,
    from_imports: dict[str, tuple[str, str]] | None = None,
    name_resolver=None,
    external_bridge_sink=None,
) -> Term:
    import_aliases = import_aliases or {}
    from_imports = from_imports or {}
    name_resolver = name_resolver or {}
    if site.observed == "Name":
        return make_var(site.name_id())
    if site.observed == "PrimitiveLiteral":
        value = site.literal_value()
        if isinstance(value, bool):
            return bool_const(value)
        if isinstance(value, int):
            return num(value)
        if isinstance(value, float):
            return _real_part_term(value)
        if isinstance(value, str):
            return str_const(value)
        if value is None:
            return ctor("None", [])
    if site.observed == "Constant":
        value = site.literal_value()
        if isinstance(value, bytes):
            return ctor("python:bytes", [str_const(value.hex())])
        if isinstance(value, complex):
            return ctor(
                "py.complex",
                [
                    _real_part_term(value.real),
                    _real_part_term(value.imag),
                ],
            )
    if site.observed == "List":
        return ctor(
            "array",
            [
                symbolic_term(
                    item,
                    owner=owner,
                    import_aliases=import_aliases,
                    from_imports=from_imports,
                    name_resolver=name_resolver,
                    external_bridge_sink=external_bridge_sink,
                )
                for item in site.terms()
            ],
        )
    if site.observed == "Dict":
        return ctor(
            "python:dict",
            [
                ctor(
                    "python:dict_entry",
                    [
                        (
                            ctor("None", [])
                            if key is None
                            else symbolic_term(
                                key,
                                owner=owner,
                                import_aliases=import_aliases,
                                from_imports=from_imports,
                                name_resolver=name_resolver,
                                external_bridge_sink=external_bridge_sink,
                            )
                        ),
                        symbolic_term(
                            value,
                            owner=owner,
                            import_aliases=import_aliases,
                            from_imports=from_imports,
                            name_resolver=name_resolver,
                            external_bridge_sink=external_bridge_sink,
                        ),
                    ],
                )
                for key, value in site.dict_entries()
            ],
        )
    if site.observed == "Tuple":
        return ctor(
            "tuple",
            [
                symbolic_term(
                    item,
                    owner=owner,
                    import_aliases=import_aliases,
                    from_imports=from_imports,
                    name_resolver=name_resolver,
                    external_bridge_sink=external_bridge_sink,
                )
                for item in site.terms()
            ],
        )
    if site.observed == "Attribute":
        return ctor(
            "py.attr",
            [
                symbolic_term(
                    site.attr_receiver(),
                    owner=owner,
                    import_aliases=import_aliases,
                    from_imports=from_imports,
                    name_resolver=name_resolver,
                    external_bridge_sink=external_bridge_sink,
                ),
                str_const(site.attr_name()),
            ],
        )
    if site.observed == "Subscript":
        return ctor(
            "py.subscript",
            [
                symbolic_term(
                    site.subscript_receiver(),
                    owner=owner,
                    import_aliases=import_aliases,
                    from_imports=from_imports,
                    name_resolver=name_resolver,
                    external_bridge_sink=external_bridge_sink,
                ),
                symbolic_term(
                    site.subscript_index(),
                    owner=owner,
                    import_aliases=import_aliases,
                    from_imports=from_imports,
                    name_resolver=name_resolver,
                    external_bridge_sink=external_bridge_sink,
                ),
            ],
        )
    if site.observed == "Slice":
        return ctor(
            "py.slice",
            [
                _optional_slice_term(
                    site.slice_lower(),
                    owner=owner,
                    import_aliases=import_aliases,
                    from_imports=from_imports,
                    name_resolver=name_resolver,
                    external_bridge_sink=external_bridge_sink,
                ),
                _optional_slice_term(
                    site.slice_upper(),
                    owner=owner,
                    import_aliases=import_aliases,
                    from_imports=from_imports,
                    name_resolver=name_resolver,
                    external_bridge_sink=external_bridge_sink,
                ),
                _optional_slice_term(
                    site.slice_step(),
                    owner=owner,
                    import_aliases=import_aliases,
                    from_imports=from_imports,
                    name_resolver=name_resolver,
                    external_bridge_sink=external_bridge_sink,
                ),
            ],
        )
    if site.observed == "BinOp":
        symbol = _BINOP_SYMBOL.get(site.operator_kind())
        if symbol is not None:
            return ctor(
                symbol,
                [
                    symbolic_term(
                        site.binop_left(),
                        owner=owner,
                        import_aliases=import_aliases,
                        from_imports=from_imports,
                        name_resolver=name_resolver,
                        external_bridge_sink=external_bridge_sink,
                    ),
                    symbolic_term(
                        site.binop_right(),
                        owner=owner,
                        import_aliases=import_aliases,
                        from_imports=from_imports,
                        name_resolver=name_resolver,
                        external_bridge_sink=external_bridge_sink,
                    ),
                ],
            )
    if site.observed == "UnaryOp":
        operator = site.operator_kind()
        operand_site = site.unaryop_operand()
        if operator == "UAdd":
            return symbolic_term(
                operand_site,
                owner=owner,
                import_aliases=import_aliases,
                from_imports=from_imports,
                name_resolver=name_resolver,
                external_bridge_sink=external_bridge_sink,
            )
        if operator == "USub":
            literal = _negated_numeric_literal(operand_site)
            if literal is not None:
                return literal
            return ctor(
                "py.neg",
                [
                    symbolic_term(
                        operand_site,
                        owner=owner,
                        import_aliases=import_aliases,
                        from_imports=from_imports,
                        name_resolver=name_resolver,
                        external_bridge_sink=external_bridge_sink,
                    )
                ],
            )
    if site.observed == "Compare":
        pieces = []
        operands = [site.compare_left(), *site.compare_comparators()]
        for operator, left, right in zip(site.compare_ops(), operands, operands[1:]):
            pieces.append(
                ctor(
                    f"py.compare:{operator}",
                    [
                        symbolic_term(
                            left,
                            owner=owner,
                            import_aliases=import_aliases,
                            from_imports=from_imports,
                            name_resolver=name_resolver,
                            external_bridge_sink=external_bridge_sink,
                        ),
                        symbolic_term(
                            right,
                            owner=owner,
                            import_aliases=import_aliases,
                            from_imports=from_imports,
                            name_resolver=name_resolver,
                            external_bridge_sink=external_bridge_sink,
                        ),
                    ],
                )
            )
        if len(pieces) == 1:
            return pieces[0]
        return ctor("py.compare:chain", pieces)
    if site.observed == "JoinedStr":
        return ctor(
            "py.fstring",
            [
                symbolic_term(
                    fragment,
                    owner=owner,
                    import_aliases=import_aliases,
                    from_imports=from_imports,
                    name_resolver=name_resolver,
                    external_bridge_sink=external_bridge_sink,
                )
                for fragment in site.fragments()
            ],
        )
    if site.observed == "FormattedValue":
        terms = [
            symbolic_term(
                term,
                owner=owner,
                import_aliases=import_aliases,
                from_imports=from_imports,
                name_resolver=name_resolver,
                external_bridge_sink=external_bridge_sink,
            )
            for term in site.terms()
        ]
        if len(terms) == 1:
            return terms[0]
        return ctor("py.formatted", terms)
    if site.observed in {"GeneratorExp", "comprehension"}:
        return ctor(
            "py.generator" if site.observed == "GeneratorExp" else "py.comprehension",
            [
                symbolic_term(
                    fragment,
                    owner=owner,
                    import_aliases=import_aliases,
                    from_imports=from_imports,
                    name_resolver=name_resolver,
                    external_bridge_sink=external_bridge_sink,
                )
                for fragment in site.fragments()
            ],
        )
    if site.observed == "Call":
        import_target = site.call_import_target_name(import_aliases, from_imports)
        target = import_target or site.call_target_name()
        if target is not None:
            args = []
            receiver = site.call_receiver()
            if import_target is None and receiver is not None:
                args.append(
                    symbolic_term(
                        receiver,
                        owner=owner,
                        import_aliases=import_aliases,
                        from_imports=from_imports,
                        name_resolver=name_resolver,
                        external_bridge_sink=external_bridge_sink,
                    )
                )
            args.extend(
                symbolic_term(
                    arg,
                    owner=owner,
                    import_aliases=import_aliases,
                    from_imports=from_imports,
                    name_resolver=name_resolver,
                    external_bridge_sink=external_bridge_sink,
                )
                for arg in site.call_args()
            )
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
                        [
                            symbolic_term(
                                keyword.keyword_value(),
                                owner=owner,
                                import_aliases=import_aliases,
                                from_imports=from_imports,
                                name_resolver=name_resolver,
                                external_bridge_sink=external_bridge_sink,
                            )
                        ],
                    )
                )
            if (
                import_target is not None
                and import_target not in name_resolver
                and external_bridge_sink is not None
            ):
                external_bridge_sink.append(
                    {
                        "targetSymbol": f"call:{import_target}",
                        "targetName": import_target,
                        "line": site.line,
                        "column": site.col,
                        "argTerms": args,
                    }
                )
            return ctor(f"call:{target}", args)
    raise TypeError(
        f"write more Sugar for {owner} `{site.observed}`: " "add a symbolic term shape"
    )


def _optional_slice_term(
    site,
    *,
    owner: str,
    import_aliases: dict[str, str],
    from_imports: dict[str, tuple[str, str]],
    name_resolver,
    external_bridge_sink,
) -> Term:
    if site is None:
        return ctor("None", [])
    return symbolic_term(
        site,
        owner=owner,
        import_aliases=import_aliases,
        from_imports=from_imports,
        name_resolver=name_resolver,
        external_bridge_sink=external_bridge_sink,
    )


def _real_part_term(value: float) -> Term:
    return real_lit(format(Decimal(str(value)), "f"))


def _negated_numeric_literal(site) -> Term | None:
    if site.observed != "PrimitiveLiteral":
        return None
    value = site.literal_value()
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return num(-value)
    if isinstance(value, float):
        return _real_part_term(-value)
    return None
