from .command import *
from .component import *
from .modal import *


__all__ = (
    "Module",
)


class Module:
    def __init__(self, bot):
        self.bot = bot

        self.commands = []
        self.components = []
        self.modals = []
        for name in dir(self):
            attr = getattr(self, name)
            if isinstance(attr, Command):
                attr.bind(self)
                self.commands.append(attr)

            elif isinstance(attr, PartialComponent):
                attr.bind(self)
                self.components.append(attr)

            elif isinstance(attr, PartialModal):
                attr.bind(self)
                self.modals.append(attr)

    @staticmethod
    def command(_callable=None, **kwargs):
        if _callable is None:
            def _predicate(_callable):
                return make_command(Command, _callable, **kwargs)

            return _predicate

        return make_command(Command, _callable, **kwargs)

    @staticmethod
    def component(_callable=None, **kwargs):
        if _callable is None:
            def _predicate(_callable):
                return make_component(_callable, **kwargs)

            return _predicate

        return make_component(_callable, **kwargs)

    @staticmethod
    def modal(_callable=None, **kwargs):
        if _callable is None:
            def _predicate(_callable):
                return make_modal(_callable, **kwargs)

            return _predicate

        return make_modal(_callable, **kwargs)

    async def post_setup(self):
        pass
