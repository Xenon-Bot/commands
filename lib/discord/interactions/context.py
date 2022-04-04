__all__ = (
    "CommandContext",
    "ComponentContext",
    "CommandAutocompleteContext",
    "ModalContext"
)


class InteractionContext:
    def __init__(self, bot, payload):
        self.bot = bot
        self.payload = payload
        self._http_cache = {}

    def __getattr__(self, item):
        return getattr(self.payload, item)


class CommandContext(InteractionContext):
    def __init__(self, bot, command, payload, args):
        super().__init__(bot, payload)
        self.command = command
        self.args = args

    @property
    def resolved(self):
        return self.payload.data.resolved

    @property
    def target_id(self):
        return self.payload.data.target_id


class CommandAutocompleteContext(InteractionContext):
    def __init__(self, bot, command, payload, args):
        super().__init__(bot, payload)
        self.command = command
        self.args = args


class ComponentContext(InteractionContext):
    def __init__(self, bot, component, payload):
        super().__init__(bot, payload)
        self.component = component

    @property
    def custom_id(self):
        return self.payload.data.custom_id

    @property
    def values(self):
        return self.payload.data.values


class ModalContext(InteractionContext):
    def __init__(self, bot, modal, payload):
        super().__init__(bot, payload)
        self.modal = modal

    @property
    def custom_id(self):
        return self.payload.data.custom_id

    @property
    def components(self):
        return self.payload.data.components
