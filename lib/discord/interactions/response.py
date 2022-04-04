from enum import IntEnum

from .component import *


__all__ = (
    "InteractionResponseType",
    "InteractionResponse"
)


class InteractionResponseType(IntEnum):
    PONG = 1
    CHANNEL_MESSAGE = 4
    DEFERRED = 5
    DEFERRED_MESSAGE_UPDATE = 6
    UPDATE_MESSAGE = 7
    APPLICATION_COMMAND_AUTOCOMPLETE_RESULT = 8
    MODAL = 9


class InteractionResponse:
    def __init__(self, type, content=None, **kwargs):
        self.type = type
        self.files = kwargs.pop("files", [])
        self.data = kwargs
        if "allowed_mentions" not in self.data:
           self.data["allowed_mmentions"] = {"parse": ["users"]}

        self.data["content"] = content
        if kwargs.pop("ephemeral", False):
            self.data["flags"] = 1 << 6

        components = kwargs.get("components", [])
        component = kwargs.get("component")
        if component is not None:
            components = [ActionRow(component)]

        elif len(components) != 0:
            if not isinstance(components[0], ActionRow):
                components = [ActionRow(*components)]

            elif not isinstance(components[0], Component):
                components = [ActionRow(*row) for row in components]

        self.data["components"] = [
            r.to_payload()
            for r in components
        ]

    @classmethod
    def pong(cls):
        return cls(InteractionResponseType.PONG)

    @classmethod
    def defer(cls, *args, **kwargs):
        return cls(InteractionResponseType.DEFERRED, *args, **kwargs)

    @classmethod
    def defer_message_update(cls, *args, **kwargs):
        return cls(InteractionResponseType.DEFERRED_MESSAGE_UPDATE, *args, **kwargs)

    @classmethod
    def message(cls, *args, **kwargs):
        return cls(InteractionResponseType.CHANNEL_MESSAGE, *args, **kwargs)

    @classmethod
    def update_message(cls, *args, **kwargs):
        return cls(InteractionResponseType.UPDATE_MESSAGE, *args, **kwargs)

    @classmethod
    def autocomplete(cls, *choices):
        return cls(InteractionResponseType.APPLICATION_COMMAND_AUTOCOMPLETE_RESULT, choices=[
            {
                "name": name,
                "value": value
            }
            for name, value in choices
        ])

    @classmethod
    def modal(cls, *args, **kwargs):
        return cls(InteractionResponseType.MODAL, *args, **kwargs)

    def to_dict(self):
        return {
            "type": self.type.value,
            "data": self.data
        }
