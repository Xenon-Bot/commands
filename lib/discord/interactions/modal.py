from .checks import *
import types

__all__ = (
    "make_modal",
    "PartialModal"
)


def make_modal(cb, **kwargs):
    checks = []
    while isinstance(cb, Check):
        checks.append(cb)
        cb = cb.next

    values = {
        "callable": cb,
        "name": cb.__name__,
        "checks": checks,
    }

    values.update(kwargs)
    modal = PartialModal(**values)

    return modal


class PartialModal:
    def __init__(self, **kwargs):
        self.name = kwargs["name"]
        self.callable = kwargs["callable"]
        self.checks = kwargs.get("checks", [])

    def bind(self, obj):
        self.callable = types.MethodType(self.callable, obj)
