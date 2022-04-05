import types

__all__ = (
    "make_modal",
    "PartialModal"
)


def make_modal(cb, **kwargs):
    values = {
        "callable": cb,
        "name": cb.__name__,
    }

    values.update(kwargs)
    modal = PartialModal(**values)

    return modal


class PartialModal:
    def __init__(self, **kwargs):
        self.name = kwargs["name"]
        self.callable = kwargs["callable"]

    def bind(self, obj):
        self.callable = types.MethodType(self.callable, obj)
