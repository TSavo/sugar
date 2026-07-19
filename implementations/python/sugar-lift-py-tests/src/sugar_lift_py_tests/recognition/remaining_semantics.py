from __future__ import annotations

import ast


class RemainingSemanticRecognition:
    """Small semantic recognizers owned by their registered consumer Sugars."""

    @staticmethod
    def initializer_call_site(
        site, *, receiver_name: str, declared_bases: frozenset[str]
    ):
        from sugar_lift_py_tests.source_fragment import (
            InitializerCallSite,
            SourceFragment,
        )

        if not isinstance(site.node, ast.Expr) or not isinstance(
            site.node.value, ast.Call
        ):
            return None
        call = SourceFragment.from_node(
            site.node.value, site.filename, source=site.source
        )
        target = call.call_target_name()
        receiver = call.call_receiver()
        if receiver is None:
            if receiver_name in call.loaded_names():
                return None
            return InitializerCallSite("ordinary_call", call, target)
        zero_arg_super = (
            receiver.observed == "Call"
            and receiver.call_target_name() == "super"
            and not receiver.call_args()
            and not receiver.call_has_keywords()
        )
        arguments = call.call_args()
        if (
            target == "__setattr__"
            and zero_arg_super
            and not call.call_has_keywords()
            and len(arguments) == 2
            and arguments[0].observed == "PrimitiveLiteral"
            and isinstance(arguments[0].literal_value(), str)
        ):
            return InitializerCallSite(
                "super_setattr", call, arguments[0].literal_value()
            )
        if (
            target != "__init__"
            and not arguments
            and not call.call_has_keywords()
            and receiver.observed == "Name"
            and receiver.name_id() == receiver_name
        ):
            return InitializerCallSite("self_method", call, target)
        if target != "__init__":
            return None
        if zero_arg_super:
            return InitializerCallSite("super", call, "super")
        from sugar_lift_py_tests.recognition.call_identity import (
            CallIdentityRecognition,
        )

        base_coordinate = CallIdentityRecognition.qualified_name(receiver)
        if (
            not call.call_has_keywords()
            and arguments
            and arguments[0].observed == "Name"
            and arguments[0].name_id() == receiver_name
            and base_coordinate in declared_bases
        ):
            return InitializerCallSite("explicit_base", call, base_coordinate)
        return None

    @staticmethod
    def except_handler_type_names(site) -> tuple[str, ...] | None:
        from sugar_lift_py_tests.recognition.call_identity import (
            CallIdentityRecognition,
        )
        from sugar_lift_py_tests.source_fragment import SourceFragment

        typ = site.node.type
        if typ is None:
            return None
        nodes = typ.elts if isinstance(typ, ast.Tuple) else (typ,)
        names = tuple(
            name
            for node in nodes
            if (
                name := CallIdentityRecognition.qualified_name(
                    SourceFragment.from_node(node, site.filename, source=site.source)
                )
            )
            is not None
        )
        return names

    @staticmethod
    def boolop_kind(site) -> str:
        return "and" if isinstance(site.node.op, ast.And) else "or"

    @staticmethod
    def joined_str_static_text(site) -> str | None:
        pieces: list[str] = []
        for value in site.node.values:
            if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                return None
            pieces.append(value.value)
        return "".join(pieces)

    @staticmethod
    def literal_pytest_parametrize_rows(site):
        """Literal parametrize rows — logo-free stub until kit contract lands.

        #5603: hard-coded ``pytest.mark.parametrize`` / ``pytest`` string
        compares are illegal construction evidence. Window 289 owns the real
        parametrize protocol (kit/bridge/proof). Until that ships, return no
        rows (loud / unowned) rather than matching vendor spellings.
        """
        _ = site
        return ()
