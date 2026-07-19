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
        """Expand literal parametrize rows only via import provenance + protocol.

        Authentication path (no logo Compare) — the real contract that #5612's
        loud stub reserved for this work:
        1. Resolve the decorator Call through ``imported_call_identity``
           (binding chain: import / assignment, shadow-aware).
        2. Look up that identity in the kit-loaded parametrize protocol table
           (``recognize_parametrize_decorator``). Production table is empty;
           missing → no expansion → loud FactoryPanic downstream.

        Spelling-only Attribute chains never authenticate. Coordinates arrive
        only through ``load_parametrize_protocol`` (kit/bridge/proof contract),
        never hard-coded as a vendor-string match in this module.
        """
        from sugar_lift_py_tests.recognition.callee_universe import (
            imported_call_identity,
        )
        from sugar_lift_py_tests.recognition.native_shape import (
            NativeShape,
            recognize_parametrize_decorator,
        )
        from sugar_lift_py_tests.source_fragment import SourceFragment

        recognized = []
        for decorator in site.node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            call = SourceFragment.from_node(
                decorator, site.filename, source=site.source
            )
            identity = imported_call_identity(call)
            if (
                recognize_parametrize_decorator(identity)
                is not NativeShape.PARAMETRIZE_DECORATOR
                or len(decorator.args) < 2
                or decorator.keywords
            ):
                continue
            try:
                raw_names = ast.literal_eval(decorator.args[0])
                raw_rows = ast.literal_eval(decorator.args[1])
            except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
                continue
            if isinstance(raw_names, str):
                names = tuple(part.strip() for part in raw_names.split(","))
            elif isinstance(raw_names, (tuple, list)):
                names = tuple(raw_names)
            else:
                continue
            if not names or any(
                not isinstance(name, str) or not name for name in names
            ):
                continue
            if not isinstance(raw_rows, (tuple, list)):
                continue
            rows = []
            for raw_row in raw_rows:
                if len(names) == 1:
                    row = (raw_row,)
                elif isinstance(raw_row, (tuple, list)):
                    row = tuple(raw_row)
                else:
                    rows = []
                    break
                if len(row) != len(names):
                    rows = []
                    break
                rows.append(row)
            if not rows:
                continue
            indexes = tuple(
                index
                for index in range(len(names))
                if all(
                    type(row[index]) in (str, int, float, bool, type(None))
                    for row in rows
                )
            )
            if indexes:
                recognized.append(
                    (
                        tuple(names[index] for index in indexes),
                        tuple(tuple(row[index] for index in indexes) for row in rows),
                    )
                )
        return tuple(recognized)
