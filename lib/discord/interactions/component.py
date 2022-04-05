from enum import IntEnum
from uuid import uuid4
import types


__all__ = (
    "ComponentType",
    "Component",
    "ActionRow",
    "ButtonStyle",
    "Button",
    "SelectMenu",
    "SelectMenuOption",
    "PartialComponent",
    "make_component",
    "TextInput",
    "TextInputStyle"
)


class ComponentType(IntEnum):
    ACTION_ROW = 1
    BUTTON = 2
    SELECT_MENU = 3
    INPUT_TEXT = 4


def make_component(cb, **kwargs):
    values = {
        "callable": cb,
        "name": cb.__name__
    }

    values.update(kwargs)
    component = PartialComponent(**values)

    return component


class Component:
    def __init__(self, **kwargs):
        self.type = ComponentType(kwargs["type"])
        self.custom_id = kwargs.get("custom_id", uuid4().hex)
        args = kwargs.get("args", [])
        if len(args) != 0:
            self.custom_id = f"{self.custom_id}?{'&'.join(args)}"

    def to_payload(self):
        return {
            "type": self.type.value
        }


class ActionRow(Component):
    def __init__(self, *components):
        super().__init__(type=ComponentType.ACTION_ROW)
        self.components = list(components)

    def to_payload(self):
        return {
            "type": self.type.value,
            "components": [c.to_payload() for c in self.components]
        }


class ButtonStyle(IntEnum):
    PRIMARY = 1
    SECONDARY = 2
    SUCCESS = 3
    DANGER = 4
    LINK = 5


class Button(Component):
    def __init__(self, **kwargs):
        super().__init__(type=ComponentType.BUTTON, **kwargs)
        self.label = kwargs.get("label")
        self.url = kwargs.get("url")
        self.disabled = kwargs.get("disabled", False)

        default_style = ButtonStyle.LINK if "url" in kwargs else ButtonStyle.PRIMARY
        self.style = ButtonStyle(kwargs.get("style", default_style))

        self.emoji = kwargs.get("emoji")
        if type(self.emoji) == str:
            self.emoji = {"name": self.emoji}

    def to_payload(self):
        return {
            "type": self.type.value,
            "custom_id": self.custom_id if self.style != ButtonStyle.LINK else None,
            "label": self.label,
            "style": self.style.value,
            "url": self.url if self.style == ButtonStyle.LINK else None,
            "emoji": self.emoji,
            "disabled": self.disabled
        }


class SelectMenu(Component):
    def __init__(self, *options, **kwargs):
        super().__init__(type=ComponentType.SELECT_MENU, **kwargs)
        self.options = options
        self.placeholder = kwargs.get("placeholder")
        self.min_values = kwargs.get("min_values", 1)
        self.max_values = kwargs.get("max_values", 1)

    def to_payload(self):
        return {
            "type": self.type.value,
            "custom_id": self.custom_id,
            "placeholder": self.placeholder,
            "min_values": self.min_values,
            "max_values": self.max_values,
            "options": [o.to_payload() for o in self.options]
        }


class SelectMenuOption:
    def __init__(self, **kwargs):
        self.label = kwargs["label"]
        self.value = kwargs["value"]
        self.description = kwargs.get("description")

        self.emoji = kwargs.get("emoji")
        if type(self.emoji) == str:
            self.emoji = {"name": self.emoji}

        self.default = kwargs.get("default", False)

    def to_payload(self):
        return {
            "label": self.label,
            "value": self.value,
            "description": self.description,
            "emoji": self.emoji,
            "default": self.default
        }


class TextInputStyle(IntEnum):
    SHORT = 1
    PARAGRAPH = 2


class TextInput(Component):
    def __init__(self, **kwargs):
        super().__init__(type=ComponentType.INPUT_TEXT, **kwargs)
        self.label = kwargs["label"]
        self.style = kwargs.get("style", TextInputStyle.SHORT)
        self.placeholder = kwargs.get("placeholder")
        self.min_length = kwargs.get("min_length")
        self.max_length = kwargs.get("max_length")

    def to_payload(self):
        return {
            "type": self.type.value,
            "label": self.label,
            "style": self.style.value,
            "custom_id": self.custom_id,
            "placeholder": self.placeholder,
            "min_length": self.min_length,
            "max_length": self.max_length
        }


class PartialComponent:
    def __init__(self, **kwargs):
        self.name = kwargs["name"]
        self.callable = kwargs["callable"]

    def bind(self, obj):
        self.callable = types.MethodType(self.callable, obj)
