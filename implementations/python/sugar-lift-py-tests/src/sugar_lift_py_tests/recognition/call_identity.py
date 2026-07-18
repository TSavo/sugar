from __future__ import annotations


class CallIdentityRecognition:
    """Structural call identity owned by Call-family Sugars."""

    @classmethod
    def qualified_name(cls, fragment) -> str | None:
        if fragment.observed == "Name":
            return fragment.name_id()
        if fragment.observed == "Attribute":
            receiver = cls.qualified_name(fragment.attr_receiver())
            return (
                f"{receiver}.{fragment.attr_name()}" if receiver is not None else None
            )
        return None

    @classmethod
    def target_name(cls, site) -> str | None:
        function = site.call_function()
        if function.observed == "Name":
            return function.name_id()
        if function.observed == "Attribute":
            return function.attr_name()
        return None

    @classmethod
    def qualified_target_name(cls, site) -> str | None:
        return cls.qualified_name(site.call_function())

    @staticmethod
    def is_method_call(site) -> bool:
        return site.call_function().observed == "Attribute"
